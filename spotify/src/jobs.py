"""Bookkeeping for sharded runs on the cluster.

Work is split by a stable hash of the track id, so a requeued job always gets
the same shard back. Each run logs which node it ran on, because previews are
cached on that node's local /scratch: /scratch is not shared between nodes,
and reusing a shard's audio means running on the node that holds it
(`sbatch --nodelist=<node>`), or holding a job there to ssh in.

The log is one JSON-lines file per shard rather than one shared file:
concurrent appends from several nodes to one NFS file can interleave.
"""

import getpass
import hashlib
import json
import os
import socket
import time
from pathlib import Path

USER_DATA_ROOT = Path("/data/user_data")
DEFAULT_OUT_DIR = USER_DATA_ROOT / getpass.getuser() / "mlip" / "embeddings"


def require_persistent_out(path, repo_root):
    """Refuse any embeddings location except /data/user_data, outside the repo.

    Resolves symlinks first, so a link cannot smuggle output elsewhere. Also
    rejects paths inside the git repo: on Babel the clone itself may live
    under /data/user_data, and output inside it could end up tracked.
    Raises rather than asserts - `python -O` strips assert statements.
    """
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(USER_DATA_ROOT):
        raise RuntimeError(f"embeddings must live under {USER_DATA_ROOT}, "
                           f"but {path} resolves to {resolved}")
    if resolved.is_relative_to(Path(repo_root).resolve()):
        raise RuntimeError(f"{resolved} is inside the git repo {repo_root}; "
                           "embeddings must stay out of version control")
    user_dir = USER_DATA_ROOT / resolved.relative_to(USER_DATA_ROOT).parts[0]
    if not user_dir.is_dir():  # also triggers the automount
        raise RuntimeError(f"{user_dir} is not available here - it is only "
                           "mounted on compute nodes with an active job")
    return resolved


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
