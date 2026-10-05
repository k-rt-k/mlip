# Project Status

Scope: [SCOPE.md](SCOPE.md). Deliverables: [baselines milestone](../milestones/baselines.md).

## 2026-10-05 — Datasets and collection pipelines ready (Harsh)

- **Prompt-only dataset:** 20 prompts, 60 reference playlists (three per prompt),
  4,603 playlist-track memberships, and 4,475 distinct video IDs. Tracks,
  provenance, selection caveats, and displayed views for 59 playlists are saved;
  aggregate likes/saves are unavailable.
- **Partial-playlist dataset:** twenty examples with five seeds each and 1,532 hidden
  song memberships; the original ten copy IDs and all seed/hidden splits are unchanged.
  All twenty private seed-only copies are verified, owned by `mlip.team0@gmail.com`,
  with neutral titles and empty descriptions. Every example has a
  `created_playlist_id`; `model_inputs.json` separates seeds from
  evaluator-only source metadata and hidden songs. Source playlist IDs are
  separate from prompt-only references; songs can overlap between datasets.
- **Pipelines:** public YouTube Music search/fetch, reproducible seed/hidden
  preparation, private-copy creation/verification, and suggestion fetching work.
  Reference reports rebuild offline from saved snapshots. Browser authentication
  is supported for account operations; public collection needs no login.
  Environment: `uv`, Python 3.12, pinned dependencies. Latest dataset checks:
  **20 YouTube Music tests passed**, original ten examples preserved, exact
  twenty-example handoff ZIP integrity verified.
  [Browser-auth script](../youtube_music/scripts/setup_auth.py) parses pasted
  Copy as fetch (Node.js) input, tests authentication, and safely refreshes credentials.
  [Copy-generation script](../youtube_music/scripts/prepare_partial_dataset.py)
  checks existing copy ownership before creating missing copies and checkpoints IDs;
  usage is in each script’s docstring.
- **Handoff:** [dataset ZIP](../datasets/baselines-v3.zip) and
  [SHA-256 manifest](../datasets/baselines-v3.manifest.json) are committed for
  teammates. Re-extract after pulling using the command in [README](../README.md)
  to replace stale local dataset IDs; extracted data stays gitignored. The ZIP contains
  no credentials.
  [Reference report](../data/youtube_music/references/v2/review.html) and
  [partial-playlist report](../data/youtube_music/partial_examples/v2/review.html)
  provide playlist links and contents/counts. Private copies require their
  owning account (`mlip.team0@gmail.com`); browser credentials must be shared separately,
  outside Git. The twenty-example `dataset.json` and `model_inputs.json` are
  under `data/youtube_music/partial_examples/v2/`. Script docstrings contain usage.
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
