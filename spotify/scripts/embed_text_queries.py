"""Freeze approved synthetic text queries for retrieval in a separate process.

From the repo root, using the encoder environment described in README.md:
  EMBED_DEVICE=cpu OMP_NUM_THREADS=4 data/retrieval/encoder-venv/bin/python spotify/scripts/embed_text_queries.py --output data/retrieval/text-queries.npz

Input is one synthetic prompt per line. Keep private/user prompts out of Git.
The adjacent JSON records texts, checkpoint revision, packages and checksums.
This script does not import FAISS or inspect hidden playlist answers.
"""

import argparse
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spotify.src.embeddings import get_embedder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, default=Path("prompts.txt"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--expected-revision", help="fail if the loaded CLAP checkpoint differs")
    args = parser.parse_args()
    manifest_path = args.output.with_suffix(".json")
    if args.output.suffix != ".npz":
        parser.error("output must end in .npz")
    if args.output.exists() or manifest_path.exists():
        parser.error("output or manifest already exists; use a new path")
    source = args.prompts.read_bytes()
    texts = [line.strip() for line in source.decode().splitlines() if line.strip()]
    if not texts:
        parser.error("no query texts found")
    encoder = get_embedder("clap", device=args.device)
    revision = encoder._model.config._commit_hash
    if not revision or (args.expected_revision and revision != args.expected_revision):
        parser.error(f"unexpected or unknown checkpoint revision: {revision}")
    vectors = encoder.embed_text(texts)
    ids = [f"prompt-{i+1}" for i in range(len(texts))]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.output, ids=ids, vectors=vectors)
    code = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        cwd=Path(__file__).resolve().parents[2],
    ).stdout.strip()
    manifest = dict(
        query_ids=ids, texts=texts, model=encoder.repo, revision=revision,
        device=args.device, python=platform.python_version(), code_revision=code,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        prompts_sha256=hashlib.sha256(source).hexdigest(),
        sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
        shape=list(vectors.shape),
        packages={d.metadata["Name"]: d.version for d in distributions()},
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Saved {len(ids)} queries to {args.output} and {manifest_path}")
