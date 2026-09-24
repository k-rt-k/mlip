# Spotify Million Playlist Dataset (MPD)

Reference only — **not obtained, not used yet**. Looked up 2026-09-23 as the
candidate source of collaborative signal and of held-out similarity labels for
evaluating the audio embedders (see `docs/eda_workflow.md`).

## Access — no longer self-service ⚠️

The [AIcrowd challenge page](https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge)
now states: *"The dataset associated with this challenge is not available for
download anymore. We request you to directly reach out to Spotify Research for
access to this dataset."*

- Challenge submissions remain open; only the data handoff moved.
- Access route: request directly from
  [Spotify Research](https://research.atspotify.com/2020/09/the-million-playlist-dataset-remastered).
  A CMU course/research affiliation is what such a request wants.
- **Plan accordingly**: any evaluation that depends on MPD is gated on a request
  that may not land. Fallback ground truth reachable with keys we already have:
  Last.fm tag overlap, or Last.fm `artist.getSimilar`.

## Contents

US Spotify users, **January 2010 – November 2017**, sampled from >4 billion
public playlists.

| | |
|---|---|
| playlists | 1,000,000 |
| track entries (with repeats) | 66,346,428 |
| **unique tracks** | **2,262,292** |
| unique albums | 734,684 |
| unique artists | 295,860 |
| unique playlist titles | 92,944 (17,381 normalised) |
| mean playlist length | 66.35 tracks |
| files | 1,000 JSON slices |

## Schema

Slices are named `mpd.slice.<START>-<END>.json` (1,000 playlists each). Each
file is a dict with `info` and `playlists`.

**`info`**: `slice`, `version`, `description`, `license`, `generated_on`

**playlist**

| field | type | notes |
|-------|------|-------|
| `pid` | int | playlist id, 0–999,999 |
| `name` | str | playlist title |
| `description` | str | optional, user-provided |
| `modified_at` | int | epoch seconds |
| `num_tracks` / `num_albums` / `num_artists` | int | |
| `num_followers` | int | at time of dataset creation |
| `num_edits` | int | editing sessions |
| `duration_ms` | int | total |
| `collaborative` | bool | |
| `tracks` | array | track objects below |

**track**

| field | type | notes |
|-------|------|-------|
| `pos` | int | 0-based position in playlist |
| `track_name` / `album_name` / `artist_name` | str | primary artist only |
| `track_uri` / `album_uri` / `artist_uri` | str | `spotify:track:<id>` etc. |
| `duration_ms` | int | |

## Why it is worth the access request

`track_uri` carries real Spotify ids, so MPD **joins exactly** against the track
ids we already pulled — no name matching, unlike every metadata source in
`docs/eda_workflow.md`. That gives two things nothing else we have does:

1. **Collaborative signal** — co-occurrence in real human playlists, the signal
   the dev-mode API removed when public playlist/user endpoints were cut.
2. **Held-out similarity labels we did not pick** — same-playlist co-occurrence
   as ground truth for comparing CLAP / MuQ-MuLan / CLaMP 3, replacing the
   informal self-chosen pairs used so far.

Caveat: it ends in 2017, so it says nothing about post-2017 tracks — the same
recency wall as the other frozen sources, and ~46% of one user's library here.
