"""Download a configurable subset of the PeerRead dataset into data/PeerRead.

Uses a blobless partial clone + sparse checkout so only the requested
sections/splits are fetched. Re-running with more sections extends the
checkout in place (idempotent).

Examples:
    ~/mamba/envs/claude/bin/python peer/scripts/download_peerread.py
    ~/mamba/envs/claude/bin/python peer/scripts/download_peerread.py \
        --sections iclr_2017 acl_2017 --splits train --include-pdfs
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from peerread import (  # noqa: E402
    BRANCH,
    REPO_URL,
    SECTIONS,
    SPLITS,
    sparse_patterns,
    summarize,
    validate_sections,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "PeerRead"


def git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def ensure_clone(out_dir):
    """Create a blobless, checkout-less clone if `out_dir` is not one already."""
    if (out_dir / ".git").is_dir():
        print(f"Reusing existing clone at {out_dir}")
        return
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Cloning {REPO_URL} (blobless, no checkout) -> {out_dir}")
    git(
        ["clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
         "--branch", BRANCH, REPO_URL, str(out_dir)],
        cwd=out_dir.parent,
    )


def checkout_subset(out_dir, patterns):
    """Set the sparse-checkout patterns and materialise matching files."""
    git(["sparse-checkout", "set", "--no-cone", *patterns], cwd=out_dir)
    git(["checkout", BRANCH], cwd=out_dir)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sections", nargs="+", default=["iclr_2017"],
                   help=f"PeerRead sections to fetch. Choices: {', '.join(SECTIONS)}")
    p.add_argument("--splits", nargs="+", default=list(SPLITS), choices=SPLITS)
    p.add_argument("--include-pdfs", action="store_true",
                   help="Also fetch raw pdfs/ (large). Default: reviews + parsed_pdfs only.")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    sections = validate_sections(args.sections)
    patterns = sparse_patterns(sections, args.splits, args.include_pdfs)

    ensure_clone(args.out)
    checkout_subset(args.out, patterns)

    summary = summarize(args.out, sections)
    print("\nJSON files per section/split:")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
