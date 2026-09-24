"""Bookkeeping for sharded runs on the cluster.

Work is split by a stable hash of the track id, so a requeued job always gets
the same shard back. Each run logs which node it ran on, because previews are
cached on that node's local /scratch: /scratch is not shared between nodes,
and reusing a shard's audio means running on the node that holds it
(`sbatch --nodelist=<node>`), or holding a job there to ssh in.

The log is one JSON-lines file per shard rather than one shared file:
concurrent appends from several nodes to one NFS file can interleave.
"""

import hashlib
import json
import os
import socket
import time
from pathlib import Path


def shard_of(track_id, n_shards):
    """Stable shard index for a track id.

    Not Python's hash(): that is salted per process, so a requeued job would
    get a different slice.
    """
    digest = hashlib.sha1(track_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") % n_shards


def parse_shard(spec):
    """'2/8' -> (2, 8)."""
    index, total = (int(part) for part in spec.split("/"))
    if total < 1 or not 0 <= index < total:
        raise ValueError(f"shard must be i/N with 0 <= i < N, got {spec!r}")
    return index, total


def shard_tag(model, index, total):
    return f"{model}-shard-{index}-of-{total}"


def job_context():
    """Where and as what this process is running (SLURM fields when present)."""
    return {
        "node": socket.gethostname(),
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "restart": int(os.environ.get("SLURM_RESTART_COUNT", 0)),
    }


def record(log_path, **fields):
    """Append one timestamped entry, stamped with the job context."""
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **job_context(), **fields}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def shard_locations(log_dir):
    """{shard tag: latest entry} — the most recent node each shard ran on."""
    latest = {}
    for log in sorted(Path(log_dir).glob("*.jsonl")):
        lines = log.read_text().splitlines()
        if lines:
            latest[log.stem] = json.loads(lines[-1])
    return latest
