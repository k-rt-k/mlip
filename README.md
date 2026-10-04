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
