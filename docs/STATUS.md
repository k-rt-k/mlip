# Project Status

Scope: [SCOPE.md](SCOPE.md). Deliverables: [baselines milestone](../milestones/baselines.md).

## 2026-10-04 — Zero-shot LLM baseline generated, unscored (Ayush)

- **Ready:** ranked, YouTube Music–resolved recommendations from
  `qwen/qwen3.8-27b:free` (OpenRouter, ModelRun host, fp4; temperature 0, seed 0,
  one run, prompt `v1`) for all 20 prompt-only requests (20 requested, top 10
  kept) and all 20 seeds-only partial examples (`partial_examples/v2`; 10
  requested, top 5 kept, matching the platform continuation budget). Outputs and raw responses are committed in
  [`data/llm/runs/qwen3.8-27b-v1/`](../data/llm/runs/qwen3.8-27b-v1/) on branch
  `LLM_baseline`; each mode file records model, provider, prompts, tokens, and latency.
  Cost $0; ~30 s per call.
- **Code:** `llm/` (OpenRouter client, prompts, parsing, title + artist resolution
  to video IDs with alternate uploads); usage in `llm/scripts/run_llm_baseline.py`.
  Needs `OPENROUTER_API_KEY` in gitignored `llm/.env`.
- **First observations:** 68% (prompt-only) and 51% (seeds-only) of suggestions
  resolve to catalog tracks; 13/20 prompts and 9/20 examples fill top-K.
  Unresolved items are mostly invented or misattributed songs (e.g. repeated
  invented gospel titles, wrong artists for real songs); some outputs repeat
  seeds or duplicates (Hindi indie, punk); classical/performer credits rarely resolve. Temperature 0 is not reproducible on the free endpoint;
  saved raw responses are the record.
- **Remaining:** scoring against references/hidden songs (evaluation owner),
  validity/constraint checks, and prompt + seeds mode (deferred until the
  partial-example request source is agreed; a discovery prompt is recoverable
  for 9/10 examples from `source_snapshot`).

## 2026-10-04 — Datasets and collection pipelines ready (Harsh)

- **Prompt-only dataset:** 20 prompts, 60 reference playlists (three per prompt),
  4,603 playlist-track memberships, and 4,475 distinct video IDs. Tracks,
  provenance, selection caveats, and displayed views for 59 playlists are saved;
  aggregate likes/saves are unavailable.
- **Partial-playlist dataset:** twenty examples with five seeds each and 1,532 hidden
  song memberships; the original ten examples are unchanged. Ten private seed-only
  copies have verified contents, neutral titles, and empty descriptions; ten
  additional copies await browser-auth refresh. All twenty local examples are
  ready. `model_inputs.json` separates seeds from
  evaluator-only source metadata and hidden songs. Source playlist IDs are
  separate from prompt-only references; songs can overlap between datasets.
- **Pipelines:** public YouTube Music search/fetch, reproducible seed/hidden
  preparation, private-copy creation/verification, and suggestion fetching work.
  Reference reports rebuild offline from saved snapshots. Browser authentication
  is supported for account operations; public collection needs no login.
  Environment: `uv`, Python 3.12, pinned dependencies. Latest dataset checks:
  **20 YouTube Music tests passed**, original ten examples preserved, exact
  twenty-example offline rebuild and handoff ZIP integrity verified.
- **Handoff:** [dataset ZIP](../datasets/baselines-v3.zip) and
  [SHA-256 manifest](../datasets/baselines-v3.manifest.json) are committed for
  teammates. `unzip -n datasets/baselines-v3.zip -d .` from the repository root
  restores the expected paths; extracted data stays gitignored. The ZIP contains
  no credentials.
  [Reference report](../data/youtube_music/references/v2/review.html) and
  [partial-playlist report](../data/youtube_music/partial_examples/v2/review.html)
  provide playlist links and contents/counts. Private copies require their
  owning account. The twenty-example `dataset.json` and `model_inputs.json` are
  under `data/youtube_music/partial_examples/v2/`. Script docstrings contain usage.
- **Limitations:** reference playlists are weak positives, not exhaustive gold
  songs. Curation uses metadata/track listings; individual audio suitability and
  release years are not verified. Matching currently uses exact video IDs,
  leaving alternate uploads, covers, and recording versions unresolved.
- **Baseline state:** five continuation suggestions per example are saved in
  `data/youtube_music/baseline_runs/continuation-v1/`, unscored. No evaluation
  harness exists. Earlier Spotify API/metadata tooling remains in
  `spotify/`; no embedding pipeline or interactive prototype is implemented.

## Baselines milestone — current checklist

### 1. Dataset and shared evaluation setup

**Owner:** Harsh (datasets/pipelines complete); evaluation owner unassigned.

- [x] Collect prompt reference playlists and save reproducible snapshots.
- [x] Prepare partial examples, hidden answers, verified seed-only copies, and handoff.
- [x] Prepare plan for implementation and evaluation of baselines.

### 2. LLM baseline
**Owner:** Ayush. **State:** prompt-only (20) and seeds-only (20) outputs generated; scoring pending.

- [x] Implement and run prompt-only and seeds-only generation; record exact
  model/version, prompts, outputs, cost, and latency.
- [ ] Prompt + partial generation (deferred; request source TBD). Web search comparison is optional.
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
