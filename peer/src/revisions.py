"""OpenReview revision retrieval: initial submission vs later revisions.

Works against both OpenReview APIs, because the venue decides which one holds
its data (see docs/openreview_api.md):

* API v2 (api2.openreview.net, venues ~2023+): a Note is the head; every
  change is an Edit. `get_note_edits(note_id=...)` returns the history and each
  `edit.note.content[field]['value']` is the field at that point.
* API v1 (api.openreview.net, e.g. ICLR 2017): revisions are "references"
  (`get_references(referent=..., original=True)`), plain Notes with a flat
  `content` dict.

`summarize_revisions` normalises both into the same row shape so the rest of
the pipeline does not care which API produced them.
"""

from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("title", "abstract", "pdf")


def _content_of(obj):
    """Return the content dict of a v2 Edit (`.note.content`) or v1 Note (`.content`)."""
    note = getattr(obj, "note", None)
    if note is not None:
        return getattr(note, "content", None) or {}
    if hasattr(obj, "note"):  # v2 Edit with note=None (e.g. a delete/meta edit)
        return None
    return getattr(obj, "content", None) or {}


def _field(content, name):
    """Read a field from v2 (`{'value': x}`) or v1 (`x`) content."""
    value = content.get(name)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def summarize_revisions(revisions):
    """Normalise Edits/references to sorted rows: rev_id, tcdate, iso_date, invitation, fields."""
    rows = []
    for rev in revisions:
        content = _content_of(rev)
        if content is None:
            continue
        tcdate = rev.tcdate
        rows.append({
            "rev_id": rev.id,
            "tcdate": tcdate,
            "iso_date": datetime.fromtimestamp(tcdate / 1000, tz=timezone.utc).isoformat(),
            "invitation": rev.invitation,
            **{f: _field(content, f) for f in FIELDS},
        })
    rows.sort(key=lambda r: r["tcdate"])
    return rows


def pick_initial_and_final(rows):
    """Return (first, last) rows carrying distinct PDFs, or None if there is <2."""
    with_pdf = [r for r in rows if r.get("pdf")]
    if len(with_pdf) < 2 or with_pdf[0]["pdf"] == with_pdf[-1]["pdf"]:
        return None
    return with_pdf[0], with_pdf[-1]


def _check_version(api_version):
    if api_version not in (1, 2):
        raise ValueError(f"api_version must be 1 or 2, got {api_version!r}")


V1_SUBMISSION_NAMES = ("Blind_Submission", "submission")  # 2018-2023, then 2017


def fetch_submissions(client, venue_id, api_version, limit=None):
    """All submissions for a venue (accepted and rejected), ordered by paper number.

    v2: the Submission invitation. Do not filter by content.venueid, which
    only matches accepted papers (rejected ones get a different venueid).
    v1: Blind_Submission (ICLR 2018-2023) with a fallback to the 2017 name.
    """
    _check_version(api_version)
    if api_version == 2:
        notes = client.get_all_notes(invitation=f"{venue_id}/-/Submission", sort="number:asc")
    else:
        notes = []
        for name in V1_SUBMISSION_NAMES:
            notes = client.get_all_notes(invitation=f"{venue_id}/-/{name}", sort="number:asc")
            if notes:
                break
    return notes if limit is None else notes[:limit]


def fetch_revisions(client, note_id, api_version):
    """Full revision history of one submission (v2 Edits or v1 references)."""
    _check_version(api_version)
    if api_version == 2:
        return client.get_note_edits(note_id=note_id, sort="tcdate:asc")
    return client.get_references(referent=note_id, original=True)


class RevisionFileUnavailable(RuntimeError):
    """The API no longer serves this revision's file (v2 keeps only the current PDF)."""


def download_revision_pdf(client, row, api_version, dest):
    """Save the PDF of one revision row (from summarize_revisions) to `dest`.

    v1: `/references/pdf?id=<reference id>` via the client; historical files work.
    v2: GET `<baseurl>/pdf/<hash>.pdf` (the edit's `content.pdf.value`) through
    the client's own session (its User-Agent passes the WAF; plain requests get
    HTML 429s). Only the *current* file of a note is served: superseded revision
    files 404 ("Pdf file with hash name ... not found"), so v2 venues cannot
    supply pre-decision PDFs to outside accounts. `/attachment?id=<edit id>`
    and `/pdf?id=<edit id>` also 404 (note ids only).
    """
    _check_version(api_version)
    if api_version == 2:
        resp = client.session.get(client.baseurl + row["pdf"], headers=client.headers, timeout=120)
        if resp.status_code == 404:
            raise RevisionFileUnavailable(f"{row['rev_id']}: {row['pdf']} is no longer served (v2 keeps current file only)")
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF"):
            raise RuntimeError(f"{row['pdf']}: response is not a PDF ({resp.headers.get('content-type')})")
        data = resp.content
    else:
        data = client.get_pdf(row["rev_id"], is_reference=True)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def venue_slug(venue_id):
    """Filesystem-safe name for a venue id such as ICLR.cc/2017/conference."""
    return venue_id.replace("/", "_")
