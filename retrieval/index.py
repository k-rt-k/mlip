"""CPU cosine retrieval with explicit FAISS metrics, stable IDs and persistence.

search accepts a (queries, dimension) matrix. Scores are inner products of
normalized vectors. Missing IVF neighbors retain row=-1, song_id=None and
score=-inf; callers must not substitute another song. Indexes are immutable
apart from query-time nprobe/efSearch. Search parameter mutation is not thread
safe; tune before concurrent serving. FAISS OpenMP thread settings are global.
"""

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import hashlib
import json
import math
import os
import shutil
import tempfile
import time

import faiss
import numpy as np

from .catalog import normalized_vectors


@dataclass(frozen=True)
class IndexConfig:
    method: str
    nlist: int | None = None
    nprobe: int | None = None
    training_sample_size: int | None = None
    seed: int = 0
    m: int | None = None
    ef_construction: int | None = None
    ef_search: int | None = None

    def __post_init__(self):
        if self.method not in ("exact", "ivf", "hnsw"):
            raise ValueError("method must be exact, ivf or hnsw")
        for name in (
            "nlist",
            "nprobe",
            "training_sample_size",
            "m",
            "ef_construction",
            "ef_search",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive integer")
        if type(self.seed) is not int or not 0 <= self.seed < 2**31:
            raise ValueError("seed must be an integer in [0, 2**31)")
        if self.method == "ivf":
            if self.nlist is None or self.nprobe is None or self.nprobe > self.nlist:
                raise ValueError("IVF requires 1 <= nprobe <= nlist")
        elif any(
            getattr(self, n) is not None
            for n in ("nlist", "nprobe", "training_sample_size")
        ):
            raise ValueError("IVF parameters require method=ivf")
        if self.method == "hnsw":
            if (
                self.m is None
                or self.m < 2
                or self.ef_construction is None
                or self.ef_search is None
            ):
                raise ValueError(
                    "HNSW requires m >= 2 and positive ef_construction/ef_search"
                )
        elif any(
            getattr(self, n) is not None for n in ("m", "ef_construction", "ef_search")
        ):
            raise ValueError("HNSW parameters require method=hnsw")

    def construction_key(self):
        values = asdict(self)
        values.pop("nprobe")
        values.pop("ef_search")
        return json.dumps(values, sort_keys=True)


@dataclass
class SearchResult:
    scores: np.ndarray
    rows: np.ndarray
    song_ids: tuple


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class RetrievalIndex:
    def __init__(self, index, ids, config, corpus_fingerprint, build_info):
        self.index, self.ids, self.config = index, tuple(ids), config
        self.corpus_fingerprint, self.build_info = corpus_fingerprint, build_info

    @classmethod
    def build(cls, corpus, config):
        start = time.perf_counter()
        vectors = corpus.vectors
        n, d = vectors.shape
        info = {
            "threads": faiss.omp_get_max_threads(),
            "training_sample_size": 0,
            "training_seed": None,
        }
        if config.method == "exact":
            index = faiss.IndexFlatIP(d)
        elif config.method == "ivf":
            sample_size = min(n, config.training_sample_size or n)
            if config.nlist > sample_size:
                raise ValueError("IVF nlist exceeds corpus/training sample size")
            index = faiss.IndexIVFFlat(
                faiss.IndexFlatIP(d), d, config.nlist, faiss.METRIC_INNER_PRODUCT
            )
            index.cp.seed = config.seed
            # Prevent FAISS silently subsampling our already selected training rows.
            index.cp.max_points_per_centroid = max(
                index.cp.max_points_per_centroid, math.ceil(sample_size / config.nlist)
            )
            if sample_size < n:
                rows = np.sort(
                    np.random.default_rng(config.seed).choice(
                        n, sample_size, replace=False
                    )
                )
                training = vectors[rows]
            else:
                training = vectors
            index.train(training)
            info.update(
                training_sample_size=sample_size,
                training_seed=config.seed,
                clustering_iterations=index.cp.niter,
                clustering_spherical=index.cp.spherical,
                min_points_per_centroid=index.cp.min_points_per_centroid,
                max_points_per_centroid=index.cp.max_points_per_centroid,
            )
            index.nprobe = config.nprobe
            del training
        else:
            index = faiss.IndexHNSWFlat(d, config.m, faiss.METRIC_INNER_PRODUCT)
            index.hnsw.efConstruction = config.ef_construction
            index.hnsw.efSearch = config.ef_search
        index.add(vectors)
        info["construction_seconds"] = time.perf_counter() - start
        return cls(index, corpus.ids, config, corpus.fingerprint, info)

    def search(self, query_embeddings, k):
        if type(k) is not int or not 1 <= k <= len(self.ids):
            raise ValueError("k must be a positive integer no larger than the catalog")
        queries = normalized_vectors(
            query_embeddings, dimension=self.index.d, allow_empty=True
        )
        if not len(queries):
            return SearchResult(
                np.empty((0, k), dtype="float32"), np.empty((0, k), dtype="int64"), ()
            )
        scores, rows = self.index.search(queries, k)
        scores[rows < 0] = -np.inf
        # Deterministic ordering within the returned set; boundary ties may
        # still select different equally scoring neighbors across methods.
        for i in range(len(rows)):
            order = np.lexsort(
                (np.where(rows[i] < 0, len(self.ids), rows[i]), -scores[i])
            )
            rows[i], scores[i] = rows[i, order], scores[i, order]
        names = tuple(
            tuple(self.ids[int(row)] if row >= 0 else None for row in line)
            for line in rows
        )
        return SearchResult(scores, rows, names)

    def set_search_parameters(self, *, nprobe=None, ef_search=None):
        changes = {
            k: v
            for k, v in [("nprobe", nprobe), ("ef_search", ef_search)]
            if v is not None
        }
        config = replace(self.config, **changes)
        if nprobe is not None:
            self.index.nprobe = nprobe
        if ef_search is not None:
            self.index.hnsw.efSearch = ef_search
        self.config = config

    def save(self, path):
        """Publish a new artifact directory atomically; never overwrite a prior index."""
        path = Path(path)
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}-", dir=path.parent))
        try:
            faiss.write_index(self.index, str(temporary / "index.faiss"))
            (temporary / "catalog.json").write_text(
                json.dumps(self.ids, ensure_ascii=False), encoding="utf-8"
            )
            metadata = {
                "schema_version": 1,
                "metric": "cosine-via-normalized-inner-product",
                "faiss_version": faiss.__version__,
                "config": asdict(self.config),
                "dimension": self.index.d,
                "count": len(self.ids),
                "corpus_fingerprint": self.corpus_fingerprint,
                "build_info": self.build_info,
                "sha256": {
                    n: checksum(temporary / n) for n in ("index.faiss", "catalog.json")
                },
            }
            (temporary / "metadata.json").write_text(
                json.dumps(metadata, indent=2) + "\n"
            )
            os.rename(temporary, path)
        except BaseException:
            shutil.rmtree(temporary)
            raise

    @classmethod
    def load(cls, path):
        """Load trusted local artifacts; checksums detect accidental swaps/corruption."""
        path = Path(path)
        meta = json.loads((path / "metadata.json").read_text())
        if (
            meta.get("schema_version") != 1
            or meta.get("metric") != "cosine-via-normalized-inner-product"
        ):
            raise ValueError("unsupported index metadata")
        for name in ("index.faiss", "catalog.json"):
            if checksum(path / name) != meta["sha256"][name]:
                raise ValueError(f"checksum mismatch: {name}")
        ids = json.loads((path / "catalog.json").read_text())
        if (
            not isinstance(ids, list)
            or any(not isinstance(i, str) or not i.strip() for i in ids)
            or len(set(ids)) != len(ids)
            or len(ids) != meta["count"]
        ):
            raise ValueError("invalid catalog mapping")
        config = IndexConfig(**meta["config"])
        index = faiss.read_index(str(path / "index.faiss"))
        expected = {
            "exact": faiss.IndexFlatIP,
            "ivf": faiss.IndexIVFFlat,
            "hnsw": faiss.IndexHNSWFlat,
        }[config.method]
        if (
            not isinstance(index, expected)
            or index.metric_type != faiss.METRIC_INNER_PRODUCT
            or index.d != meta["dimension"]
            or index.ntotal != len(ids)
            or not index.is_trained
        ):
            raise ValueError("FAISS index and metadata disagree")
        if config.method == "ivf" and index.nlist != config.nlist:
            raise ValueError("IVF construction configuration mismatch")
        if config.method == "hnsw" and (
            index.hnsw.nb_neighbors(1) != config.m
            or index.hnsw.efConstruction != config.ef_construction
        ):
            raise ValueError("HNSW construction configuration mismatch")
        result = cls(index, ids, config, meta["corpus_fingerprint"], meta["build_info"])
        result.set_search_parameters(nprobe=config.nprobe, ef_search=config.ef_search)
        return result
