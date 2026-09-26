# Benchmark: our recommenders vs Spotify's own picks

Spotify's recommendations cannot be fetched by our app (checked live
2026-09-24: `/recommendations` 404, related-artists and artist top-tracks
403), and other users' playlists return no tracks in Development Mode. So the
benchmark is captured by hand in the Spotify app and scored by script.

Code: `spotify/src/benchmark.py` (pairing, recommender, scoring),
`spotify/scripts/run_benchmark.py` (CLI), `LastFM.similar_tracks` in
`spotify/src/enrich.py`.

## Capturing a playlist (in the Spotify app)

1. Copy the playlist into your library as **`seed: <name>`**
   (desktop: Ctrl/Cmd+A -> Add to Playlist -> New Playlist; mobile:
   ... -> Add to other playlist -> New playlist).
2. Optional: add the songs Spotify shows under that copy in "Recommended
   songs" to **`recs: <name>`**. Without it we still generate
   recommendations, just no score.

Names pair case-insensitively. "Recommended songs" is computed for the
viewing account, so your history influences it; for playlist-only
suggestions, capture step 2 from a fresh account allowlisted as another
`--user` (see `docs/spotify_api.md`, onboarding).

## Running

    python spotify/scripts/run_benchmark.py --user kartik [--top-n 50]

Writes `data/spotify/<user>/benchmark.json` (captured tracks) and
`benchmark_results.json`; Last.fm lookups are cached in
`data/spotify/lastfm_similar.json`, shared across users.

## Method

- **Recommender (`lastfm`)**: for every seed track, Last.fm
  `track.getSimilar` (collaborative filtering over all scrobbles — no user
  profile involved); candidates are ranked by their summed similarity to all
  seeds; seed tracks are never recommended. `lastfm-new-artists` also drops
  the seed artists.
- **Scoring**: tracks match on a normalised (artist, title) key (case,
  diacritics, curly quotes and feat./version suffixes ignored), since Last.fm
  returns names and one recording can have several Spotify ids. Reported:
  hits, precision, recall against Spotify's list, and **artist recall** — did
  we reach the right artists even when not the exact songs.

## Sanity check (2026-09-26, before any capture)

Held-out test on one real playlist ("Some songs (2)", 51 tracks): seed with a
random half, try to recover the other half.

| variant | held-out tracks in top 50 | artist recall |
|---------|---------------------------|---------------|
| `lastfm` | 2 / 26 | 16% |
| `lastfm-new-artists` | 0 / 26 | 12% |

Pipeline works end to end (25 seeds, 15 s including Last.fm calls). The low
numbers are informative rather than a verdict:
- The playlist is eclectic (MF DOOM, Echosmith, Bollywood). **Summing
  similarity lets the densest cluster dominate** — the top 5 was mostly MF
  DOOM. A per-seed normalisation or per-cluster quota is the obvious next
  variant to try.
- **Artist aliases leak through** "new artists": Viktor Vaughn and
  DANGERDOOM are MF DOOM. Excluding by name cannot catch aliases.
- Recovering a random half of a personal playlist exactly is a hard task;
  Spotify's `recs:` lists are the intended reference.
