"""External enrichment APIs replacing what Spotify's dev-mode API dropped.

- GetSongBPM: tempo/key/danceability/acousticness + artist genres + mbid.
  Free tier requires a visible backlink to getsongbpm.com. 3,000 req/hour.
- Last.fm: weighted crowd tags per track/artist. ~5 req/sec.

Keys live in spotify/.env (GETSONGBPM_API_KEY, LASTFM_API_KEY).
Both clients throttle themselves; lookups are by (artist, title), not id.
"""

import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

from auth import ENV_PATH

_TITLE_NOISE = re.compile(
    r"\s*[(\[][^)\]]*[)\]]"      # any (...) or [...] segment
    r"|\s+-\s+.*$",              # " - Remastered 2014", " - Live" suffixes
)


def clean_title(title):
    """Strip feat./remaster/version noise that breaks name-based lookups."""
    cleaned = _TITLE_NOISE.sub("", title).strip()
    return cleaned or title  # never return empty (e.g. title was all brackets)


def ascii_fold(text):
    """Fold curly quotes and diacritics to ASCII (catalogs index the plain form)."""
    text = text.replace("’", "'").replace("‘", "'")
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return folded or text


def title_variants(title):
    """Lookup candidates in order: raw, noise-stripped, ascii-folded."""
    variants = [title, clean_title(title), ascii_fold(clean_title(title))]
    return list(dict.fromkeys(variants))  # dedupe, keep order


_HONORIFIC = re.compile(r"^(ms|mr|mrs|dr)\.?\s+", re.IGNORECASE)


def fancy_punct(text):
    """ASCII -> typographic punctuation (GetSongBPM stores titles this way)."""
    return text.replace("-", "‐").replace("'", "’")


_AKA = re.compile(r"\b([aA]\.[kK]\.[aA])(?!\.)")


def dot_aka(text):
    """Normalize 'a.k.a' -> 'a.k.a.' (catalogs punctuate the abbreviation)."""
    return _AKA.sub(r"\1.", text)


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

    def _get(self, url, params, attempts=3):
        for attempt in range(attempts):
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                response = requests.get(url, params=params, timeout=20)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                # 4xx won't heal on retry; timeouts, 5xx and 429s often do.
                status = getattr(getattr(e, "response", None), "status_code", None)
                if (status and status < 500 and status != 429) or attempt == attempts - 1:
                    raise
                time.sleep(30 if status == 429 else 2 ** attempt)


class GetSongBPM(_ThrottledAPI):
    BASE = "https://api.getsong.co"

    def __init__(self, api_key=None, min_interval=1.2):  # 3,000/hour ceiling
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

    @staticmethod
    def _search_variants(artist, title):
        """Bounded (artist, title) query pairs — their search does not
        normalize unicode punctuation or honorifics in either direction."""
        base = clean_title(title)
        bare = _HONORIFIC.sub("", artist)
        pairs = [
            (artist, title),
            (ascii_fold(bare), dot_aka(ascii_fold(base))),
            (bare, fancy_punct(ascii_fold(base))),
        ]
        return list(dict.fromkeys(pairs))

    def lookup_track(self, artist, title):
        """Normalized feature dict for the best search hit, or None."""
        hits = None
        for artist_q, title_q in self._search_variants(artist, title):
            hits = self.search(artist_q, title_q)
            if hits:
                break
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

    def similar_tracks(self, artist, title, limit=50):
        """[(artist, title, match 0-1)] from global listening data; [] if unknown.

        Independent of any user profile - it is Last.fm's collaborative
        filtering over all scrobbles.
        """
        for variant in title_variants(title):
            result = self._call("track.getsimilar", artist=artist, track=variant,
                                limit=limit)
            tracks = result.get("similartracks", {}).get("track", [])
            if tracks:
                return [(s["artist"]["name"], s["name"], float(s.get("match", 0)))
                        for s in tracks]
        return []

    def track_info(self, artist, title):
        """Track metadata (listeners, playcount, …) or None. Tries title
        variants — feat. suffixes break getInfo despite autocorrect."""
        for variant in title_variants(title):
            track = self._call("track.getinfo", artist=artist, track=variant).get("track")
            if track:
                return track
        return None


def enrich_track(artist, title, gsb, lastfm):
    """Merge both sources into one feature dict; missing sources yield Nones.

    GetSongBPM tries its own search variants internally; Last.fm gets title
    variants here (its autocorrect handles artists, but not title noise).
    The two APIs are independent, so their call chains run concurrently.
    """
    def _lastfm_part():
        tags = []
        for variant in title_variants(title):
            tags = lastfm.track_tags(artist, variant)
            if tags:
                break
        return tags, lastfm.track_info(artist, title)

    with ThreadPoolExecutor(max_workers=2) as pool:
        features_future = pool.submit(gsb.lookup_track, artist, title)
        tags, info = pool.submit(_lastfm_part).result()
        features = features_future.result()

    features = features or {
        "tempo": None, "key": None, "danceability": None,
        "acousticness": None, "genres": [], "mbid": None,
    }
    features["tags"] = tags
    features["listeners"] = int(info["listeners"]) if info else None
    features["playcount"] = int(info.get("playcount", 0)) if info else None
    return features
