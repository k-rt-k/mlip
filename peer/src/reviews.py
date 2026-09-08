"""Reviews, decisions, and pre/post-rebuttal PDF selection for one submission.

Selection rule (project decision, 2026-09-08):
  pre  = the submission-time PDF (first revision carrying a PDF)
  post = the latest PDF in [window_start, decision), where window_start is
         the venue's reviews-released date (fallback: review deadline, then the
         paper's first review) and decision is the venue's notification date
         (fallback: the paper's decision note).
Papers with no PDF upload inside that window are dropped: revisions before
reviews are self-edits, revisions after the decision are camera-ready.
Official thresholds live in peer/config/venue_dates.json.
"""

import re

from revisions import FIELDS as _REV_FIELDS  # noqa: F401  (documented dependency)

REVIEW_KEYS = ("official_review", "review")
DECISION_KEYS = ("decision", "acceptance")
EXCLUDE_KEYS = ("meta_review", "metareview")


def _kind(invitation):
    return invitation.rsplit("/", 1)[-1].lower()


def classify_replies(replies, submission_id):
    """Split forum replies into official reviews and the decision note.

    ICLR 2019 posted decisions as Meta_Review notes (no separate Decision), so
    meta-reviews stand in for the decision when no decision note exists.
    """
    reviews, decisions, metas = [], [], []
    for n in replies:
        if n.id == submission_id:
            continue
        k = _kind(n.invitation)
        if any(x in k for x in EXCLUDE_KEYS):
            metas.append(n)
        elif any(x in k for x in DECISION_KEYS):
            decisions.append(n)
        elif any(k.endswith(x) for x in REVIEW_KEYS):
            reviews.append(n)
    reviews.sort(key=lambda n: n.tcdate)
    decisions = sorted(decisions or metas, key=lambda n: n.tcdate)
    return {"reviews": reviews, "decision": decisions[0] if decisions else None}


def select_pre_post(rows, window_start, decision):
    """Apply the selection rule to normalised revision rows (see revisions.summarize_revisions)."""
    if window_start is None or decision is None:
        return None
    with_pdf = [r for r in rows if r.get("pdf")]
    before = [r for r in with_pdf if r["tcdate"] < decision]
    in_window = [r for r in before if r["tcdate"] >= window_start]
    if not before or not in_window:
        return None
    pre, post = before[0], in_window[-1]
    if pre is post or pre["pdf"] == post["pdf"]:
        return None
    return {
        "pre": pre,
        "post": post,
        "n_pdfs_before_decision": len(before),
        "n_in_window": len(in_window),
        "n_camera_ready": len(with_pdf) - len(before),
    }


def parse_score(value):
    """'7: Good paper' -> 7; {'value': 8} -> 8; None/unparseable -> None."""
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def _content(note, key):
    return (note.content or {}).get(key)


def rating_history(rows):
    """Reduce a review note's revision rows to [{iso_date, rating, confidence}], oldest first."""
    return [{"rev_id": r["rev_id"], "iso_date": r["iso_date"],
             "rating": parse_score(r.get("rating")), "confidence": parse_score(r.get("confidence"))}
            for r in rows]


def review_record(review, history):
    """Flat record for one official review, with first/last rating from its history."""
    ratings = [h["rating"] for h in history if h.get("rating") is not None]
    first, last = (ratings[0], ratings[-1]) if ratings else (None, None)
    return {
        "review_id": review.id,
        "tcdate": review.tcdate,
        "signature": (review.signatures or [None])[0],
        "rating": parse_score(_content(review, "rating")),
        "confidence": parse_score(_content(review, "confidence")),
        "rating_first": first,
        "rating_last": last,
        "rating_changed": first is not None and first != last,
        "history": history,
    }
