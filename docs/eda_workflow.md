# Spotify EDA Workflow — Feasibility Check

Goal: decide whether the Spotify recommender project is feasible given the
2024–26 API restrictions (see `docs/spotify_api.md`), as input to the
spotify-vs-peer topic decision.

Status: **steps 1–2 complete** (2026-09-08); next: discuss which API features
to target, then steps 3–4.

## Step 2 results (personal-data inventory, 2026-09-08, user `kartik`)

Pulled via `spotify/scripts/inventory.py --user kartik`; raw JSON cached in
`data/spotify/kartik/` (per-user dirs since 2026-09-13; all numbers in this
doc are for `kartik` unless stated).

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

   **First result (2026-09-08, `spotify/scripts/kaggle_coverage.py`)**: the Kaggle
   114k dump (HF mirror `maharshipandya/spotify-tracks-dataset`; 89,741 unique
   ids, genre-stratified ~1k/genre, frozen ~2022) covers only **162/2,152
   (7.5%)** of our tracks by id — best on playlists (21.5%) and saved (14.8%),
   worst on recent (6.1%). An exact-id join on this dump is not viable.
   Candidate next moves: (a) the 1.2M-track Kaggle dump (needs Kaggle API
   token), (b) fuzzy (artist, title) matching — ids differ across re-releases,
   so id-join undercounts, (c) build on collaborative/external-genre signals
   instead of audio features.

   **FULL-HISTORY results (2026-09-09, `spotify/scripts/enrich_coverage.py
   all` — every one of the 2,152 pulled tracks enriched; feature matrix in
   `data/spotify/enrich_sample.json`):**
   - GetSongBPM tempo/key/danceability: **41–42%**; artist genres 38%.
   - Last.fm track tags: **38%**; **listeners/playcount: 2,149/2,152 (100%)**.
   - By release date (1,164 pre-2020 / 988 from 2020s): audio features
     **70% vs 8%**, genres 64% vs 8%, tags 40% vs 36%, listeners 100% both.

   Earlier 100-track seeded sample (same script, drove the miss analysis):
   - GetSongBPM track features 35%; split by release date:
     **pre-2020: 67% (28/42) — 2020s: 7%** (4/55).
   - Last.fm track tags: **41%**; either source at track level: **53%**.
   - **Last.fm track existence: 99/100** (`track.getInfo`; the one miss is a
     feat.-suffix title) — and getInfo returns per-track **listeners +
     playcount**, a live popularity proxy for the field Spotify dropped.
   - **Last.fm artist-level tags: 100% (50/50 sampled artists).**

   **Miss-resolution analysis (per-case probing of uncovered tracks):**
   - **GetSongBPM's recency cutoff is a real catalog gap** — no 2020s
     albums on their site either (user-verified by browsing). No query
     reformulation can recover those 51/55 misses.
   - **Their search is also broken against their own catalog**: entries are
     stored with typographic punctuation ("Ex‐Factor", U+2010) and search
     requires byte-exact matches; honorifics in artist names ("Ms. Lauryn
     Hill") also kill matches. Fixed in `GetSongBPM._search_variants()`
     (honorific-strip, ascii-fold, fancy-punct, a.k.a-dot query pairs) —
     recovered the famous pre-2020 misses (Ex-Factor, Same Ol' Mistakes,
     Sherane) but is worth ~3% in aggregate. Further strategies (canonical
     artist name via artist-search, title-only + fuzzy artist match)
     recovered zero more; the /artist/ endpoint has no song list. All 15
     remaining pre-2020 misses were then checked against their *website*
     via domain-restricted web search: only Sherane existed (recovered);
     the other 14 are deep cuts / soundtrack / non-album tracks genuinely
     absent — **~67% is the verified pre-2020 ceiling**.
   - Last.fm "misses" are **not coverage gaps**: every probed track exists
     (e.g. We Cry Together, 658k listeners) but recent releases carry zero
     crowd tags. Tag coverage ≈ tagged-ness, hence artist-level tags being
     the reliable genre signal.
   - GetSongBPM also enforces burst limits (429s) beyond the hourly quota;
     the client backs off 30s on 429.
   - Untried exact-match bridge: every dev-mode Spotify track carries an
     **ISRC** (200/200 checked) → MusicBrainz `/ws/2/isrc/` → MBID →
     Last.fm mbid lookups + AcousticBrainz (frozen 2022) features.

   **Raw audio (2026-09-12):** Spotify's own 30s `preview_url` is gone for
   new apps (Nov 2024; 0/1,937 of our tracks carry one). But **Deezer's
   public API resolves by ISRC with no key**
   (`api.deezer.com/track/isrc:{ISRC}`) and returns a **30.0s, 128 kbps MP3
   preview** (snippet, not the full track). On the 100-track seeded sample:
   **92/97 (95%) — pre-2020: 90%, 2020s: 98%**; 3 tracks had no ISRC on
   Spotify's side. Misses are takedowns (`readable: false`: Kanye
   "Stronger", a Cocteau Twins remaster) or not-on-Deezer (Daft Punk
   "Instant Crush", Mac Miller "Shangri-La"). This is exact-match
   (no name normalization) and era-independent, so computing our own
   tempo/key/energy from the previews (librosa/essentia) would close the
   GetSongBPM 2020s gap. Not yet built — decision pending.

   **Takeaway:** genre/style signal is fully recoverable at artist level;
   per-track audio features exist for only ~⅓ of the history. A recommender
   should lean on artist-level content + the user's interaction structure,
   treating track-level audio features as optional icing.
5. **Feasibility verdict** — short writeup here in `docs/` with a go/no-go
   recommendation and the pivots available if no-go.

