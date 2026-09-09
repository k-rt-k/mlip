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
2. `cp peer/.env.example peer/.env`, then mint a token:
   `~/mamba/envs/claude/bin/python peer/scripts/openreview_login.py --username you@cmu.edu`.
   It prompts for your password (hidden), logs in once, and writes a 7-day
   `OPENREVIEW_TOKEN` into `peer/.env` (mode 600). No password is stored.
   Re-run when the token expires. There is no web page for tokens; the
   `/login` API mints them (`expiresIn` max one week). Passkeys only work as
   a second factor on top of the password, not instead of it.
3. Fallback: set `OPENREVIEW_USERNAME` / `OPENREVIEW_PASSWORD` in `peer/.env`.
4. `openreview-py 2.6.0` is installed in `~/mamba/envs/claude`.

`peer/src/openreview_auth.py:get_client(api_version)` builds the logged-in
client, token first, then username/password.

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
| PDF of a specific revision | see "v2 revision PDFs" below; `/attachment?id=<edit id>` 404s (note ids only) | `client.get_pdf(<reference id>, is_reference=True)` |
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

## Results (2026-09-08, ICLR 2017 via API v1, first 5 submissions)

Token minted against `api2` works for `api.openreview.net` (v1) calls too.

| # | revisions | PDF revisions | first PDF | last PDF |
|---|-----------|---------------|-----------|----------|
| 1 | 53 | 9 | 2016-10-17 (arXiv v1 link) | 2017-03-14 |
| 2 | 3 | 2 | 2016-10-18 | 2016-10-18 |
| 3 | 3 | 2 | 2016-10-18 (arXiv link) | 2016-12-04 |
| 4 | 5 | 3 | 2016-10-18 (arXiv link) | 2016-12-14 |
| 5 | 3 | 2 | 2016-10-19 | 2017-01-10 |

- 5/5 papers have >=2 distinct PDFs; all 10 downloaded PDFs are valid and
  differ by md5. Output: `data/openreview/ICLR.cc_2017_conference/<n>/{initial,final}.pdf`.
- Early ICLR 2017 submissions often point `pdf` at an arXiv URL; OpenReview
  still serves a stored copy via `get_pdf(ref_id, is_reference=True)`.
- Every paper also carries `Venue_Revision` edits from 2022-07-21 (platform
  migration, `pdf=None`) and sometimes later metadata edits; these are ignored
  by `pick_initial_and_final` because they carry no PDF.
- Caveat for "pre-review": ICLR 2017 reviews landed ~2016-12-16, and authors
  revised both before and after that. The right pre-review snapshot is the
  last PDF *before the first review*, not necessarily the original
  submission. The dataset builder must fetch review dates to pick it.

## Official venue deadlines (`peer/config/venue_dates.json`)

Built by `peer/scripts/fetch_venue_dates.py --years 2017-2025`, which merges
three sources per venue (priority order) and records the source per milestone:

| Source | Coverage | What it gives |
|--------|----------|---------------|
| `website` | iclr.cc/Conferences/YEAR/Dates + /CallForPapers (2018+), archive prose for 2017 | Dates page: labels drift per year ("Paper Reviews Released", "Rebuttal/discussion begins", "Discussion Period Starts", ...), mapped by `venue_dates.label_rank`; "Paper ..." labels outrank bare ones so Tiny-Papers / blog dates lose. CFP page: "Reviews released: Nov 4", "Author discussion period ends: ...", "Final decisions: ..." (year inferred from the cycle when omitted; ranges take the end) fills what the Dates page omits (2019, 2020, 2023, 2024). Dates-page values win when both exist. |
| `invitations` | OpenReview v2 (2023+) | `Official_Review.duedate` -> review_due, `Meta_Review.cdate` -> rebuttal_end, `Decision.duedate` -> decision. v1 invitations carry no dates. |
| `empirical` | any | Busiest day of submissions / reviews / decisions (AoE end of day). Fallback only. |

Milestones: `submission, review_due, reviews_released, rebuttal_end, decision`,
stored as UTC epoch ms. "Anywhere on Earth" resolves to 23:59:59 at UTC-12
(so the UTC instant is 11:59:59 the next morning). Entries with
`"source": "manual"` survive re-runs; use them to fix a milestone by hand.

## Building the pre/post dataset

