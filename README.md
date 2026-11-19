# MLIP Course Project

Course project for CMU's Machine Learning In Practice: a music playlist
recommender guided by natural-language requests and optional existing songs.
See [docs/SCOPE.md](docs/SCOPE.md) for the project goal and
[docs/STATUS.md](docs/STATUS.md) for current progress and remaining milestone work.

Coding agents should start with [AGENTS.md](AGENTS.md). Shared project context
lives in `docs/SCOPE.md` and `docs/STATUS.md`, with completed-task summaries newest first.
`w0_writeup.md` records the initial Spotify project idea.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
`uv sync` from this directory. `.python-version` selects Python 3.12; `uv.lock`
pins dependencies. Run the lightweight suite separately from optional PyTorch
encoder tests; the local FAISS/PyTorch wheels conflict through OpenMP when loaded
together:

```sh
uv run python -m pytest --ignore=spotify/tests/test_embeddings.py
# In an existing encoder environment with PyTorch, separately:
/path/to/encoder-venv/bin/python -m pytest spotify/tests/test_embeddings.py
```

CPU prompt-to-music search supports exact, IVF and HNSW over precomputed CLAP
vectors. Its shared interface is `EmbeddingCatalog`, `IndexConfig`, and
`RetrievalIndex.build/search/save/load`; see the docstrings in `retrieval/`
and `uv run python -m retrieval --help`. Corpus/query NPZs contain string `ids`
and numeric `vectors` arrays. IDs retain their original namespace.

On Babel, keep full-catalog artifacts, temporary files and model caches on data
storage. The verified raw-CLAP snapshot is under
`/data/user_data/hpoonia/mlip/retrieval/mpd-v1/snapshot/`; small local reports are
under `/home/hpoonia/mlip/data/retrieval/mpd-v1/`. These files are not in Git.
For a new run, from a compute node with storage mounted:

```sh
umask 022  # Keep new shared artifacts readable by teammates.
MLIP_STORAGE=/data/user_data/hpoonia/mlip
export TMPDIR="$MLIP_STORAGE/tmp"
mkdir -p "$TMPDIR"
uv run python scripts/validation/audit_retrieval.py --help
uv run python -m retrieval.prepare_mpd --help
# Encode in the existing separate environment; no FAISS import:
OMP_NUM_THREADS=4 "$MLIP_STORAGE/encoder-venv/bin/python" spotify/scripts/embed_text_queries.py --output data/retrieval/text-queries.npz
uv run python -m retrieval benchmark \
  --corpus "$MLIP_STORAGE/retrieval/mpd-v1/snapshot/corpus.npz" \
  --queries data/retrieval/text-queries.npz \
  --configs retrieval/configs/mpd-v1.json --threads 4 --k 100 \
  --warmups 2 --repeats 10 \
  --artifacts-dir "$MLIP_STORAGE/retrieval/new-run/indexes" \
  --output data/retrieval/new-run/benchmark.json
```

Output directories must be new. The query encoder reuses
`spotify.src.embeddings.get_embedder('clap')` and records checkpoint revision,
package versions and checksums in the adjacent JSON. The verified encoder used
Python 3.12, torch 2.14.1+cpu, transformers 5.17.0, numpy 2.4.6 and librosa 0.11.0;
it is separate from the pinned CPU retrieval environment. Benchmark settings
reuse builds where only `nprobe`/`ef_search` changes. Reports include exact-neighbor
recall, warm search latency, build time, serialized size and worker peak RSS.
Encoding/loading/IO are outside the latency measurement. These measurements do
not establish recommendation quality.

The run-specific recording-overlap scorer is under `experiments/retrieval/`:

```sh
uv run python -m experiments.retrieval.score_mpd_retrieval --help
```

It uses upstream ISRC evidence, deduplicates recordings, retains unmatched
reference songs and counts short outputs as misses. Its defaults refer to the
saved Babel development run; pass `--query-manifest` for newly encoded queries.
The learned metadata/title-supervised models and live experiments remain local
in the feature worktree; [STATUS.md](docs/STATUS.md) summarizes their findings
and remaining work.