Steps 2–4 will be refined after we discuss which API features to build around.

## Related docs

- `docs/babel_embedding.md` — running the sharded embedding pipeline on Babel (storage layout, node logging, rate-limit and preemption constraints).
- `docs/mpd_dataset.md` — Million Playlist Dataset: access status, schema, and why it is the natural source of held-out evaluation labels.

## Code pointers

- Auth: `spotify/src/auth.py` (PKCE with forced consent dialog, scopes)
- Multi-user paths + identity guard: `spotify/src/users.py`
- API surface: `spotify/src/client.py` (`SpotifyClient`, `BLOCKED_METHODS`)
- Smoke test: `spotify/scripts/smoke_test.py`
- Tests: `spotify/tests/test_client.py`

## Audio embeddings from previews (2026-09-23)

Replaces the deprecated Spotify audio features with learned embeddings over the
Deezer 30s previews. Three models behind one interface in
`spotify/src/embeddings.py`; previews in `spotify/src/previews.py`.

    python spotify/scripts/embed.py --user <slug> --model clap|muq|clamp3 [--limit N]

Previews land in `data/spotify/previews/` and embeddings in
`data/spotify/embeddings/<model>.npz` — both keyed by track id, so both are
shared across users. Resumable: reruns only fetch and embed what is missing.

### Availability

Google's **MuLan is not public** (HF 401; weights never released).
`OpenMuQ/MuQ-MuLan-large` is the open reproduction and is what `muq` loads.
CLAP and CLaMP 3 are both downloadable.

| key | model | dim | params | load | marginal cost/clip (this Mac) |
|-----|-------|-----|--------|------|------------------------------|
| `clap` | `laion/larger_clap_music_and_speech` | 512 | ~90M audio tower | 7 s | 0.41 s (3 windows) / 0.15 s (1 window) |
| `muq` | `OpenMuQ/MuQ-MuLan-large` | 512 | 663M | 12 s | ~2.4 s |
| `clamp3` | CLaMP 3 SAAS | 768 | MERT-95M + encoder | in-call | 1.2 s + **16 s fixed per call** |

### Where the time actually goes (profiled 2026-09-23, 20 clips)

Per clip, CLAP: **0.16 s mp3 decode + 0.06 s mel feature-extract + 0.35 s
forward** (3 windows, CPU; mps only 0.36 vs 0.41 — Apple mps barely helps here).

- **CLAP is not intrinsically slow.** 0.15 s/clip for one window; our
  deterministic 3-window average tripled it. A deliberate accuracy-for-speed
  trade, not overhead.
- **MuQ is slow because it is big**: 663M params (~7x CLAP's audio tower) run
  over 720k *raw* samples (30 s @ 24 kHz), where CLAP sees a compressed mel
  spectrogram of 10 s.
- **CLaMP 3 is mostly fixed cost**: 16 s per invocation (loads MERT ~400 MB and
  CLaMP3 SAAS ~1 GB from disk, spawns a subprocess, stages temp files) and only
  1.2 s/clip marginal. Earlier "70 s for 20 clips" was overhead, not throughput
  — always pass every clip in one call.
- **On real GPUs the forward collapses and mp3 decode (~0.15 s/clip, pure CPU)
  becomes the wall.** Hence `decode_workers` (threaded decode) in the base class.
  Device order is cuda > mps > cpu, and a cpu fallback now emits a warning —
  an unnoticed cpu run is the difference between minutes and days.

### Rate limits

- **Models: none.** Weights download once from HuggingFace (~4 GB cache) and
  then run locally and offline. Batch size is a memory/speed tradeoff only.
- **Deezer: 50 requests / 5 s per IP**, unauthenticated, no key. We pace at
  5 req/s (`previews.MIN_INTERVAL`) and retry on their in-body quota error
  (code 4, not HTTP 429). The MP3 itself comes from their CDN and does not
  count against the API quota.

### What we have and have not established

Coverage is measured: **Deezer resolved 20/20 and 92/97 (95%)** of sampled
tracks, 2020s releases included (see the gap-analysis section above).

Quality is **not** established. The earlier comparison was an informal smell
test: five pairs *we* nominated as similar, checked for where one ranked among
the other's 19 neighbours on a 20-clip sample. Self-chosen labels, n=5 — it is
not a retrieval benchmark and should not be quoted as one. What it suggested,
weakly: CLaMP 3 ranked those pairs most consistently (1-2 of 19), CLAP tagged
short text prompts best and is ~4x faster, and all three placed two Japanese
guitar bands (my dead girlfriend / the cabs) as near neighbours — a similarity
no metadata source we tried could express. **A real evaluation needs held-out
labels we did not pick**, e.g. same-playlist co-occurrence from the Million
Playlist Dataset, or Last.fm tag overlap as a proxy for ground truth.

### Gotchas found

- **CLAP is non-deterministic out of the box**: its feature extractor defaults
  to `truncation="rand_trunc"`, taking a *random* 10s window of each clip
  (cosine 0.969-0.982 between runs of the same file). `Clap` in
  `embeddings.py` instead windows the clip itself and averages — deterministic,
  and uses all 30 s.
- **CLaMP 3 needs isolation**: it pins transformers 4.40 / numpy<2, which would
  break the other two. `spotify/scripts/setup_clamp3.sh` creates its venv and
  clone; the adapter drives it by subprocess. Its CLI also shells out to a bare
  `python`, so the venv must lead PATH (handled in `Clamp3._run`).
- `spotify/scripts/coverage.py` was renamed to `kaggle_coverage.py`: on
  `sys.path` it shadowed the real `coverage` package, which broke numba (and so
  librosa) for any script importing it.
