# Project Status

Scope: [SCOPE.md](SCOPE.md). Deliverables: [baselines milestone](../milestones/baselines.md).

## 2026-10-05 — Radio Pool baseline scored

- **Ready:** public song-radio aggregation (`baselines/candidates.py`,
  `build_candidate_pools.py`, `run_radio_pool.py`) and
  [Radio Pool predictions](../predictions/radio_pool.json) for all 40 paired
  five/twenty-seed inputs. Continuation comparison owner: Spandan.
- **Method:** collect up to 50 cleaned radio tracks per seed, union with
  reference-corpus co-occurrence candidates (no popularity fallback), exclude
  seeds, and rank by number of supporting seed radios, first-seen radio position,
  then video ID. Retain 60 candidates and recommend the first five. Hidden songs
  enter only downstream ceiling/scoring, never candidate construction.
- **Results (@5, five/twenty seeds):** precision **0.23 / 0.20**, hit rate
  **0.45 / 0.60**, NDCG **0.2250 / 0.1921**. Pool ceilings: **0.85 / 1.00**.
  All 40 lists contain five unique non-seed IDs; 399 unique seed radios were
  cached with zero collection errors.
- **Handoff:** [radio data ZIP](../datasets/radio-pool-v1.zip) and
  [checksum/provenance manifest](../datasets/radio-pool-v1.manifest.json)
  supplement the existing v4 dataset. They contain normalized radio tracks,
  frozen pools/settings, and the full evaluation, with no credentials.
  Extraction: [README](../README.md); commands and comparison: [evaluation](evaluation.md).
- **Limitations:** this is our aggregation heuristic over YouTube Music's own
  radio algorithm, distinct from native playlist suggestions. Exact-ID recovery
  remains an offline proxy; paired inputs are not independent playlists. LLM
  Rerank is deferred and is not part of this completed baseline.

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

## 2026-10-05 — Zero-shot LLM baseline scored (Ayush)

- **Ready:** Qwen3.8 27B via OpenRouter on the ModelRun host (fp4; temperature 0,
  structured JSON, prompt `v1`, one run). Prompt-only requests and five-seed
  inputs used the free tier (`qwen/qwen3.8-27b:free`); the free tier was gone
  before the twenty-seed run, so ids 21–40 used the paid model pinned to ModelRun
  (`--provider ModelRun`, $0.11). The model returns titles/artists, resolved to
  video IDs by public YouTube Music search (title + artist match). 20 songs are
  requested per prompt (top 10 kept) and 10 per partial input (top 5 kept).
- **Artifacts:** raw responses and run files in `data/llm/runs/qwen3.8-27b-v1/`
  (free) and `data/llm/runs/qwen3.8-27b-modelrun-v1/` (paid);
  [`predictions/llm_qwen.json`](../predictions/llm_qwen.json) (all 40 partial
  inputs) and [`predictions/llm_qwen_prompt_only.json`](../predictions/llm_qwen_prompt_only.json),
  built by `llm/scripts/export_predictions.py`, which pads short or empty lists
  so missing places score as misses. Prompt-only scoring:
  `evaluation/evaluate_prompt_only.py` (relevant = in any of the prompt's three
  reference playlists). Result tables: `llm_baseline_result.txt`,
  `llm_prompt_only_result.txt`.
- **Results (@5, five/twenty seeds):** precision **0.02 / 0.02**, hit rate
  **0.10 / 0.05**, NDCG **0.0158 / 0.0173** (4 hits in 200 places). Prompt-only:
  precision 0.04, hit rate 0.15, NDCG 0.0330; counting any matching upload as a
  hit raises prompt-only NDCG to 0.069 (continuation unchanged).
- **Limitations:** 68% (prompt-only) and 49% / 52% (five/twenty seeds) of
  suggestions resolve; 9 of 40 partial inputs end with no usable song. Failures
  are invented or misattributed songs, duplicates, and repeated seeds; classical
  credits rarely resolve. Temperature 0 is not repeatable on these endpoints (a
  rerun of examples 11–20 shared 0–4 of 10 songs), so single-run scores are noisy.
- **Remaining:** prompt + seeds generation (needs a written request per partial
  input); prompt constraint/validity checks.

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
**Owner:** Ayush. **State:** prompt-only (20) and seeds-only (all 40 partial inputs) generated and scored.

- [x] Implement and run prompt-only and seeds-only generation; record exact
  model/version, prompts, outputs, cost, and latency.
- [ ] Prompt + partial generation (deferred; request source TBD). Web search comparison is optional.
- [x] Implement and report prompt-only proxy evaluation (reference-playlist overlap).
- [ ] Prompt validity/constraint checks (e.g. instrumental, language, era).
- [ ] Resolve prompt + partial evaluation (**TBD**) or justify deferring performance claims.

### 3. Playlist-continuation baselines

**Owner:** Spandan. **State:** YouTube Music, co-occurrence, and Radio Pool scored
on all 40 inputs.

- [x] Complete the YouTube Music continuation experiment on seed-only copies.
- [x] Implement and run the required non-ML baseline (seed-song co-occurrence).
  Prompt-based retrieval and LLM reranking are optional.
- [x] Collect, freeze, and score Radio Pool on all 40 inputs; share its cached
  radios, pools, predictions, and evaluation.
- [ ] LLM Rerank over the same candidates (deferred, separate baseline).
- [x] Score all comparable methods (including the LLM) on the same 40 inputs at K = 5.
- [ ] Report results, failures, and proxy limitations in the writeup.

### 4. Writeup and submission

**Owner:** unassigned/shared. **State:** not started.

- [ ] Obtain grading feedback; revise answers scored 1 with original/revision/change notes,
  including any necessary corrections to platform-capability claims.
- [ ] Make slides for presentation
- [ ] Explain baselines, split, constrained metrics, results, limitations, and improvement needed to justify deployment. Participant satisfaction remains the eventual product eval.
- [ ] Produce the short PDF and GitHub code link; verify instructor/TA access and reproducibility.
