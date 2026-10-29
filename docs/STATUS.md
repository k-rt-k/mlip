# Project Status

Scope: [SCOPE.md](SCOPE.md). Deliverables:
[initial ML solution](../milestones/initial_ml_solution.md),
[baselines milestone](../milestones/baselines.md).

## 2026-10-28 — Seed-audio coverage and YouTube fallback probe (Kartik)

- **Dataset:** the 40 five-/twenty-song partial inputs contain 399 distinct seed
  video IDs; the twenty-song input includes its paired five seeds. Cached CLAP
  vectors cover 160 seeds. All 239 uncovered seeds have `no_match` in the
  existing Deezer map, leaving 11 inputs with no embedded seed. Examples include
  Rousseau's Scriabin/Chopin uploads, Sophie Milman tracks credited to upload
  channels, and Keyshia Cole's *I Should Have Cheated*. `no_match` does not
  establish that the recording is absent from Deezer.
- **Feasibility probe:** `ytmusicapi.get_song()` reported playable audio formats
  for the Scriabin and Keyshia Cole seeds, but only signature-cipher URLs.
  `yt-dlp` fetched a decodable 30-second segment from each YouTube video; the
  existing CLAP encoder produced a finite, normalized 512-D vector from the
  Scriabin segment. Probe clips and the seed-only retrieval smoke check remain
  local under `data/retrieval/seed-smoke/` and are not dataset handoff artifacts.
- **Remaining:** implement request-time retrieval and caching of missing seed
  embeddings, then evaluate seed-only retrieval, text-plus-seed retrieval, and
  seed-based reranking. The probe did not update `clap.npz` or change the 11-input
  coverage gap; it does not establish recommendation quality or coverage for all
  239 unmatched videos. Text-only retrieval does not depend on seed audio.

## 2026-10-28 — Prompt-only retrieval infrastructure and modeling progress (Harsh)

- **Shared:** CPU FAISS exact/IVF/HNSW search, validated catalog loading,
  checksummed index persistence, retained benchmark predictions, frozen query
  encoding, and audited MPD snapshot preparation in `retrieval/`,
  `spotify/scripts/embed_text_queries.py`, and `scripts/validation/audit_retrieval.py`.
  Recording-level metrics live in `evaluation/recordings.py`; the run-specific
  scorer is separate in `experiments/retrieval/score_mpd_retrieval.py`.
  Commands/setup: [README](../README.md) and source docstrings.
- **Search benchmark:** 1,025,994 audio-covered MPD tracks (512-D CLAP),
  20 frozen development prompts, six builds / 24 settings, four CPU threads
  on Babel-v9-20 (EPYC 7313), ten warm repetitions per query. Exact search p95
  **75.96 ms**; HNSW M=16 / efConstruction=100 / efSearch=512 p95 **1.31 ms**,
  ANN recall@5/@100 **0.990 / 0.9815**, serialized index **2.095 GiB**, build
  **138.4 s**. Encoding/loading/IO are excluded. ANN recall measures recovery
  of exact neighbors; these provisional settings do not establish song relevance.
- **Raw CLAP quality check:** upstream metadata-derived ISRC matching covers
  **698 / 4,485** per-prompt reference-recording memberships (15.6%). All
  24 trials have zero precision/hit rate/NDCG at 5 and 10; unmatched references
  remain in scoring. The prompt-only LLM rescored with the same identity policy
  has P@5 **0.04**, NDCG@5 **.0330**. This diagnostic inherits matching errors,
  limited catalog coverage and incomplete reference positives. A metadata-only
  assistant review of exact top-two outputs found 17 plausible, nine poor fits,
  14 uncertain; no audio was auditioned.
