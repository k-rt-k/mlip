# OpenReview API: getting paper revisions (as of Sept 2026)

Reference for `peer/src/`. Goal: for a submission, obtain the *initial* PDF
(what reviewers saw) and the *post-review* PDF (rebuttal / camera-ready
revision), so we can train on (draft, reviews, revised draft).

## Setup (user)

Anonymous API access is gone. Every `/notes` and `/notes/edits` request on
**both** `api.openreview.net` (v1) and `api2.openreview.net` (v2) returns

```
403 ChallengeRequiredError: Challenge verification required
```

(only `/groups` still answers without login). So:

1. Have an OpenReview profile (https://openreview.net/signup).
2. `cp peer/.env.example peer/.env` and fill `OPENREVIEW_USERNAME` /
   `OPENREVIEW_PASSWORD`. `.env` is gitignored.
3. `openreview-py 2.6.0` is installed in `~/mamba/envs/claude`.

`peer/src/openreview_auth.py:get_client(api_version)` builds the logged-in client.

## Two APIs, decided by the venue

| API | Base URL | Client | Venues |
|-----|----------|--------|--------|
| v1 | `https://api.openreview.net` | `openreview.Client` | Older venues, e.g. `ICLR.cc/2017/conference` (the only one overlapping PeerRead) |
| v2 | `https://api2.openreview.net` | `openreview.api.OpenReviewClient` | Roughly 2023+ venues, e.g. `ICLR.cc/2024/Conference` |

Passing a v1 URL to the v2 client raises immediately, so pick per venue.
`peer/src/revisions.py` takes `api_version` on every call and normalises both.

## Data model

**Note** = a submission / review / comment. `note.id`, `note.forum` (the
submission it belongs to), `note.number` (paper number), `note.content`.
In v2 every content field is wrapped: `content['title']['value']`.

**Revisions:**

- **v2 — Edits.** A Note is the head; each change is an `Edit` posted under an
  invitation. The first edit is the original submission; later ones come from
  invitations like `<venue>/Submission<N>/-/Revision`,
  `.../Camera_Ready_Revision`, or `<venue>/-/PC_Revision`. Each
  `edit.note.content` holds the field values *at that point*, so diffing
  consecutive edits gives what changed. The venue group's `content` lists the
  invitation names (`submission_id`, `pc_submission_revision_id`, ...).
- **v1 — References.** Each revision is a "reference" Note with its own `id`,
  `tcdate` and flat `content`; `original=True` returns the author-visible
  history for a (possibly blind) submission.

## Calls we use (`peer/src/revisions.py`)

| Task | v2 | v1 |
|------|----|----|
| Submissions of a venue | `client.get_all_notes(content={'venueid': venue}, sort='number:asc')` | `client.get_all_notes(invitation=f'{venue}/-/submission', ...)` |
| Revision history of one paper | `client.get_note_edits(note_id=id, sort='tcdate:asc')` | `client.get_references(referent=id, original=True)` |
| PDF of a specific revision | `client.get_attachment(field_name='pdf', id=<edit id>)` | `client.get_pdf(<reference id>, is_reference=True)` |
| Latest PDF | `client.get_pdf(<note id>)` | same |
| Reviews in the same call | add `details='replies'` to `get_all_notes`, then filter replies whose invitation ends with `Official_Review` | `details='directReplies'` |

Wrappers: `fetch_submissions`, `fetch_revisions`, `download_revision_pdf`,
`summarize_revisions` (rows of `rev_id, tcdate, iso_date, invitation, title,
abstract, pdf`), `pick_initial_and_final` (first and last rows with distinct PDFs).

## Running the spike

```bash
# ICLR 2017 (v1) — overlaps PeerRead's iclr_2017 section
~/mamba/envs/claude/bin/python peer/scripts/explore_revisions.py --n 20
# A recent v2 venue, also saving initial.pdf / final.pdf per paper
~/mamba/envs/claude/bin/python peer/scripts/explore_revisions.py \
    --venue ICLR.cc/2024/Conference --api 2 --n 20 --download-pdfs
```

Prints a per-paper table (revision count, whether pdf/abstract/title changed,
date span) and the headline number: how many sampled papers have >=2 distinct
PDFs. Output goes to `data/openreview/<venue>/revisions.json` (gitignored).

## Results

_Pending: run once `peer/.env` is filled in._

## Gotchas

- Rate limits are undocumented; `get_all_notes` pages at 1000 per request.
  Sample with `--n` before pulling a whole venue.
- v1 `get_references(original=True)` is needed for double-blind venues; without
  it you get the anonymised copy's history.
- PeerRead's `histories` field is empty for ICLR 2017, so revision data must
  come from OpenReview and be joined on title / paper number.
