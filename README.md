# MLIP Course Project

Course project for CMU's Machine Learning In Practice: exploring a Spotify
recommendation + playlist builder (and a peer-review assistant as the
alternative topic). See `w0_writeup.md` and `docs/` for details.

## Setup

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