- **Completed exploratory comparisons (code/results remain local):** metadata
  and training-playlist-title supervision improve held-out-title member recovery:

  | Method | HR@10 | NDCG@10 |
  |---|---:|---:|
  | Frozen CLAP text → audio (pilot diagnostic) | 0.27% | .0002 |
  | Frozen E5 metadata | 7.70% | .0284 |
  | Learned E5 query/song projections | 20.68% | .0422 |
  | Song title profiles + hard negatives | 30.17% | .0650 |
  | Song/artist profiles + hard negatives + semantic anchor | 31.24% | .0775 |
  | Matched song-only control | 31.24% | .0713 |
  | E5 title-neighbor membership counts | 33.84% | .0853 |

  HR@10 counts titles with at least one known member in ten results; NDCG@10
  also rewards rank and multiple recovered members. Full supervision:
  621,870 training playlists, 12,704 normalized titles,
  13.78M title–song links; evaluation uses 1,117 validation titles and the same
  1.03M candidates. Exact normalized titles are disjoint across 80/10/10
  splits; songs overlap and near-duplicate titles remain. Checkpoint selection
  uses 512 validation titles; many settings were tuned on validation. No test
  ranking scores exist for the 1,102 test titles. These exploratory single-run
  membership scores are distinct from the YouTube prompt-reference proxy.
- **Prompt behavior:** the highest membership score still produces generic pop
  for some Hindi/bossa/instrumental requests. A soft-facet/audio hybrid's top-two
  review on the 20 repeatedly seen prompts found **32 broadly reasonable,
  one poor fit, seven uncertain** (assistant review, no listening/blinding).
  Mood and combined constraints remain unreliable. A metadata-only extension
  reaches all **2,262,292 MPD tracks**, but still fails “90s Bollywood romance”;
  verified release-year/language fields are unavailable. Learned/hybrid models
  use exact GPU scoring and sparse associations; their ANN indexes are not built.
- **Acoustic-attribute results:** linear classifiers over frozen audio,
  plain E5 metadata, or both learn instrumental/vocal, low/high energy and
  sad/happy scores from repeated training-title evidence (at least two supporting
  memberships, none for the opposite class). Display-artist groups are disjoint
  between training and validation; checkpoints use that same validation set.

  | Weak attribute labels | Validation tracks | Audio AUROC | Audio + metadata AUROC |
  |---|---:|---:|---:|
  | Instrumental / vocal | 2,875 | .9961 | .9964 |
  | Low / high energy | 7,704 | .9712 | .9729 |
  | Sad / happy | 536 | .8824 | .9003 |

  These measure agreement with noisy playlist-derived labels, not listening-based
  accuracy, prompt relevance or an independent test. Energy/mood labels use
  model-selected descriptive training titles; the vocal labels use explicit form
  cues. Features exclude title-derived song profiles.
- **Vocal-form and prompt checks:** on four constructed vocal-form requests, the
  audio vocal head changes the piano/guitar singer suggestions while preserving
  the two instrumental pairs. The guitar-with-vocals example now returns Calum
  Graham's *Half Your Heart* and *Billie Jean*. Descriptive-title routing plus
  acoustic heads changes the seen dreamy-drive pair from *Sail* / *Riptide* to
  *Skinny Love* / *Intro*, and mellow jazz to *In A Sentimental Mood* /
  *Summertime*. These are non-blind metadata inspections without listening;
  the earlier 32/40 hybrid review does not score this new recipe.
- **Completed follow-ups:** 41 contrasting-energy title pairs yield HR@10
  **31.07% / NDCG .0747**, versus the semantic baseline's **31.24% / .0775**.
  Sampled-positive loss falls to **11.46% / .0330** (repeated evidence:
  **17.73% / .0462**). Descriptive-title sampling reaches **30.26% / .0739**
  overall and HR@10 **30.81%** on 185 model-selected descriptive validation
  titles (baseline **29.19%**). Title-count retrieval gets **43.78%** on that
  slice; 14/185 titles have a training title with the same word bag. The slice
  was used for selection and is not independent quality evidence. Audio gating,
  LoRA, sentence wrappers, synthetic conjunctions, centering, title filtering and
  reranking have not established a better full-prompt method.
- **Integration and remaining failure:** the local experimental CLI's acoustic
  recipe ran on both the 1.03M audio-covered and 2.26M full-MPD catalogs.
  Missing-audio tracks receive neutral acoustic scores. The full catalog still
  returns Barenaked Ladies — *One Week* and Hootie & the Blowfish — *Only Wanna
  Be With You* for “90s Bollywood romance,” a clear genre/language failure.
  A routing correction preserves exact Hindi/Bollywood facet matches previously
  excluded by descriptive-title selection; its backend rerun still fails. The
  full CLI passed before that correction and has not been rerun afterward.
