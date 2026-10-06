"""Public song-radio candidates; no hidden answers enter pool construction."""

from collections import Counter
import time

from youtube_music.src.playlists import clean_tracks


def radio_candidates(client, seed_ids, per_seed=50, delay=1.0):
    """Collect one paced radio per unique seed, preserving per-seed errors."""
    if per_seed < 1 or delay < 0:
        raise ValueError("per_seed must be positive and delay nonnegative")
    radios, errors = {}, []
    for index, seed in enumerate(dict.fromkeys(seed_ids)):
        if index:
            time.sleep(delay)
        try:
            raw = client.get_watch_playlist(videoId=seed, radio=True, limit=per_seed)
            radios[seed] = clean_tracks(raw.get("tracks", []))[:per_seed]
            if not radios[seed]:
                errors.append({"seed_id": seed, "error": "empty_radio"})
        except Exception as exc:
            # Exception messages may contain request headers; retain only their type.
            radios[seed] = []
            errors.append({"seed_id": seed, "error": type(exc).__name__})
    return {"radios": radios, "errors": errors}


def build_pool(seeds, radio, cooccurrence, max_size=60):
    """Rank the union by radio seed coverage, first (seed, position), then ID.

    Co-occurrence entries are normalized track dictionaries from the reference
    corpus. Their incoming order does not affect ties.
    """
    if max_size < 1:
        raise ValueError("max_size must be positive")
    excluded = {t["video_id"] if isinstance(t, dict) else t for t in seeds}
    counts, first, tracks = Counter(), {}, {}
    for seed_position, entries in enumerate(radio.values()):
        seen = set()
        for position, track in enumerate(entries):
            vid = track["video_id"]
            if vid in excluded or vid in seen:
                continue
            seen.add(vid)
            counts[vid] += 1
            first.setdefault(vid, (seed_position, position))
            tracks.setdefault(vid, track)
    for track in cooccurrence:
        if track["video_id"] not in excluded:
            tracks.setdefault(track["video_id"], track)
    ordered = sorted(tracks, key=lambda vid: (-counts[vid], first.get(vid, (float("inf"), 0)), vid))
    return [dict(tracks[vid], radio_seed_count=counts[vid]) for vid in ordered[:max_size]]


def load_pools(path, k=5):
    """Load candidate-only records and reject short, duplicate, or seed-leaking pools."""
    import json
    from pathlib import Path

    examples = json.loads(Path(path).read_text(encoding="utf-8"))["examples"]
    if not isinstance(examples, dict) or not examples:
        raise ValueError("Expected nonempty pools keyed by example ID")
    for eid, ex in examples.items():
        ids = [t["video_id"] for t in ex["candidates"]]
        seeds = {t["video_id"] for t in ex["seed_tracks"]}
        if len(ids) < k or len(ids) != len(set(ids)) or seeds.intersection(ids):
            raise ValueError(f"Example {eid}: pool is short, duplicated, or contains seeds")
        if any(not isinstance(vid, str) or not vid for vid in ids):
            raise ValueError(f"Example {eid}: invalid video ID")
        if ex["seed_count"] != len(ex["seed_tracks"]):
            raise ValueError(f"Example {eid}: seed count does not match seeds")
    return examples
