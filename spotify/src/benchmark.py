"""Benchmark our playlist recommenders against Spotify's own suggestions.

Spotify's recommendations are unreachable through the API for our app, so they
are captured by hand in the Spotify app: copy a playlist into your library as
"seed: <name>", then add the songs Spotify suggests under that copy to
"recs: <name>". This module pairs those playlists, generates our own
recommendations for each seed, and scores them against Spotify's list.

Tracks are compared by a normalised (artist, title) key rather than Spotify
id: Last.fm returns names, and one recording can carry several Spotify ids.
"""

import json
import re
from collections import defaultdict

from enrich import ascii_fold, clean_title

_CAPTURE_NAME = re.compile(r"^\s*(seed|recs)\s*:\s*(.+?)\s*$", re.IGNORECASE)


def pair_playlists(playlists):
    """{name: {"seed": id, "recs": id or None}} from "seed:"/"recs:" playlists.

    Names match case-insensitively; a recs playlist without a seed is ignored.
    """
    found = defaultdict(dict)
    for playlist in playlists:
        match = _CAPTURE_NAME.match(playlist["name"])
        if match:
            kind, name = match.group(1).lower(), match.group(2).lower()
            found[name][kind] = playlist["id"]
    return {name: {"seed": ids["seed"], "recs": ids.get("recs")}
            for name, ids in sorted(found.items()) if "seed" in ids}


def _norm(text):
    return re.sub(r"\s+", " ", ascii_fold(text).lower()).strip()


def track_key(artist, title):
    """Normalised identity: primary artist + title without feat./version noise."""
    return _norm(artist), _norm(clean_title(title))


def recommend_similar(seed_tracks, similar, top_n=50, exclude_seed_artists=False):
    """Rank candidates by their summed similarity to every seed track.

    `seed_tracks` is [(artist, title)]; `similar(artist, title)` returns
    [(artist, title, score)], e.g. LastFM.similar_tracks. Summing favours
    candidates close to many seeds over ones close to a single outlier.
    Returns [(artist, title, score)], best first.
    """
    seed_keys = {track_key(a, t) for a, t in seed_tracks}
    seed_artists = {artist for artist, _ in seed_keys}
    scores, display = defaultdict(float), {}
    for artist, title in seed_tracks:
        for cand_artist, cand_title, score in similar(artist, title):
            key = track_key(cand_artist, cand_title)
            if key in seed_keys or (exclude_seed_artists and key[0] in seed_artists):
                continue
            scores[key] += score
            display.setdefault(key, (cand_artist, cand_title))
    ranked = sorted(scores, key=lambda k: (-scores[k], k))[:top_n]
    return [(*display[k], scores[k]) for k in ranked]


def evaluate(recommended, reference):
    """How much of Spotify's list (`reference`) our ranked list recovers.

    Track matches are strict, so artist_recall is reported too: whether we
    reached the right artists even when not the exact songs.
    """
    rec_keys = {track_key(r[0], r[1]) for r in recommended}
    ref_keys = {track_key(a, t) for a, t in reference}
    hits = len(rec_keys & ref_keys)
    ref_artists = {artist for artist, _ in ref_keys}
    rec_artists = {artist for artist, _ in rec_keys}
    return {
        "recommended": len(rec_keys),
        "reference": len(ref_keys),
        "hits": hits,
        "precision": hits / len(rec_keys) if rec_keys else 0.0,
        "recall": hits / len(ref_keys) if ref_keys else 0.0,
        "artist_recall": (len(rec_artists & ref_artists) / len(ref_artists)
                          if ref_artists else 0.0),
    }


class CachedSimilar:
    """Wraps a similar(artist, title) lookup with a JSON cache on disk."""

    def __init__(self, lookup, path):
        self._lookup, self._path = lookup, path
        self._cache = json.loads(path.read_text()) if path.exists() else {}

    def __call__(self, artist, title):
        key = f"{artist}\t{title}"
        if key not in self._cache:
            self._cache[key] = self._lookup(artist, title)
        return self._cache[key]

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._cache))
