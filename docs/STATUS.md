# Project Status

Scope: [SCOPE.md](SCOPE.md). Deliverables: [baselines milestone](../milestones/baselines.md).

## 2026-10-05 — Evaluation pipeline and continuation baselines scored (Spandan)

- **Ready:** `evaluation/evaluate.py` + `evaluation/metrics.py` score predictions
  (`{example_id: [video_ids]}`) against hidden songs in
  `partial_examples/v3/dataset.json` by exact video ID: precision, recall, hit
  rate, MAP, NDCG at K = 1 and 5, plus R-precision, reported per seed count.
- **Baselines:** non-ML seed co-occurrence over the reference-pool playlists
  (`baselines/`) and native YouTube Music suggestions
  (`youtube_music/scripts/run_ytm_baseline.py`), both on all 40 inputs.
- **Results (@5, five seeds / twenty seeds):** YouTube Music precision 0.13 / 0.08,
  hit rate 0.40 / 0.30, NDCG 0.15 / 0.08; co-occurrence precision 0.06 / 0.08,
  hit rate 0.15 / 0.20, NDCG 0.07 / 0.08. Full tables:
  `ytm_baseline_result2.txt`, `cooccurrence_baseline_result2.txt`.
  `cooccurence_baseline_result.txt` is an earlier twenty-input result, retained
  for reference rather than the current comparison.
- **Limitations:** recall is near zero because hidden sets are large (8–264
  songs); exact-ID matching misses alternate uploads; co-occurrence only knows
  songs in the 60 reference playlists.
  Before LLM scoring, handle short/empty outputs: the current evaluator rejects
  lists shorter than five and skips empty ones. Co-occurrence still needs a final
  deterministic tie-breaker; saved predictions preserve the reported run.

## 2026-10-04 — Zero-shot LLM baseline generated, unscored (Ayush)

- **Ready:** ranked, YouTube Music–resolved recommendations from
  `qwen/qwen3.8-27b:free` (OpenRouter, ModelRun host, fp4; temperature 0, seed 0,
  one run, prompt `v1`) for all 20 prompt-only requests (20 requested, top 10
  kept) and all 20 five-seed partial examples (`partial_examples/v2`, ids 1–20; 10
  requested, top 5 kept, matching the platform continuation budget). Outputs and
  raw responses are committed in
  [`data/llm/runs/qwen3.8-27b-v1/`](../data/llm/runs/qwen3.8-27b-v1/); each mode
  file records model, provider, prompts, tokens, and latency.
  Cost $0; ~30 s per call.
- **Code:** `llm/` (OpenRouter client, prompts, parsing, title + artist resolution
  to video IDs with alternate uploads); usage in `llm/scripts/run_llm_baseline.py`.
  Needs `OPENROUTER_API_KEY` in gitignored `llm/.env`.
- **First observations:** 68% (prompt-only) and 49% (seeds-only) of suggestions
  resolve to catalog tracks; 13/20 prompts and 10/20 examples fill top-K.
  Unresolved items are mostly invented or misattributed songs (e.g. repeated
  invented gospel titles, wrong artists for real songs); some outputs repeat
  seeds or duplicates (Hindi indie, punk); classical/performer credits rarely
  resolve. Temperature 0 is not reproducible on the free endpoint: a repeat of
  examples 11–20 shared only 0–4 of 10 songs per example and reasoning length
  varied ~10x, so single-run numbers are noisy; saved raw responses are the record.
- **Remaining:** convert saved seeds-only outputs to the evaluator's prediction
  format and score the five-seed half after handling incomplete outputs; evaluate
  prompt-only against reference playlists with validity/constraint checks; run the
  twenty-seed inputs (`partial_examples/v3`, ids 21–40). Prompt + seeds generation
  remains deferred until the request source is agreed.

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
- **Other tooling:** earlier Spotify API/metadata tooling remains in
  `spotify/`; no embedding pipeline or interactive prototype is implemented.

## Baselines milestone — current checklist

### 1. Dataset and shared evaluation setup

**Owner:** Harsh (datasets/pipelines); Spandan (evaluation pipeline).

- [x] Collect prompt reference playlists and save reproducible snapshots.
- [x] Prepare partial examples, hidden answers, verified seed-only copies, and handoff.
- [x] Prepare plan for implementation and evaluation of baselines.
- [x] Shared evaluation pipeline for partial-playlist continuation (`evaluation/`).
- [ ] Agree the reported split and constrained metric (e.g. hit rate/precision@5).

### 2. LLM baseline
**Owner:** Ayush. **State:** prompt-only (20) and seeds-only (20) outputs generated; scoring pending.

- [x] Implement and run prompt-only and seeds-only generation; record exact
  model/version, prompts, outputs, cost, and latency.
- [ ] Prompt + partial generation (deferred; request source TBD). Web search comparison is optional.
- [ ] Implement and report prompt-only proxy evaluation with validity/constraint checks.
- [ ] Resolve prompt + partial evaluation (**TBD**) or justify deferring performance claims.

### 3. Playlist-continuation baselines

**Owner:** Spandan. **State:** YouTube Music and co-occurrence scored on all 40 inputs.

- [x] Complete the YouTube Music continuation experiment on seed-only copies.
- [x] Implement and run the required non-ML baseline (seed-song co-occurrence).
  Prompt-based retrieval and LLM reranking are optional.
- [ ] Evaluate all comparable methods (including the LLM) on the same examples and
  fixed recommendation budget; report results, failures, and proxy limitations.

### 4. Writeup and submission

**Owner:** unassigned/shared. **State:** not started.

- [ ] Obtain grading feedback; revise answers scored 1 with original/revision/change notes,
  including any necessary corrections to platform-capability claims.
- [ ] Make slides for presentation
- [ ] Explain baselines, split, constrained metrics, results, limitations, and improvement needed to justify deployment. Participant satisfaction remains the eventual product eval.
- [ ] Produce the short PDF and GitHub code link; verify instructor/TA access and reproducibility.
