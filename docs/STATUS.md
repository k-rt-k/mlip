# Project Status

Scope: [SCOPE.md](SCOPE.md). Deliverables: [baselines milestone](../milestones/baselines.md).

## 2026-10-05 — Datasets and collection pipelines ready (Harsh)

- **Prompt-only dataset:** 20 prompts, 60 reference playlists (three per prompt),
  4,603 playlist-track memberships, and 4,475 distinct video IDs. Tracks,
  provenance, selection caveats, and displayed views for 59 playlists are saved;
  aggregate likes/saves are unavailable.
- **Partial-playlist dataset:** twenty sources, each with 5-song and 20-song inputs
  (40 records/private copies). The 20-song input includes its original five seeds;
  all remaining eligible source songs are hidden for each size. Hidden counts vary:
  23–264 for five seeds (1,532 total), 8–249 for twenty seeds (1,232 total).
  Original five-song copies/splits are unchanged; twenty larger copies are added.
  All copies belong to `mlip.team0@gmail.com`, have neutral titles and empty
  descriptions, and contain exactly their seeds. Each record has a
  `created_playlist_id`; `source_example_id` pairs the two sizes and `seed_count`
  identifies the size. `example_id` 1–20 denotes five seeds, 21–40 twenty seeds.
  `model_inputs.json` excludes source metadata and hidden songs. Source playlist
  IDs are separate from prompt references; songs can overlap between datasets.
- **Pipelines:** public YouTube Music search/fetch, reproducible seed/hidden
  preparation, private-copy creation/verification, and suggestion fetching work.
  Reference reports rebuild offline from saved snapshots. Browser authentication
  is supported for account operations; public collection needs no login.
  Environment: `uv`, Python 3.12, pinned dependencies. Latest dataset checks:
  **21 YouTube Music tests passed**, all original five-song splits preserved, paired
  seed/hidden coverage and handoff ZIP integrity verified.
  [Browser-auth script](../youtube_music/scripts/setup_auth.py) parses pasted
  Copy as fetch (Node.js) input, tests authentication, and safely refreshes credentials.
  [Paired-copy generation script](../youtube_music/scripts/prepare_nested_partials.py)
  builds the 5/20-song setup, checks existing ownership, and checkpoints new copy IDs.
  Requests are paced; incomplete reads have bounded retries, rate-limit failures stop
  the run, and sanitized diagnostics are saved locally in `v3/errors.jsonl` when needed.
  Usage is in each script’s docstring.
- **Handoff:** [dataset ZIP](../datasets/baselines-v4.zip) and
  [SHA-256 manifest](../datasets/baselines-v4.manifest.json) are committed for
  teammates. Re-extract after pulling using the command in [README](../README.md)
  to replace stale local dataset IDs; extracted data stays gitignored. The ZIP contains
  no credentials.
  [Reference report](../data/youtube_music/references/v2/review.html) and
  [partial-playlist report](../data/youtube_music/partial_examples/v3/review.html)
  provide playlist links and contents/counts. Private copies require their
  owning account (`mlip.team0@gmail.com`); browser credentials must be shared separately,
  outside Git. The forty-input `dataset.json` and `model_inputs.json` are
  under `data/youtube_music/partial_examples/v3/`; original v2 files are retained. Script docstrings contain usage.
- **Limitations:** reference playlists are weak positives, not exhaustive gold
  songs. Curation uses metadata/track listings; individual audio suitability and
  release years are not verified. Matching currently uses exact video IDs,
  leaving alternate uploads, covers, and recording versions unresolved.
- **Baseline state:** five continuation suggestions per example are saved in
  `data/youtube_music/baseline_runs/continuation-v1/`, unscored. No LLM results or
  evaluation harness exist. Earlier Spotify API/metadata tooling remains in
  `spotify/`; no embedding pipeline or interactive prototype is implemented.

## Baselines milestone — current checklist

### 1. Dataset and shared evaluation setup

**Owner:** Harsh (datasets/pipelines complete); evaluation owner unassigned.

- [x] Collect prompt reference playlists and save reproducible snapshots.
- [x] Prepare partial examples, hidden answers, verified seed-only copies, and handoff.
- [x] Prepare plan for implementation and evaluation of baselines.

### 2. LLM baseline
**Owner:** unassigned. **State:** not started.

- [ ] Implement and run prompt-only and prompt + partial generation; record exact
  model/version, prompts, outputs, cost, and latency. Web search comparison is optional.
- [ ] Implement and report prompt-only proxy evaluation with validity/constraint checks.
- [ ] Resolve prompt + partial evaluation (**TBD**) or justify deferring performance claims.

### 3. Playlist-continuation baselines

**Owner:** unassigned. **State:** platform outputs collected; evaluation pending.

- [ ] Complete the YouTube Music continuation experiment on seed-only copies.
- [ ] Implement and run the required non-ML baseline; seed-song co-occurrence is
  a candidate. Prompt-based retrieval and LLM reranking are optional.
- [ ] Evaluate comparable methods on the same examples and fixed recommendation
  budget; report results, failures, and proxy limitations.

### 4. Writeup and submission

**Owner:** unassigned/shared. **State:** not started.

- [ ] Obtain grading feedback; revise answers scored 1 with original/revision/change notes,
  including any necessary corrections to platform-capability claims.
- [ ] Make slides for presentation
- [ ] Explain baselines, split, constrained metrics, results, limitations, and improvement needed to justify deployment. Participant satisfaction remains the eventual product eval.
- [ ] Produce the short PDF and GitHub code link; verify instructor/TA access and reproducibility.
