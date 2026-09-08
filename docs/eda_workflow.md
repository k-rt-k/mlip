# Spotify EDA Workflow — Feasibility Check

Goal: decide whether the Spotify recommender project is feasible given the
2024–26 API restrictions (see `docs/spotify_api.md`), as input to the
spotify-vs-peer topic decision.

Status: **steps 1–2 complete** (2026-09-08); next: discuss which API features
to target, then steps 3–4.

## Step 2 results (personal-data inventory, 2026-09-08)

Pulled via `spotify/scripts/inventory.py`; raw JSON cached in `data/spotify/`.

- **2,152 unique tracks** total: top tracks 145/546/1,937 (short/medium/long
  term — long_term is the motherlode), 236 saved, 65 playlist tracks (2 owned
  playlists; 3 followed playlists 403 — non-owned items blocked), 42 recently
  played, 15 followed artists, 11–109 top artists by range.
- Overlaps are small (7% of top tracks saved, 12% of recent saved) → the
  collections are complementary, not redundant.
- Freshness: recently-played caps at ~50 events; history depth comes from
  top-tracks long_term instead.
- Gotcha found: playlist entries wrap the track under `item` (Feb 2026
  rename) — normalized by `client.unwrap_item()`.

## Steps

1. **Setup** — create the dashboard app, fill `spotify/.env`, run
   `spotify/scripts/smoke_test.py` end-to-end. *(user + done code)*
2. **Personal-data inventory** — pull everything the API gives us about one
   user: top tracks/artists (3 time ranges), saved tracks, playlists + their
   tracks, recently played, followed artists. Record sizes, overlap, freshness.
3. **Metadata richness audit** — for the pulled tracks, join single-item
   metadata and ask: is this enough signal for a useful exploration/
   exploitation playlist builder? ⚠️ Smoke test (2026-09-08) showed dev-mode
   objects are slimmer than documented: **no artist genres, no popularity** —
   only duration, explicit, release date, album metadata survive
   (see docs/spotify_api.md).
4. **Gap analysis** — quantify what the deprecations cost; evaluate
   supplements: Million Playlist Dataset (collaborative signal), Kaggle
   audio-feature dumps (frozen content features keyed by track id), open
   audio-analysis alternatives.

   **First result (2026-09-08, `spotify/scripts/coverage.py`)**: the Kaggle
   114k dump (HF mirror `maharshipandya/spotify-tracks-dataset`; 89,741 unique
   ids, genre-stratified ~1k/genre, frozen ~2022) covers only **162/2,152
   (7.5%)** of our tracks by id — best on playlists (21.5%) and saved (14.8%),
   worst on recent (6.1%). An exact-id join on this dump is not viable.
   Candidate next moves: (a) the 1.2M-track Kaggle dump (needs Kaggle API
   token), (b) fuzzy (artist, title) matching — ids differ across re-releases,
   so id-join undercounts, (c) build on collaborative/external-genre signals
   instead of audio features.
5. **Feasibility verdict** — short writeup here in `docs/` with a go/no-go
   recommendation and the pivots available if no-go.

Steps 2–4 will be refined after we discuss which API features to build around.

## Code pointers

- Auth: `spotify/src/auth.py` (PKCE, scopes)
- API surface: `spotify/src/client.py` (`SpotifyClient`, `BLOCKED_METHODS`)
- Smoke test: `spotify/scripts/smoke_test.py`
- Tests: `spotify/tests/test_client.py`