## Prompt-conditioned playlist retrieval

`experiments/retrieval/` also contains the initial no-training prompt-plus-
playlist experiment. It combines a CLAP text embedding with the normalized mean
of available CLAP seed-song embeddings, retrieves from the embedded public
reference pool, then reranks the first-stage candidates by seed similarity.
Data loading (`playlist_data.py`) and fusion/ranking policy (`playlist_model.py`)
are separate so later experiments can replace the model without changing input
handling.

The frozen labels in
`data/youtube_music/partial_examples/v3/prompt_inputs.json` are built by
`build_partial_prompts.py`. They were manually authored from visible seed-track
metadata only; a source playlist's five- and twenty-seed inputs share one
prompt. Regenerate the ignored local artifact after extracting the dataset:

```sh
uv run python -m experiments.retrieval.build_partial_prompts \
  --output data/youtube_music/partial_examples/v3/prompt_inputs.json
```

The prediction runner reads `model_inputs.json`, the frozen prompt labels,
public reference-pool candidates, and Kartik's cached YTM CLAP vectors. It does
not read `dataset.json` or held-out tracks. Candidate IDs are YouTube Music
video IDs, so its output has the same `{example_id: [video_id, ...]}` contract
as `predictions/cooccurrence.json` and `predictions/ytm_native.json` and can use
the shared evaluator directly. Run it in the separate encoder environment:

```sh
/data/user_data/hpoonia/mlip/encoder-venv/bin/python \
  -m experiments.retrieval.run_playlist_conditioned \
  --embeddings /data/user_data/ksnair/mlip/embeddings/ytm-eval/clap.npz \
  --output predictions/prompt_playlist_clap_fusion.json \
  --report data/retrieval/prompt_playlist_clap_fusion/report.json \
  --prompt-weight 0.5 --rerank-seed-weight 0.25 --top-k 5 --device cpu
uv run python evaluation/evaluate.py \
  --predictions predictions/prompt_playlist_clap_fusion.json \
  --output data/retrieval/prompt_playlist_clap_fusion/evaluation.json
```

Both output paths must be new. The report records per-example missing seed
vectors and whether the model fell back to prompt-only retrieval; do not treat
those fallbacks as seed-conditioned results. The cached `clap.npz` is a Babel
artifact rather than a Git dataset handoff.

The twenty synthetic prompts are in `prompts.txt`. YouTube Music collection,
partial-playlist creation, suggestions, and browser-auth setup commands are documented
in the scripts under `youtube_music/scripts/` (also available via `--help`).
Keep fetched data and account credentials under gitignored `data/youtube_music/`.

The shared baseline dataset is committed in
[datasets/baselines-v4.zip](datasets/baselines-v4.zip), with a
[checksum manifest](datasets/baselines-v4.manifest.json). After cloning or pulling,
extract it from the repository root:

```sh
unzip -o datasets/baselines-v4.zip 'data/*' dataset-manifest.json -d .
```

This restores the 20-prompt reference dataset and 40 partial inputs: the same
20 source playlists at sizes 5 and 20. Selection manifests and source snapshots
are included; the original five-song v2 dataset is retained for compatibility.
Use `data/youtube_music/references/v2/reference_pools.json` for prompt references
and `data/youtube_music/partial_examples/v3/model_inputs.json` for the forty partial inputs;
`dataset.json` in the same partial directory contains the hidden answers.
The archive contains no credentials. Reading the saved datasets needs no login;
live operations on private playlist copies require their owning account.
All forty inputs have verified private copies owned by `mlip.team0@gmail.com`.
`source_example_id` pairs inputs from the same source; `seed_count` is 5 or 20.
The larger input includes the original five seeds. Every other source song is
hidden for that size, so hidden counts vary and are smaller for the 20-song input.
The generating script is `youtube_music/scripts/prepare_nested_partials.py`;
its docstring includes the reproducible command and complete setup.
Re-extract after pulling updates to replace stale local dataset IDs; extraction leaves tracked prompts and code unchanged.
The extracted root `dataset-manifest.json` is generated and gitignored; the
checked-in checksum manifest under `datasets/` is the shared reference.

