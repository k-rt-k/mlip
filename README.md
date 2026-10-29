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
