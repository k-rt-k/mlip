"""Helpers for fetching the PeerRead dataset (github.com/allenai/PeerRead).

PeerRead ships its data committed in the git repo under
data/<section>/<split>/{reviews,parsed_pdfs,reviews_raw,pdfs}. The repo pack is
~1.2 GB, so we use a blobless partial clone plus a non-cone sparse checkout to
pull only the sections/splits requested. Raw pdfs/ are excluded by default.
"""

from pathlib import Path

REPO_URL = "https://github.com/allenai/PeerRead.git"
BRANCH = "master"

# Sections committed in the repo. nips_2013-2017 needs its own crawler and is
# not in git, so it is deliberately absent here.
SECTIONS = (
    "acl_2017",
    "conll_2016",
    "iclr_2017",
    "arxiv.cs.ai_2007-2017",
    "arxiv.cs.cl_2007-2017",
    "arxiv.cs.lg_2007-2017",
)
SPLITS = ("train", "dev", "test")

# Per-split subdirectories. JSON kinds are always fetched; pdfs/ is opt-in.
JSON_KINDS = ("reviews", "parsed_pdfs", "reviews_raw")
PDF_KIND = "pdfs"


class UnknownSectionError(ValueError):
    """Raised when a requested section is not one PeerRead ships in git."""


def validate_sections(sections):
    """Return `sections` unchanged if every entry is a known section."""
    unknown = [s for s in sections if s not in SECTIONS]
    if unknown:
        raise UnknownSectionError(
            f"Unknown PeerRead section(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(SECTIONS)}"
        )
    return list(sections)


def sparse_patterns(sections, splits, include_pdfs):
    """Build non-cone `git sparse-checkout` patterns for the requested subset.

    Section-level files (LICENSE.txt, README.md) are included by extension.
    Never use `/data/<section>/*`: in non-cone (gitignore-style) mode a pattern
    that matches a directory includes its entire subtree, i.e. the raw pdfs/.
    """
    kinds = JSON_KINDS + ((PDF_KIND,) if include_pdfs else ())
    patterns = []
    for section in dict.fromkeys(sections):
        patterns.append(f"/data/{section}/*.txt")
        patterns.append(f"/data/{section}/*.md")
        for split in dict.fromkeys(splits):
            for kind in kinds:
                patterns.append(f"/data/{section}/{split}/{kind}/")
    return patterns


def summarize(out_dir, sections):
    """Count .json files per section/split/kind under `out_dir`."""
    out_dir = Path(out_dir)
    summary = {}
    for section in sections:
        per_split = {}
        section_dir = out_dir / "data" / section
        for split in SPLITS:
            split_dir = section_dir / split
            if not split_dir.is_dir():
                continue
            per_split[split] = {
                kind_dir.name: sum(1 for p in kind_dir.iterdir() if p.suffix == ".json")
                for kind_dir in sorted(split_dir.iterdir())
                if kind_dir.is_dir()
            }
        summary[section] = per_split
    return summary
