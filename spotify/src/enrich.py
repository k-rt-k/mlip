"""External enrichment APIs replacing what Spotify's dev-mode API dropped.

- GetSongBPM: tempo/key/danceability/acousticness + artist genres + mbid.
  Free tier requires a visible backlink to getsongbpm.com. 3,000 req/hour.
- Last.fm: weighted crowd tags per track/artist. ~5 req/sec.

Keys live in spotify/.env (GETSONGBPM_API_KEY, LASTFM_API_KEY).
Both clients throttle themselves; lookups are by (artist, title), not id.
"""

import os
import time

import requests
from dotenv import load_dotenv

from auth import ENV_PATH


def _require_env(name):
    load_dotenv(ENV_PATH)
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} not set — add it to {ENV_PATH}")
    return value


class _ThrottledAPI:
    """Shared GET-with-rate-limit base for the enrichment clients."""

    def __init__(self, min_interval):
        self._min_interval = min_interval
        self._last_call = 0.0

    def _get(self, url, params):
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()


class GetSongBPM(_ThrottledAPI):
    BASE = "https://api.getsong.co"

    def __init__(self, api_key=None, min_interval=1.3):  # 3,000/hour ceiling
        super().__init__(min_interval)
        self._key = api_key or _require_env("GETSONGBPM_API_KEY")

    def _call(self, path, **params):
        params["api_key"] = self._key
        return self._get(f"{self.BASE}{path}", params=params)

    def search(self, artist, title):
        """Best-first search hits, [] when the API reports no result."""
        result = self._call("/search/", type="both", lookup=f"song:{title} artist:{artist}")
        hits = result.get("search")
        return hits if isinstance(hits, list) else []

    def song(self, song_id):
        return self._call("/song/", id=song_id).get("song", {})

    def lookup_track(self, artist, title):
        """Normalized feature dict for the top search hit, or None."""
        hits = self.search(artist, title)
        if not hits:
            return None
        detail = self.song(hits[0].get("song_id") or hits[0].get("id"))
        artist_obj = detail.get("artist") or hits[0].get("artist") or {}
        tempo = detail.get("tempo") or hits[0].get("tempo")
        return {
            "source_id": detail.get("id"),
            "tempo": float(tempo) if tempo else None,
            "time_sig": detail.get("time_sig"),
            "key": detail.get("key_of"),
            "open_key": detail.get("open_key"),
            "danceability": detail.get("danceability"),
            "acousticness": detail.get("acousticness"),
            "genres": artist_obj.get("genres") or [],
            "mbid": artist_obj.get("mbid"),
        }


class LastFM(_ThrottledAPI):
    BASE = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key=None, min_interval=0.25):
        super().__init__(min_interval)
        self._key = api_key or _require_env("LASTFM_API_KEY")

    def _call(self, method, **params):
        params.update(method=method, api_key=self._key, format="json", autocorrect=1)
        return self._get(self.BASE, params=params)

    def _tags(self, method, **params):
        result = self._call(method, **params)
        tags = result.get("toptags", {}).get("tag", [])
        return [(t["name"], int(t.get("count", 0))) for t in tags]

    def track_tags(self, artist, title):
        """Weighted crowd tags for a track, heaviest first. [] if unknown."""
        return self._tags("track.gettoptags", artist=artist, track=title)

    def artist_tags(self, artist):
        return self._tags("artist.gettoptags", artist=artist)


def enrich_track(artist, title, gsb, lastfm):
    """Merge both sources into one feature dict; missing sources yield Nones."""
    features = gsb.lookup_track(artist, title) or {
        "tempo": None, "key": None, "danceability": None,
        "acousticness": None, "genres": [], "mbid": None,
    }
    features["tags"] = lastfm.track_tags(artist, title)
    return features
