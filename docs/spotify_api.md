# Spotify Web API Lookup (as of Sept 2026)

Reference for our code in `spotify/src/`. The API shrank substantially in
Nov 2024 and Feb 2026 — this doc tracks what we can actually call.

## One-time setup (user)

Development Mode now **requires a Spotify Premium account** (Feb 2026 policy).
1. Go to https://developer.spotify.com/dashboard → "Create an App".
2. Name/description: anything (shown on the consent screen). Accept the ToS.
3. In app settings, add Redirect URI: `http://127.0.0.1:8080/callback`
   (must be the loopback IP — `localhost` is rejected).
4. Copy the **Client ID** into `spotify/.env` (from `spotify/.env.example`).
   No client secret needed — we use the PKCE flow.

Dev-mode limits: 1 dev-mode Client ID per account, ≤5 authorized users,
reduced endpoint set (tables below), quota counted per developer account
(July 2026 change).

## Auth flows

| Flow | Use when | Our code |
|------|----------|----------|
| Authorization Code + PKCE | Anything under `/me/*` (personal data). No secret; browser consent once, then token cached. | `spotify/src/auth.py:get_spotify()` |
| Client Credentials | Catalog-only (search/metadata), no user context. | Not implemented — PKCE covers everything we need. |

Token cache: `spotify/.cache-pkce` (gitignored). Scopes: `auth.SCOPES`.

## Available in Development Mode → our wrapper

All via `SpotifyClient` (`spotify/src/client.py`), which handles pagination.

| Endpoint | spotipy method | Our method |
|----------|---------------|------------|
| `GET /me` | `current_user` | `profile()` |
| `GET /me/top/{type}` | `current_user_top_tracks/artists` | `top_tracks()`, `top_artists()` |
| `GET /me/playlists` | `current_user_playlists` | `playlists()` |
| `GET /playlists/{id}/items` | `playlist_items` | `playlist_tracks(id)` |
| `GET /me/tracks` | `current_user_saved_tracks` | `saved_tracks()` |
| `GET /me/player/recently-played` | `current_user_recently_played` | `recently_played()` |
| `GET /me/following` | `current_user_followed_artists` | `followed_artists()` |
| `GET /search` | `search` | `search(q, type)` (reduced limits in dev mode) |
| `GET /tracks/{id}` | `track` | `track(id)` |
| `GET /artists/{id}` | `artist` | `artist(id)` |
| `GET /albums/{id}` | `album` | `album(id)` |
| `GET /albums/{id}/tracks` | `album_tracks` | `album_tracks(id)` |
| `GET /artists/{id}/albums` | `artist_albums` | `artist_albums(id)` |

Also available (not wrapped yet, add to `SpotifyClient` when needed):
playlist create/edit (`POST /me/playlists`, `PUT /playlists/{id}`), unified
library save/remove (`PUT|DELETE /me/library`, URIs not IDs — spotipy ≥2.26),
player control (`/me/player/*`).

## Blocked — calling these raises `DeprecatedEndpointError`

| Endpoint | Why | Since |
|----------|-----|-------|
| `/audio-features`, `/audio-analysis` | No audio-feature vectors for new apps | Nov 2024 |
| `/recommendations` (+ genre seeds) | Spotify recommender unavailable | Nov 2024 |
| `/artists/{id}/related-artists` | deprecated | Nov 2024 |
| `/browse/featured-playlists`, category playlists | deprecated | Nov 2024 |
| Bulk `/tracks?ids=`, `/artists?ids=`, `/albums?ids=` | removed from dev mode — loop single-item lookups | Feb 2026 |
| `/browse/*` (categories, new releases), `/markets` | removed from dev mode | Feb 2026 |
| `/users/{id}`, `/users/{id}/playlists` | public user data removed | Feb 2026 |

Full block list with messages: `BLOCKED_METHODS` in `spotify/src/client.py`.

## Consequences for the recommender project

- **Observed 2026-09-08 (smoke test): dev-mode responses are slimmed beyond
  the docs.** Artist objects carry no `genres`, `popularity`, or `followers`;
  track objects carry no `popularity`. Artist fields actually returned:
  `external_urls, href, id, images, name, type, uri`.
- No audio features or Spotify recommendations → surviving content signals are
  only **duration, explicit flag, release date, album type/metadata** plus the
  user's own listening history. Genre/popularity must come from external data.
- Search relevance also appears degraded in dev mode (top "artist" hit for
  "Kendrick Lamar" was Kanye West).
- **Playlist items renamed** `track` → `item` in `/playlists/{id}/items`
  responses (Feb 2026); use `client.unwrap_item()` to normalize.
- **Non-owned playlists 403**: `/me/playlists` lists followed playlists, but
  fetching items of playlists you don't own is Forbidden in dev mode.
- No public user/playlist data → no collaborative signals from the API;
  external datasets (e.g., Million Playlist Dataset) would fill that gap.
- ≤5 authorized users → any user study is tiny unless we get extended quota
  (which since May 2025 effectively requires a large MAU count — not us).

## Enrichment APIs (`spotify/src/enrich.py`)

Fill the gap the dev-mode API left (no genres/popularity/audio features):

| API | Gives us | Limits | Our client |
|-----|----------|--------|------------|
| GetSongBPM (`api.getsong.co`) | tempo, key, time sig, danceability, acousticness, artist genres, mbid | 3,000 req/h; **visible backlink to getsongbpm.com required** | `GetSongBPM.lookup_track(artist, title)` |
| Last.fm (`ws.audioscrobbler.com`) | weighted crowd tags per track/artist | ~5 req/s | `LastFM.track_tags(artist, title)` |

Both are (artist, title) lookups — no Spotify-id join. `enrich_track()` merges
the two into one feature dict. Keys go in `spotify/.env` (see `.env.example`).

## Sources

- https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api
- https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security
- https://developer.spotify.com/documentation/web-api/references/changes/february-2026
- https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- spotipy 2.26.0 changelog (unified `/me/library` support, deprecation warnings)
