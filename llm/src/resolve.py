"""Resolve (title, artist) suggestions to YouTube Music tracks by public search.

A match needs the same normalised title and an overlapping artist. Unmatched
suggestions return None (likely hallucinated or absent from the catalog). All
matching uploads are kept because references mix audio, video, and fan uploads.
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "spotify" / "src"))
sys.path.insert(0, str(ROOT / "youtube_music" / "src"))
from benchmark import track_key  # noqa: E402
from playlists import clean_tracks  # noqa: E402

RESOLVE_VERSION = 3  # bump when matching changes so cached results are not reused


def _alnum(text):
    """Compare on letters/digits only: catalogs vary ':' vs ',' and similar punctuation."""
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _title(text):
    return _alnum(track_key("", text)[1])  # feat./version noise stripped


def _titles(title):
    """Normalised title forms; video uploads often read 'Artist - Title (Official Video)'."""
    forms = {_title(title)}
    if " - " in title:
        forms.add(_title(title.split(" - ", 1)[1]))
    return forms


def _exact(title):
    return _alnum(track_key(title, "")[0])  # normalised but not version-stripped


def _artists_overlap(track_artists, artist):
    """Whole-name containment, else matching surnames (e.g. 'Fryderyk' vs 'Frédéric' Chopin).

    Only called once titles already match, which keeps the surname fallback safe.
    """
    wanted = _alnum(track_key(artist, "")[0])
    for name in track_artists:
        have = _alnum(track_key(name, "")[0])
        if have and wanted and (re.search(rf"\b{re.escape(have)}\b", wanted)
                                or re.search(rf"\b{re.escape(wanted)}\b", have)
                                or (len(have.split()) > 1 and len(wanted.split()) > 1
                                    and have.split()[-1] == wanted.split()[-1])):
            return True
    return False


def matches(track, title, artist):
    return bool(_titles(track["title"]) & _titles(title)) and _artists_overlap(track["artists"], artist)


def resolve_song(client, title, artist, cache, limit=10):
    """First matching song (songs search, then videos) plus alt_video_ids, or None; cached by query."""
    query = f"{title} {artist}"
    key = f"v{RESOLVE_VERSION}|{query}"
    if key in cache:
        return cache[key]
    hit = None
    for kind in ("songs", "videos"):
        found = [t for t in clean_tracks(client.search(query, filter=kind, limit=limit), max_duration_seconds=0)
                 if matches(t, title, artist)]
        if found:  # prefer exact titles over "(Live)"/"(Reimagined)" variants; stable otherwise
            found.sort(key=lambda t: _exact(t["title"]) != _exact(title))
            hit = {**found[0], "alt_video_ids": [t["video_id"] for t in found[1:]], "search_filter": kind}
            break
    cache[key] = hit
    return hit