- **Still exploratory:** acoustic-query scoring, descriptive-title routing,
  calibrated attribute fusion and compound-constraint handling. The 24 contrasting
  development requests measure response sensitivity, not correctness. No final
  recipe, independent relevance estimate or test ranking score is available.
- **Local artifacts:** active code is in `playlist_model/` in
  `/home/hpoonia/mlip-text-music-retrieval` (separate from shared `retrieval/`).
  Login-readable summaries/results: `/home/hpoonia/mlip/data/retrieval/mpd-v1/`
  and `data/retrieval/overnight/` (`experiments.csv`, `full-results/`,
  `constraint-diagnostic/`, `top2-review.md`). Attribute evidence is in
  `vocal-attribute/results.json`, `energy-attribute/results.json`, and
  `mood-attribute/results.json`; slice/review evidence is in `validation-slices.md`
  and `constraint-diagnostic/{development-comparison,vocal-review}.md`.
  Large snapshots/indexes are under
  `/data/user_data/hpoonia/mlip/retrieval/mpd-v1/`; model features/checkpoints
  under `/data/user_data/hpoonia/mlip/overnight/`. These are Babel-local,
  gitignored artifacts; no datasets, weights or live run logs are added here.
- **Remaining:** independent constraint-focused review with audio listening,
  reliable recording metadata, final model selection and comparable baseline
  evaluation, seed-conditioned modeling, and the ML milestone writeup.

## 2026-10-26 — CLAP audio embeddings for MPD and eval songs (Kartik)

- **Ready:** 1,028,385 CLAP vectors (`laion/larger_clap_music_and_speech`, 512-D,
  L2-normalized, 30 s Deezer previews; text queries embed into the same space).
  Stored on Babel under `/data/user_data/ksnair/mlip/embeddings/`, not in Git.
  - **Eval songs** (`ytm-eval/`): 2,391 of 5,958 unique video IDs in the v3
    partial inputs and v2 reference pools. `clap.npz` is keyed by video ID;
    `deezer_map.json` records the Deezer ID, ISRC, and match evidence per song.
    Built by `spotify/scripts/map_eval_deezer.py`.
  - **Spotify MPD** (`mpd-full/clap/`): 1,025,994 of 2,262,292 unique tracks
    (45%), keyed by Spotify track ID. Built by `spotify/scripts/mpd_pipeline.py`;
    details in [mpd_dataset.md](mpd_dataset.md).
- **Limitations:** matching is by title/artist/duration metadata (no ISRCs from
  YouTube or MPD), so unmatched songs are not necessarily missing from Deezer.
  Eval coverage is 76% for official audio, 41% for music videos, and ~0% for
  user uploads. Only **29% of hidden partial songs** are covered, so scores on
  covered songs are biased toward official audio. Full overlap between eval songs
  and MPD is not computed; the prompt-reference subset is audited above.
- **Remaining:** seed-conditioned embedding evaluation; the v2 matching
  policy in `spotify/src/mpd.py` (+~19% on a no-match sample) is implemented
  but not run over MPD.

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
  `spotify/`; no interactive prototype is implemented.

## Initial ML solution — current checklist

**Prompt-only retrieval owner:** Harsh. **State:** search infrastructure shared;
learned retrieval remains exploratory. Due October 29; see the
[assignment](../milestones/initial_ml_solution.md).

- [x] Implement and benchmark exact/IVF/HNSW over the full audio-covered MPD catalog.
- [x] Audit recording-overlap coverage and raw-CLAP development recommendations.
- [x] Explore metadata/title-supervised retrieval and record validation comparisons locally.
- [ ] Select a final method with independent constraint/relevance evidence.
- [ ] Compare the chosen ML method and baselines on the same split and metric.
- [ ] Complete seed-conditioned modeling/evaluation and the milestone writeup.

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
