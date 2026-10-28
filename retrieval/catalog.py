"""Load Kartik's ids/vectors NPZ files into an ordered, normalized catalog.

Accept a single clap.npz or a directory of NPZ chunks (including shard dirs).
Files are traversed lexicographically; IDs retain their within-file row order.
Distinct IDs with identical vectors are retained: recording deduplication and
Spotify/Deezer/YouTube joins belong to catalog preparation, not the index.
"""

from pathlib import Path
import hashlib
import json

import numpy as np


def normalized_vectors(values, *, dimension=None, allow_empty=False):
    """Return a private float32 cosine matrix (unit tolerance 1e-6); reject invalid rows."""
    raw = np.asarray(values)
    if raw.ndim != 2 or raw.shape[1] == 0 or raw.dtype.kind not in "iuf":
        raise ValueError(
            "vectors must be a real numeric matrix with a positive dimension"
        )
    if dimension is not None and raw.shape[1] != dimension:
        raise ValueError(
            f"query dimension {raw.shape[1]} differs from index dimension {dimension}"
        )
    if not allow_empty and not len(raw):
        raise ValueError("vectors must contain at least one row")
    with np.errstate(over="ignore", invalid="ignore"):
        matrix = np.array(raw, dtype=np.float32, order="C", copy=True)
        norms = np.linalg.norm(matrix, axis=1)
    if (
        not np.isfinite(matrix).all()
        or not np.isfinite(norms).all()
        or (norms <= 0).any()
    ):
        raise ValueError("vectors must be finite, nonzero and representable in float32")
    # Preserve already-unit float32 rows, so saving/reloading keeps their bits
    # and fingerprint stable. Normalize other rows independently of the batch.
    needs_normalization = np.abs(norms - 1) > 1e-6
    np.divide(matrix, norms[:, None], out=matrix, where=needs_normalization[:, None])
    return matrix


class EmbeddingCatalog:
    """Ordered song IDs plus normalized rows; the fingerprint includes both."""

    def __init__(self, ids, vectors):
        self.ids = tuple(ids)
        if any(not isinstance(i, str) or not i.strip() for i in self.ids):
            raise ValueError("IDs must be nonempty strings")
        if len(set(self.ids)) != len(self.ids):
            raise ValueError(
                "duplicate song IDs; namespaces/catalogs must be disambiguated explicitly"
            )
        self.vectors = normalized_vectors(vectors)
        if len(self.ids) != len(self.vectors):
            raise ValueError("ID count differs from vector row count")
        digest = hashlib.sha256(
            json.dumps(self.ids, ensure_ascii=False, separators=(",", ":")).encode()
        )
        digest.update(str(self.vectors.shape).encode())
        digest.update(memoryview(self.vectors).cast("B"))
        self.fingerprint = digest.hexdigest()
        self.vectors.flags.writeable = False


def load_embeddings(path, *, limit=None):
    """Load NPZ ids/vectors without pickle; an explicit limit selects a prefix.

    The existing embedding worker's load_existing returns a per-row dictionary.
    This loader instead retains a dense matrix for FAISS and validates schemas,
    duplicate IDs and dimensions across chunks. Concatenation temporarily needs
    roughly twice the corpus-array memory; avoid loading multiple corpora at once.
    """
    path = Path(path)
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("limit must be a positive integer")
    files = [path] if path.is_file() else sorted(path.rglob("*.npz"))
    if not files:
        raise FileNotFoundError(f"no embedding NPZ files at {path}")
    ids, blocks, dimension = [], [], None
    for file in files:
        with np.load(file, allow_pickle=False) as data:
            if not {"ids", "vectors"}.issubset(data.files):
                raise ValueError(f"{file}: expected ids and vectors arrays")
            names, vectors = data["ids"], data["vectors"]
            if names.ndim != 1 or names.dtype.kind not in "SU":
                raise ValueError(f"{file}: ids must be a one-dimensional string array")
            if vectors.ndim != 2 or len(names) != len(vectors):
                raise ValueError(f"{file}: invalid vector shape or ID count")
            if dimension is not None and vectors.shape[1] != dimension:
                raise ValueError(f"{file}: inconsistent embedding dimension")
            dimension = vectors.shape[1]
            count = len(names) if limit is None else min(len(names), limit - len(ids))
            ids.extend(
                i.decode("utf-8") if isinstance(i, bytes) else str(i)
                for i in names[:count]
            )
            blocks.append(vectors[:count])
        if limit is not None and len(ids) == limit:
            break
    combined = blocks[0] if len(blocks) == 1 else np.concatenate(blocks, axis=0)
    blocks.clear()  # Release chunks before the catalog makes its private copy.
    return EmbeddingCatalog(ids, combined)
