"""Public playlist collection and reproducible seed-only continuation examples.

Song identity currently means exact YouTube video ID; alternate recordings and
uploads remain distinct. Hidden references must never be sent to a recommender.
"""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import random
import re
import time
from urllib.parse import parse_qs, urlparse

import requests
from ytmusicapi import YTMusic


class TimeoutSession(requests.Session):
    """Bound network waits without retrying playlist writes."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().request(method, url, **kwargs)


def make_client(auth=None):
    """Public reads need no auth; account operations use browser headers only.

    OAuth issuance succeeds, but the Music backend rejects its bearer tokens
    with HTTP 400 in our live test (upstream ytmusicapi issue #813).
    """
    if auth is not None and not Path(auth).is_file():
        raise FileNotFoundError("Credential file not found; run the setup_auth.py script first.")
    if auth is not None:
        config = json.loads(Path(auth).read_text(encoding="utf-8"))
        if not isinstance(config, dict) or "access_token" in config:
            raise ValueError("Use browser authentication from setup_auth.py, not OAuth tokens.")
    return YTMusic(auth=str(auth) if auth else None, requests_session=TimeoutSession())


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    """Checkpoint locally; keep experiments under the gitignored data directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def playlist_id(value):
    """Accept playlist URLs, search browse IDs, or plain playlist IDs."""
    value = value.strip()
    if "://" in value:
        value = parse_qs(urlparse(value).query).get("list", [""])[0]
    if value.startswith("VL"):
        value = value[2:]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Provide a playlist ID or a URL containing ?list=...")
    return value


def clean_tracks(tracks, max_duration_seconds=900):
    """Keep unique song entries; exclude long mixes with a configurable length cap.

    The pilot cap is 15 minutes; 0 disables it. This is a compilation heuristic,
    not a guarantee that each entry is a canonical recording. Unknown lengths
    remain eligible and are preserved as null for later review.
    """
    cleaned, seen = [], set()
    for entry in tracks:
        if not isinstance(entry, dict):
            continue
        video_id = entry.get("videoId")
        artists = [a["name"] for a in (entry.get("artists") or []) if a.get("name")]
        if not video_id or not entry.get("title") or not artists or entry.get("isAvailable") is False:
            continue
        if video_id in seen:
            continue
        duration = entry.get("duration_seconds")
        if duration is None:
            text = entry.get("duration") or ""
            if re.fullmatch(r"\d+(?::\d{1,2}){1,2}", text):
                duration = 0
                for part in text.split(":"):
                    duration = duration * 60 + int(part)
        if max_duration_seconds and duration is not None and duration > max_duration_seconds:
            continue
        seen.add(video_id)
        cleaned.append({
            "video_id": video_id,
            "title": entry["title"],
            "artists": artists,
            "album": entry.get("album"),
            "duration_seconds": duration,
            "duration": entry.get("duration"),
            "is_explicit": entry.get("isExplicit"),
            "video_type": entry.get("videoType"),
        })
    return cleaned


def prepare_partial(source, seed_count=5, random_seed=42, max_duration_seconds=900):
    """Sample seeds deterministically, retaining source order and hidden positives."""
    tracks = clean_tracks(source.get("tracks", []), max_duration_seconds)
    if not 0 < seed_count < len(tracks):
        raise ValueError(f"Need more than {seed_count} usable unique songs; found {len(tracks)}.")
    indices = set(random.Random(random_seed).sample(range(len(tracks)), seed_count))
    return {
        "schema_version": 1,
        "source_playlist_id": playlist_id(source["id"]),
        "source_title": source.get("title"),
        "source_description": source.get("description"),
        "selection": {"method": "random_sample", "seed_count": seed_count, "random_seed": random_seed},
        "identity_policy": "exact_video_id",
        "track_filter": {"max_duration_seconds": max_duration_seconds},
        "seed_tracks": [t for i, t in enumerate(tracks) if i in indices],
        "held_out_tracks": [t for i, t in enumerate(tracks) if i not in indices],
        "raw_track_count": len(source.get("tracks", [])),
        "usable_unique_track_count": len(tracks),
    }


def create_seed_playlist(client, example, title):
    """Create a private copy containing seeds only, then verify the exact contents.

    The created ID is saved on the example before verification, for recovery if
    the follow-up read fails. Never retry creation automatically after an error.
    """
    if example.get("created_playlist_id"):
        raise ValueError("This example already has a created playlist; reuse its ID.")
    ids = [t["video_id"] for t in example["seed_tracks"]]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Seeds must be nonempty and unique.")
    created = client.create_playlist(title=title, description="", privacy_status="PRIVATE", video_ids=ids)
    if not isinstance(created, str) or not created:
        raise RuntimeError("Playlist creation did not return an ID; check account authentication.")
    example["created_playlist_id"] = created
    example["creation_verified"] = False
    verify_seed_playlist(client, example)
    return created


def verify_seed_playlist(client, example):
    """Recheck a copy; allow brief propagation delay without retrying writes."""
    created = example["created_playlist_id"]
    example["creation_verified"] = False
    ids = [t["video_id"] for t in example["seed_tracks"]]
    for attempt in range(4):
        try:
            actual = client.get_playlist(created, limit=None)
            break
        except KeyError as exc:
            # Newly created playlists can temporarily return no contents renderer.
            if "contents" not in str(exc) or attempt == 3:
                raise
            time.sleep(2 ** attempt)
    actual_ids = [t.get("videoId") for t in actual.get("tracks", [])]
    if Counter(actual_ids) != Counter(ids):
        raise RuntimeError(f"Created playlist {created} contents do not match the selected seeds.")
    example["creation_verified"] = True


def get_suggestions(client, value, count=5, max_duration_seconds=900):
    """Keep platform order, exclude existing songs, and report any shortfall."""
    if count < 1:
        raise ValueError("Suggestion count must be positive.")
    value = playlist_id(value)
    raw = client.get_playlist(value, limit=None, suggestions_limit=count + 7)
    seeds = {t.get("videoId") for t in raw.get("tracks", [])}
    suggestions = [t for t in clean_tracks(raw.get("suggestions", []), max_duration_seconds) if t["video_id"] not in seeds]
    return {
        "schema_version": 1,
        "collected_at": timestamp(),
        "playlist_id": value,
        "owned_by_authenticated_user": raw.get("owned"),
        "requested_count": count,
        "track_filter": {"max_duration_seconds": max_duration_seconds},
        "suggested_tracks": suggestions[:count],
        "shortfall": max(0, count - len(suggestions)),
        "raw": raw,
    }
