"""Parse LLM song lists into clean, de-duplicated (title, artist) suggestions."""

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "spotify" / "src"))
from benchmark import track_key  # noqa: E402

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _load_json(text):
    """Accept plain JSON, fenced JSON, or JSON embedded in prose."""
    candidates = [text, *_FENCE.findall(text)]
    for opener, closer in ("{}", "[]"):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON song list in model output")


def track_keys(tracks):
    """Normalised keys for track records, one per credited artist (for seed exclusion)."""
    return {track_key(artist, t["title"]) for t in tracks for artist in t["artists"]}


def parse_songs(text, exclude=()):
    """Return ([{"title", "artist"}] in model order, drop counts); raises ValueError without JSON."""
    data = _load_json(text)
    items = data.get("songs", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("model output has no song list")
    songs, seen = [], set()
    stats = {"returned": len(items), "kept": 0, "malformed": 0, "duplicates": 0, "seed_repeats": 0}
    for item in items:
        title = item.get("title") if isinstance(item, dict) else None
        artist = item.get("artist") if isinstance(item, dict) else None
        if not (isinstance(title, str) and title.strip() and isinstance(artist, str) and artist.strip()):
            stats["malformed"] += 1
            continue
        key = track_key(artist, title)
        if key in exclude:
            stats["seed_repeats"] += 1
        elif key in seen:
            stats["duplicates"] += 1
        else:
            seen.add(key)
            songs.append({"title": title.strip(), "artist": artist.strip()})
    stats["kept"] = len(songs)
    return songs, stats