Selection rule (decided 2026-09-08): **pre = submission-time PDF; post =
latest PDF uploaded between the venue's reviews-released date and its
decision date** (`venue_dates.load_thresholds`; window start falls back to
review_due, and if the venue is absent from the config, to the paper's own
first-review / decision timestamps). Uploads before the window are
self-revisions, uploads after it are camera-ready (ICLR 2017 uses one
`Revision` invitation for everything, so names can't separate them; v2 venues
also have a distinct `Camera_Ready_Revision`). Papers with no PDF inside the
window are skipped.

```bash
~/mamba/envs/claude/bin/python peer/scripts/build_revision_dataset.py --n 5   # ICLR 2017, v1
```

Writes `data/openreview/<venue>/<number>/{pre_review.pdf,post_rebuttal.pdf,meta.json}`
and `manifest.jsonl` (one line per paper, idempotent re-runs). `meta.json`
carries the window used (`window_start`, `window_end`, `window_source` =
`venue` or `paper`), counts of PDFs in/before/after the window, and per-review
`rating`, `confidence`, and the review note's own revision history
(`rating_first`/`rating_last`).

First 5 ICLR 2017 papers with the official window: #1 and #5 kept (they
uploaded a PDF during the rebuttal window); #2-#4 skipped because their only
revisions predate the reviews. Review notes have a single revision each, so
ICLR 2017 has **no pre/post-rebuttal score history** on OpenReview; PeerRead
likewise stores one `RECOMMENDATION` per reviewer. Rating edits are expected
on v2 venues (2024+), to be checked.

## Venue layouts and other sources (probed 2026-09-08)

| Venue | API | Submissions | Per-paper replies | Reviews public? | PDF revisions in rebuttal? |
|-------|-----|-------------|-------------------|-----------------|-----------------------------|
| ICLR 2017 | v1 | `<v>/-/submission` | `<v>/-/paper<N>/official/review`, `.../acceptance` | yes | yes |
| ICLR 2018-2019 | v1 | `<v>/-/Blind_Submission` | `<v>/-/Paper<N>/Official_Review`, `Meta_Review` (2019: this *is* the decision) | yes | yes |
| ICLR 2020-2023 | v1 | `<v>/-/Blind_Submission` | `<v>/Paper<N>/-/Official_Review`, `Meta_Review`, `Decision` | yes | yes |
| ICLR 2024+ | v2 | `<v>/-/Submission` (7404 for 2024; `content.venueid` gives only the 2260 accepted) | `<v>/Submission<N>/-/Official_Review`, `Meta_Review`, `Decision` | yes | yes, **but not readable**: `Submission`/`Revision`/`Rebuttal_Revision` edits have restricted readers, so `get_note_edits` returns only post-decision `Camera_Ready_Revision` edits (accepted) or nothing (rejected). No pre/post pairs for outsiders. |
| NeurIPS 2023+ | v2 | accepted only readable (3218 / 4035) | `Official_Review`, `Rebuttal`, `Decision` | accepted only | no (text rebuttal) |
| ICML 2024 | v2 | 2610 readable | none | no | no |
| TMLR | v2 | 4661 readable | `TMLR/Paper<N>/-/Review`, `Decision` | yes | edits visible (title/abstract/pdf path history), **but superseded PDF files are not served** (404 "Pdf file with hash name ... not found", even for a paper revised two weeks earlier). No pre/post PDF pairs. |

**Bottom line (2026-09-09):** pre-review / post-rebuttal PDF pairs are only
obtainable from **ICLR 2017-2023 (API v1)**, where `get_references` +
`/references/pdf` serve every historical file. On API v2 (ICLR 2024+, TMLR,
NeurIPS) either the pre-decision edits are unreadable or their files are gone.

**v2 revision PDFs:** `client.session.get(client.baseurl + edit.content.pdf.value,
headers=client.headers)` serves the *current* file only. Plain `requests`
without the client's User-Agent gets an HTML 429 from the WAF regardless of
quota. `/notes/edits` also has a tighter secondary limit (~18 requests/minute).

Within PeerRead only `iclr_2017` overlaps OpenReview (ACL/CoNLL used START,
NIPS used CMT, arXiv sections have no reviews).

**Rate limit:** ~500 requests per account per window (429 with a reset time;
openreview-py retries automatically). The builder spends ~4 requests per
paper, so pace full-venue runs or rely on the manifest to resume.

## Gotchas

- Rate limits are undocumented; `get_all_notes` pages at 1000 per request.
  Sample with `--n` before pulling a whole venue.
- v1 `get_references(original=True)` is needed for double-blind venues; without
  it you get the anonymised copy's history.
- PeerRead's `histories` field is empty for ICLR 2017, so revision data must
  come from OpenReview and be joined on title / paper number.
