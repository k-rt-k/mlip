"""Isolated-process CPU index comparison, separate from recommendation evaluation.

Each construction configuration gets a fresh spawned process and identical
corpus/queries/thread count. Query-only parameter sweeps reuse its built index.
RSS is the worker's lifetime high-water mark (loader, corpus, queries, index,
training and serialization included), not just the FAISS allocation. Serialized
index bytes are reported separately. Latencies are warm single-query calls to
search (normalization and ID mapping included), excluding encoding and IO.
ID-based ANN recall can understate agreement when exact boundary scores tie.
"""

from dataclasses import asdict
from pathlib import Path
import multiprocessing
import platform
import resource
import sys
import tempfile
import time
import traceback

import faiss
import numpy as np

from .catalog import load_embeddings
from .index import IndexConfig, RetrievalIndex


def ann_recall(approximate, exact):
    """Mean overlap of unique returned row IDs with exact top-k; -1 is a miss.

    Existing downstream recall divides by playlist ground-truth size. This
    metric instead measures recovery of the fixed exact nearest-neighbor set.
    """
    approximate, exact = np.asarray(approximate), np.asarray(exact)
    if approximate.shape != exact.shape or exact.ndim != 2 or not exact.size:
        raise ValueError(
            "ANN and exact rows must have equal nonempty (queries,k) shapes"
        )
    if (exact < 0).any():
        raise ValueError("exact reference must have k valid neighbors")
    return float(
        np.mean(
            [len((set(a) - {-1}) & set(e)) / len(e) for a, e in zip(approximate, exact)]
        )
    )


def _worker(
    connection,
    corpus_path,
    queries_path,
    configs,
    reference,
    k,
    repeats,
    warmups,
    threads,
):
    try:
        faiss.omp_set_num_threads(threads)
        start = time.perf_counter()
        corpus, queries = load_embeddings(corpus_path), load_embeddings(queries_path)
        load_seconds = time.perf_counter() - start
        index = RetrievalIndex.build(corpus, configs[0])
        reference = Path(reference)
        if configs[0].method == "exact":
            exact = index.search(queries.vectors, k)
            np.savez(
                reference,
                rows=exact.rows,
                corpus=corpus.fingerprint,
                queries=queries.fingerprint,
            )
            reference_rows = exact.rows
        else:
            with np.load(reference, allow_pickle=False) as saved:
                if (
                    str(saved["corpus"]) != corpus.fingerprint
                    or str(saved["queries"]) != queries.fingerprint
                ):
                    raise ValueError(
                        "corpus/query fingerprint differs from exact reference"
                    )
                reference_rows = saved["rows"]
        with tempfile.TemporaryDirectory(prefix="faiss-size-") as directory:
            path = Path(directory) / "index.faiss"
            faiss.write_index(index.index, str(path))
            index_bytes = path.stat().st_size
        records = []
        for config in configs:
            index.set_search_parameters(
                nprobe=config.nprobe, ef_search=config.ef_search
            )
            predictions = index.search(queries.vectors, k)
            for _ in range(warmups):
                for query in queries.vectors:
                    index.search(query[None, :], k)
            latencies = []
            order = np.random.default_rng(0).permutation(len(queries.ids))
            for _ in range(repeats):
                for i in order:
                    start = time.perf_counter()
                    index.search(queries.vectors[i : i + 1], k)
                    latencies.append((time.perf_counter() - start) * 1000)
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            records.append(
                {
                    "config": asdict(config),
                    "corpus_fingerprint": corpus.fingerprint,
                    "queries_fingerprint": queries.fingerprint,
                    "corpus_rows": len(corpus.ids),
                    "query_rows": len(queries.ids),
                    "dimension": corpus.vectors.shape[1],
                    "ann_recall_at_k": ann_recall(predictions.rows, reference_rows),
                    "missing_neighbor_fraction": float(np.mean(predictions.rows < 0)),
                    "latency_ms": {
                        "count": len(latencies),
                        "mean": float(np.mean(latencies)),
                        "p50": float(np.percentile(latencies, 50)),
                        "p95": float(np.percentile(latencies, 95)),
                    },
                    "construction_seconds": index.build_info["construction_seconds"],
                    "build_info": index.build_info,
                    "load_seconds": load_seconds,
                    "corpus_array_bytes": corpus.vectors.nbytes,
                    "index_file_bytes": index_bytes,
                    "process_peak_rss_bytes": int(
                        peak if sys.platform == "darwin" else peak * 1024
                    ),
                }
            )
        connection.send({"results": records})
    except BaseException:
        connection.send({"error": traceback.format_exc()})
    finally:
        connection.close()


def compare(
    corpus_path, queries_path, configs, *, k=5, repeats=3, warmups=1, threads=1
):
    """Return a JSON-serializable report; no real corpus or default tuning grid assumed."""
    if (
        any(type(v) is not int or v <= 0 for v in (k, repeats, threads))
        or type(warmups) is not int
        or warmups < 0
    ):
        raise ValueError(
            "k, repeats and threads must be positive; warmups must be nonnegative"
        )
    configs = list(configs)
    if not any(c.method == "exact" for c in configs):
        configs.insert(0, IndexConfig("exact"))
    groups = {}
    for config in sorted(configs, key=lambda c: c.method != "exact"):
        group = groups.setdefault(config.construction_key(), [])
        if config not in group:
            group.append(config)
    results = []
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="retrieval-benchmark-") as directory:
        reference = Path(directory) / "exact.npz"
        for number, group in enumerate(groups.values()):
            receiver, sender = ctx.Pipe(duplex=False)
            process = ctx.Process(
                target=_worker,
                args=(
                    sender,
                    str(Path(corpus_path).resolve()),
                    str(Path(queries_path).resolve()),
                    group,
                    str(reference),
                    k,
                    repeats,
                    warmups,
                    threads,
                ),
            )
            process.start()
            sender.close()
            try:
                message = receiver.recv()
            except EOFError as exc:
                process.join()
                raise RuntimeError(
                    f"benchmark worker exited with code {process.exitcode}"
                ) from exc
            except BaseException:
                process.terminate()
                process.join()
                raise
            finally:
                receiver.close()
            process.join()
            if "error" in message:
                raise RuntimeError(message["error"])
            if process.exitcode:
                raise RuntimeError(
                    f"benchmark worker exited with code {process.exitcode}"
                )
            for record in message["results"]:
                record["build_id"] = number
                results.append(record)
    return {
        "schema_version": 1,
        "faiss_version": faiss.__version__,
        "numpy_version": np.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "threads": threads,
        "k": k,
        "warmups": warmups,
        "repeats": repeats,
        "latency_scope": "warm single-query search; normalization/ID mapping included; encoding/IO excluded",
        "memory_scope": "worker lifetime peak RSS including data loading, training, vectors and index",
        "tie_policy": "strict row-ID recall; equally scoring boundary ties may reduce measured recall",
        "results": results,
    }
