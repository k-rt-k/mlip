"""Populate pre-review / post-rebuttal PDF pairs for a venue from OpenReview.

For each submission: pre = submission-time PDF, post = latest PDF between the
venue's reviews-released date and its decision date (peer/config/venue_dates.json,
built by peer/scripts/fetch_venue_dates.py; falls back to the paper's own first
review / decision timestamps if the venue is not in the config). Writes, per kept paper,
    <out>/<venue>/<number>/pre_review.pdf
    <out>/<venue>/<number>/post_rebuttal.pdf
    <out>/<venue>/<number>/meta.json     (title/abstract per stage, dates, decision, reviews + rating history)
and appends one line per paper (kept or skipped) to <out>/<venue>/manifest.jsonl.
Idempotent: papers already in the manifest are skipped.

    ~/mamba/envs/claude/bin/python peer/scripts/build_revision_dataset.py --n 5
    ~/mamba/envs/claude/bin/python peer/scripts/build_revision_dataset.py \
        --venue ICLR.cc/2024/Conference --api 2 --n 50
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openreview_auth import get_client  # noqa: E402
from reviews import classify_replies, rating_history, review_record, select_pre_post  # noqa: E402
from revisions import (  # noqa: E402
    RevisionFileUnavailable,
    download_revision_pdf,
    fetch_revisions,
    fetch_submissions,
    summarize_revisions,
    venue_slug,
)
from venue_dates import iso, load_thresholds  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "openreview"
REVIEW_FIELDS = ("rating", "confidence")


def _val(content, key):
    v = (content or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def review_revision_rows(client, review, api_version):
    """Revision rows for a review note, carrying rating/confidence instead of pdf."""
    rows = []
    for rev in fetch_revisions(client, review.id, api_version):
        content = getattr(getattr(rev, "note", None), "content", None) or getattr(rev, "content", None) or {}
        rows.append({"rev_id": rev.id, "tcdate": rev.tcdate,
                     "iso_date": summarize_revisions([rev])[0]["iso_date"] if content else None,
                     **{f: _val(content, f) for f in REVIEW_FIELDS}})
    return sorted(rows, key=lambda r: r["tcdate"])


def window_for(thresholds, first_review, decision_ts):
    """(window_start, decision, source): venue config first, else the paper's own timestamps."""
    if thresholds:
        return thresholds["window_start"], thresholds["decision"], "venue"
    return first_review, decision_ts, "paper"


def process_paper(client, note, api_version, paper_dir, thresholds):
    """Return the manifest record for one submission; downloads PDFs if kept."""
    rows = summarize_revisions(fetch_revisions(client, note.id, api_version))
    forum = classify_replies(client.get_all_notes(forum=note.id), submission_id=note.id)
    reviews, decision = forum["reviews"], forum["decision"]
    first_review = reviews[0].tcdate if reviews else None
    decision_ts = decision.tcdate if decision else None
    window_start, window_end, window_source = window_for(thresholds, first_review, decision_ts)
    sel = select_pre_post(rows, window_start, window_end)

    record = {
        "note_id": note.id, "number": getattr(note, "number", None), "title": _val(note.content, "title"),
        "decision": _val(decision.content, "decision") if decision else None,
        "decision_date": decision_ts, "first_review_date": first_review,
        "window_start": window_start, "window_end": window_end, "window_source": window_source,
        "n_reviews": len(reviews), "n_revisions": len(rows),
        "kept": sel is not None,
    }
    if sel is None:
        record["skip_reason"] = ("no thresholds" if window_start is None or window_end is None
                                 else "no PDF revision in rebuttal window")
        return record

    paper_dir.mkdir(parents=True, exist_ok=True)
    try:
        download_revision_pdf(client, sel["pre"], api_version, paper_dir / "pre_review.pdf")
        download_revision_pdf(client, sel["post"], api_version, paper_dir / "post_rebuttal.pdf")
    except RevisionFileUnavailable as exc:
        record.update(kept=False, skip_reason=f"revision file not served: {exc}")
        return record
    meta = {
        **record,
        "pre": sel["pre"], "post": sel["post"],
        "n_pdfs_before_decision": sel["n_pdfs_before_decision"],
        "n_in_window": sel["n_in_window"],
        "n_camera_ready": sel["n_camera_ready"],
        "reviews": [review_record(r, rating_history(review_revision_rows(client, r, api_version)))
                    for r in reviews],
        "all_revisions": rows,
    }
    (paper_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    record.update({k: meta[k] for k in ("n_in_window", "n_camera_ready")})
    record["ratings_changed"] = sum(r["rating_changed"] for r in meta["reviews"])
    return record


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--venue", default="ICLR.cc/2017/conference")
    p.add_argument("--api", type=int, choices=(1, 2), default=1)
    p.add_argument("--n", type=int, default=0, help="Max submissions to process (0 = all)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    client = get_client(args.api)
    venue_dir = args.out / venue_slug(args.venue)
    venue_dir.mkdir(parents=True, exist_ok=True)
    manifest = venue_dir / "manifest.jsonl"
    done = {json.loads(l)["note_id"] for l in manifest.read_text().splitlines()} if manifest.exists() else set()

    thresholds = load_thresholds(args.venue)
    if thresholds:
        print(f"Window: {iso(thresholds['window_start'])} ({thresholds['window_start_source']}) -> "
              f"{iso(thresholds['decision'])} ({thresholds['decision_source']})")
    else:
        print("No venue thresholds in config; using each paper's first review / decision timestamps.")

    notes = fetch_submissions(client, args.venue, args.api, limit=args.n or None)
    print(f"{args.venue}: {len(notes)} submissions, {len(done)} already in manifest")
    kept = skipped = 0
    with manifest.open("a") as fh:
        for note in notes:
            if note.id in done:
                continue
            rec = process_paper(client, note, args.api, venue_dir / str(getattr(note, "number", note.id)),
                                thresholds)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            kept += rec["kept"]
            skipped += not rec["kept"]
            status = "KEPT" if rec["kept"] else f"skip ({rec['skip_reason']})"
            print(f"  #{rec['number']:<5} {status:<40} {rec['decision'] or '-':<24} {(rec['title'] or '')[:45]}")
    print(f"\nkept {kept}, skipped {skipped}. Manifest: {manifest}")


if __name__ == "__main__":
    main()
