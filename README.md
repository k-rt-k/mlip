# MLIP Course Project

Course project for CMU's Machine Learning In Practice: a music playlist
recommender guided by natural-language requests and optional existing songs.
See [docs/SCOPE.md](docs/SCOPE.md) for the project goal and
[docs/STATUS.md](docs/STATUS.md) for current progress and remaining baseline work.

Coding agents should start with [AGENTS.md](AGENTS.md). Shared project context
lives in `docs/SCOPE.md` and `docs/STATUS.md`, with completed-task summaries newest first.
`w0_writeup.md` records the initial Spotify project idea.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
`uv sync` from this directory. `.python-version` selects Python 3.12; `uv.lock`
pins dependencies. Run tests with `uv run pytest`.

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