The completed **Radio Pool** baseline adds public per-seed radio aggregation.
Its saved predictions are in `predictions/radio_pool.json`. Extract the
[radio data supplement](datasets/radio-pool-v1.zip) after the v4 dataset to
reproduce them offline:

```sh
unzip -n datasets/radio-pool-v1.zip -d .
uv run python evaluation/evaluate.py --predictions predictions/radio_pool.json
```

The supplement contains all 399 normalized seed-radio caches, 40 candidate pools,
and the evaluation results; [its manifest](datasets/radio-pool-v1.manifest.json)
records SHA-256 hashes and generation settings. No credentials or LLM responses
are included. Method, results, and fresh-collection commands are in
[docs/evaluation.md](docs/evaluation.md#radio-pool).

After cloning, activate the secret-guard git hooks (once per machine):

```sh
brew install gitleaks   # or your platform's equivalent
git config core.hooksPath scripts/git-hooks
```

## Data & API credits

- Song tempo, key, and audio features provided by
  [GetSongBPM.com](https://getsongbpm.com/)
- Music tags and metadata powered by [Last.fm](https://www.last.fm/) via the
  [Last.fm API](https://www.last.fm/api)
- Listening history via the [Spotify Web API](https://developer.spotify.com/)

## Evaluation app

Run the paired interface with example suggestions from the repository root:

```sh
uv sync
uv run python -m evaluation_app --rehearsal
```

Open **http://127.0.0.1:8060**. Add `--setup manual` for the facilitator's
single-recommender picker. The paired setup starts with a text request and then
supports text plus playlist and playlist-only rounds. Rehearsal feedback is
identified in a separate gitignored SQLite file. Study decisions and open
questions are in [assumptions_and_decisions.md](assumptions_and_decisions.md)
and [questions.md](questions.md).

### Live laptop and Babel setup

On an allocated Babel CPU node, run this in Bash from the repo root. It prepares
the recording lookup if needed and starts the encoder and FAISS in separate
processes. Use the same model and index artifacts for comparable sessions.

```sh
MLIP_STORAGE=/data/user_data/hpoonia/mlip
MPD_ROOT="$MLIP_STORAGE/retrieval/mpd-v1"

if [ ! -f "$MPD_ROOT/evaluation-app-lookup.sqlite" ]; then
  uv run python -m evaluation_app.retrieval_service \
    --build-lookup "$MPD_ROOT/snapshot/tracks.sqlite" \
    --lookup "$MPD_ROOT/evaluation-app-lookup.sqlite"
fi

OMP_NUM_THREADS=4 "$MLIP_STORAGE/encoder-venv/bin/python" -m evaluation_app.encoder_service &
encoder_pid=$!
trap 'kill "$encoder_pid" 2>/dev/null || true' EXIT

uv run python -m evaluation_app.retrieval_service \
  --index "$MPD_ROOT/indexes/build-04/index" \
  --lookup "$MPD_ROOT/evaluation-app-lookup.sqlite" \
  --seed-embeddings /data/user_data/ksnair/mlip/embeddings/ytm-eval/clap.npz \
  --seed-embeddings /data/user_data/ksnair/mlip/embeddings/ytm-eval/seed-youtube-clap.npz
```

Both workers bind to loopback. From the laptop, forward port 8061 to the
allocated Babel node with SSH, adding your normal jump host if needed.

```sh
ssh -N -L 8061:127.0.0.1:8061 <allocated-babel-node>
```

In another laptop terminal, set `OPENROUTER_API_KEY` in the environment or the
ignored `llm/.env` and launch the app from the checkout.

```sh
uv run python -m evaluation_app
```

The default OpenRouter model is `deepseek/deepseek-v4-flash-0731`. Set
`MLIP_LLM_MODEL` to override it. Set `MLIP_LLM_ENV_FILE` to the path of an existing
ignored `.env` when launching from a separate Git worktree. An alternative
OpenAI-compatible adapter accepts
`MLIP_LLM_URL` (full completions URL), `MLIP_LLM_MODEL` and `MLIP_LLM_KEY`.
The live paired setup requires the CPU worker and LLM configuration. Use
`--setup manual` to exercise a single live recommender independently.

The YouTube Music baseline searches public playlists for text-only rounds. For
playlist-only rounds, it creates a temporary private playlist on the team
account, fetches native suggestions, and attempts to delete the copy. Prepare
browser authentication with [setup_auth.py](youtube_music/scripts/setup_auth.py)
while signed in to the team account. The app defaults to
`data/youtube_music/browser.json`. Set `MLIP_YTM_AUTH_FILE` to use a credential
file from another checkout. Credentials are required for playlist-only rounds.
The YouTube Music panel is skipped for combined rounds.

Export local feedback after the study. Keep the export in gitignored storage.

```sh
uv run python -m evaluation_app --export data/evaluation_app/pilot-export.json
```

Use a new export filename for each snapshot. To select a different study database
throughout a run, pass `--db` when launching and exporting. The export includes
keep rate over shown tracks, paired keep rates over rounds where both arms
showed at least one song,
empty slots, unavailable panels, and skipped panels, grouped by participant and
recommender. These commands run local development servers for the pilot.
Public hosting requires a production
WSGI server and deployment configuration. The
[AWS migration guide](docs/aws_migration_plan.md#public-paired-study)
has the live retrieval preview, public paired-study cutover, and operator
instructions. The public study uses `/var/lib/playlist-lab/live.sqlite` on EC2;
the private acceptance app and retrieval preview use separate databases.

### Analyze participant results

Export from the **same database path used to launch the app**. Keep the export and
analysis files in gitignored storage; they contain pseudonymous session IDs,
song choices, ratings, and optional comments. Use a new output filename each
time. For example:

```sh
uv run python -m evaluation_app --db data/evaluation_app/study.sqlite \
  --export data/evaluation_app/pilot-export.json
uv run python -m evaluation_app.results \
  --input data/evaluation_app/pilot-export.json \
  --output data/evaluation_app/pilot-metrics.json \
  --participants-csv data/evaluation_app/pilot-participants.csv
```

The results command validates event references and panel assignments, then
includes **completed, non-rehearsal paired sessions** by default. It excludes
manual tests, unfinished sessions, and sessions with no round where both panels
were available and showed at least one song. The `screening` counts show these
exclusions. Use `--cohort rehearsal` to analyze rehearsal exports separately;
never combine those outcomes with live participants.

The primary result is the **mean across participants** of `(retrieval keeps /
retrieval songs shown) - (assigned baseline keeps / baseline songs shown)`.
Each participant's rates use only eligible paired rounds, including their
refinements; each participant contributes one difference. The JSON reports
results separately for the LLM and YouTube Music comparisons. A positive
difference favors retrieval. Mirrored Keep/Reject decisions count once in each
panel's rate, but their two offers are not independent observations. Sessions
with fewer than ten eligible participants per comparison receive no confidence
interval; larger samples get a fixed-seed participant bootstrap interval.

The JSON participant rows also report shown, kept, rejected, undecided, judged
fraction, play clicks, overlapping recordings, round modes, mode-specific paired
counts, final playlist size, empty slots, unavailable and skipped panels,
duration, and optional ratings. The CSV gives a compact participant-level table
of the primary rates and session context.
Unjudged offers remain in the `shown` denominator. A play click means an
attempt, not confirmed audio playback. Final and fifth-round ratings describe
the whole shared-playlist session and must not be attributed to either panel.
The `all_rounds` breakdown is diagnostic; the primary paired comparison
excludes rounds with an empty, unavailable, or inapplicable panel. These are
descriptive pilot results, not a causal or significance claim on their own.
