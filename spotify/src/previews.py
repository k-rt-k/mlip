"""Deezer 30s preview downloads, keyed by the ISRC every Spotify track carries.

Spotify removed `preview_url` for new apps (Nov 2024). Deezer's public API
resolves by ISRC with no key and covers ~95% of our tracks, recent releases
included, so it is an exact-match join rather than name matching. The clips
are the input to `embeddings.py`.
"""

import json
import time
from pathlib import Path

import requests

from client import unwrap_item
from users import DATA_ROOT, data_dir

ISRC_URL = "https://api.deezer.com/track/isrc:{isrc}"

# Deezer's public API allows 50 requests / 5s per IP (no key, no signup).
# The MP3 itself is served from their CDN and does not count against that.
MIN_INTERVAL = 0.2  # 5 req/s — half the documented ceiling
QUOTA_ERROR = 4     # Deezer reports throttling in the body, not as HTTP 429

# Previews are per-track, not per-user, so all users share one directory.
PREVIEW_DIR = DATA_ROOT / "previews"

_COLLECTIONS = ("top_tracks_short_term", "top_tracks_medium_term",
                "top_tracks_long_term", "saved_tracks", "recently_played")


def track_isrcs(user):
    """id -> {artist, title, isrc, year} for every ISRC-bearing cached track."""
    src = data_dir(user)
    entries = []
    for name in _COLLECTIONS:
        path = src / f"{name}.json"
        if path.exists():
            entries += json.loads(path.read_text())
    playlists = src / "playlist_tracks.json"
    if playlists.exists():
        entries += [e for v in json.loads(playlists.read_text()).values() for e in v]

    tracks = {}
    for entry in entries:
        t = unwrap_item(entry)
        if t and t.get("id") and t.get("external_ids", {}).get("isrc"):
            tracks[t["id"]] = {
                "artist": t["artists"][0]["name"],
                "title": t["name"],
                "isrc": t["external_ids"]["isrc"],
                "year": (t.get("album", {}).get("release_date") or "")[:4],
            }
    return tracks


def preview_url(isrc, session=requests, retries=3):
    """Deezer preview MP3 url for an ISRC, or None when there is no audio.

    Deezer answers for withdrawn tracks too, with an empty preview field.
    Backs off and retries when it reports a quota error.
    """
    for attempt in range(retries):
        body = session.get(ISRC_URL.format(isrc=isrc), timeout=15).json()
        if body.get("error", {}).get("code") != QUOTA_ERROR:
            return body.get("preview") or None
        time.sleep(2 ** attempt)
    return None


def download_previews(tracks, out_dir=PREVIEW_DIR, pause=MIN_INTERVAL):
    """Fetch any missing previews into out_dir/<track_id>.mp3.

    Resumable: existing clips are kept, so reruns only fetch what is absent.
    Returns ({track_id: path}, [ids with no available audio]).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    have, unavailable = {}, []
    for tid, meta in tracks.items():
        dest = out_dir / f"{tid}.mp3"
        if dest.exists():
            have[tid] = dest
            continue
        url = preview_url(meta["isrc"], session)
        if not url:
            unavailable.append(tid)
            continue
        dest.write_bytes(session.get(url, timeout=30).content)
        have[tid] = dest
        time.sleep(pause)  # stay under the documented quota
    return have, unavailable
