"""Spike: how many OpenReview submissions have >1 PDF revision, and what do they look like?

Samples submissions from a venue, pulls each one's revision history, prints a
per-paper table, and writes data/openreview/<venue>/revisions.json. With
--download-pdfs it also saves initial.pdf / final.pdf per paper that has two
distinct PDFs.

Requires peer/.env with OpenReview credentials (anonymous reads are blocked).

Examples:
    # ICLR 2017 lives on API v1 (the venue PeerRead overlaps with)
    ~/mamba/envs/claude/bin/python peer/scripts/explore_revisions.py --n 20
    # A recent venue on API v2
    ~/mamba/envs/claude/bin/python peer/scripts/explore_revisions.py \
        --venue ICLR.cc/2024/Conference --api 2 --n 20 --download-pdfs
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openreview_auth import get_client  # noqa: E402
from revisions import (  # noqa: E402
    download_revision_pdf,
    fetch_revisions,
    fetch_submissions,
    pick_initial_and_final,
    summarize_revisions,
    venue_slug,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "openreview"


def note_title(note):
    title = (note.content or {}).get("title")
    return title["value"] if isinstance(title, dict) else title


def describe(note, rows):
    """One record per submission: revision rows + what changed between first and last."""
    changed = {f: len({r[f] for r in rows if r[f] is not None}) > 1
               for f in ("title", "abstract", "pdf")}
    pair = pick_initial_and_final(rows)
    return {
        "note_id": note.id,
        "number": getattr(note, "number", None),
        "title": note_title(note),
        "n_revisions": len(rows),
        "changed": changed,
        "initial_pdf_rev": pair[0]["rev_id"] if pair else None,
        "final_pdf_rev": pair[1]["rev_id"] if pair else None,
        "revisions": rows,
    }


def print_table(records):
    print(f"{'#':>5}  {'revs':>4}  {'pdf':>3}  {'abs':>3}  {'title':>5}  first -> last            title")
    for rec in records:
        rows = rec["revisions"]
        span = f"{rows[0]['iso_date'][:10]} -> {rows[-1]['iso_date'][:10]}" if rows else "-"
        flags = ["Y" if rec["changed"][f] else "." for f in ("pdf", "abstract", "title")]
        print(f"{str(rec['number']):>5}  {rec['n_revisions']:>4}  {flags[0]:>3}  {flags[1]:>3}  "
              f"{flags[2]:>5}  {span}  {(rec['title'] or '')[:50]}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--venue", default="ICLR.cc/2017/conference",
                   help="Venue id, e.g. ICLR.cc/2017/conference (v1) or ICLR.cc/2024/Conference (v2)")
    p.add_argument("--api", type=int, choices=(1, 2), default=1, help="OpenReview API version")
    p.add_argument("--n", type=int, default=20, help="Number of submissions to sample (0 = all)")
    p.add_argument("--download-pdfs", action="store_true",
                   help="Save initial.pdf/final.pdf for papers with two distinct PDF revisions")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    client = get_client(args.api)
    out_dir = args.out / venue_slug(args.venue)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching submissions for {args.venue} via API v{args.api} ...")
    notes = fetch_submissions(client, args.venue, args.api, limit=args.n or None)
    print(f"Got {len(notes)} submissions. Fetching revision histories ...\n")

    records = []
    for note in notes:
        rows = summarize_revisions(fetch_revisions(client, note.id, args.api))
        rec = describe(note, rows)
        records.append(rec)
        if args.download_pdfs and rec["initial_pdf_rev"]:
            paper_dir = out_dir / str(rec["number"] or note.id)
            by_id = {r["rev_id"]: r for r in rows}
            download_revision_pdf(client, by_id[rec["initial_pdf_rev"]], args.api, paper_dir / "initial.pdf")
            download_revision_pdf(client, by_id[rec["final_pdf_rev"]], args.api, paper_dir / "final.pdf")

    print_table(records)
    n_multi = sum(1 for r in records if r["initial_pdf_rev"])
    print(f"\n{n_multi}/{len(records)} sampled papers have >=2 distinct PDF revisions.")

    path = out_dir / "revisions.json"
    path.write_text(json.dumps({"venue": args.venue, "api": args.api, "papers": records}, indent=2))
    print(f"Wrote {path}")
    return records


if __name__ == "__main__":
    main()
