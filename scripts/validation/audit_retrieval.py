"""Audit an immutable embedding snapshot before a real-data retrieval run.

Run with the retrieval environment from the repo root:
  uv run python scripts/validation/audit_retrieval.py --corpus /path/to/clap --output data/retrieval/audit.json

Reads source files only; writes a checksum manifest locally. Counts reflect
available vectors, not completeness of the upstream matching pipeline.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from retrieval import load_embeddings


def audit_file(path):
    """Validate one chunk and checksum it, without writing to shared storage."""
    before = path.stat()
    blob = path.read_bytes()
    catalog = load_embeddings(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"source changed during audit: {path}")
    with np.load(io.BytesIO(blob), allow_pickle=False) as data:
        norms = np.linalg.norm(data["vectors"], axis=1)
    return catalog.ids, dict(
        file=str(path), rows=len(catalog.ids), dimension=catalog.vectors.shape[1],
        bytes=len(blob), mtime_ns=after.st_mtime_ns,
        sha256=hashlib.sha256(blob).hexdigest(),
        norm_min=float(norms.min()) if len(norms) else None,
        norm_max=float(norms.max()) if len(norms) else None,
        non_unit_rows=int(np.count_nonzero(np.abs(norms - 1) > 1e-6)),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error("workers must be positive")
    root = args.corpus.resolve()
    files = [root] if root.is_file() else sorted(root.rglob("*.npz"))
    if not files:
        parser.error(f"no NPZ files found at {root}")
    seen, records, dimension = set(), [], None
    print(f"Auditing {len(files)} NPZ files", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for ids, record in pool.map(audit_file, files):
            overlap = seen.intersection(ids)
            if overlap:
                raise ValueError(f"duplicate IDs across files: {record['file']}: {sorted(overlap)[:5]}")
            seen.update(ids)
            if dimension is not None and record['dimension'] != dimension:
                raise ValueError(f"inconsistent dimension: {record['file']}")
            dimension = record['dimension']
            records.append(record)
            if len(records) % 1000 == 0:
                print(f"Audited {len(records)}/{len(files)} files, {len(seen)} rows", flush=True)
    report = dict(
        corpus=str(root), rows=len(seen), dimension=dimension,
        files=records, hostname=platform.node(),
        cpu_affinity=sorted(os.sched_getaffinity(0)),
        slurm_job_id=os.environ.get("SLURM_JOB_ID"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"rows": len(seen), "dimension": dimension,
                      "files": len(files), "output": str(args.output)}))
