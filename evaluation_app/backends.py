"""Use the project baseline runners' policies behind a shared online interface."""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import logging
import re
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from baselines.playlist_search import rank_songs, select_playlists
from llm.src import chat_client, parse, prompts, resolve
from spotify.src.deezer import fresh_preview
from youtube_music.src.playlists import clean_tracks, create_seed_playlist, get_suggestions, make_client

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
TOP_K = 5
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "deepseek/deepseek-v4-flash-0731"
LOG = logging.getLogger(__name__)


class BackendUnavailable(Exception):
    """The selected backend could not serve the request."""


def playable_track(track):
    """Pass the UI only the track metadata it needs."""
    video_id = track["video_id"]
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Invalid YouTube video ID")
    duration = track.get("duration_seconds")
    return {
        "video_id": video_id, "title": track["title"][:300],
        "artists": [artist[:160] for artist in track["artists"][:12]],
        "duration_seconds": int(duration) if duration is not None else None,
    }


def identity(track):
    return track.get("recording_key") or "yt:" + track["video_id"]


def eligible_tracks(tracks, exclusions):
    used_ids = {entry[0] for entry in exclusions}
    used_keys = {entry[1] for entry in exclusions}
    result = []
    for track in tracks:
        key = identity(track)
        if track["video_id"] not in used_ids and key not in used_keys:
            used_ids.add(track["video_id"])
            used_keys.add(key)
            result.append(track)
    return result


class Backends:
    def __init__(self, retrieval_url, llm_url=None, llm_model=None, llm_key=None, *, ytm_auth=None):
        self.retrieval_url = retrieval_url
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.llm_key = llm_key
        self.ytm_auth = ytm_auth

    def ready(self, arms):
        missing = []
        if "playlist_search" in arms and (self.ytm_auth is None or not self.ytm_auth.is_file()):
            missing.append("YouTube Music browser credentials")
        if "llm" in arms:
            if not (self.llm_url and self.llm_model):
                missing.append("LLM endpoint and model")
            elif self.llm_url == OPENROUTER_URL and not self.llm_key:
                missing.append("an OpenRouter API key")
        if "retrieval" in arms:
            try:
                response = requests.get(self.retrieval_url + "/health", timeout=3)
                response.raise_for_status()
                if not response.json().get("ready"):
                    missing.append("CPU retrieval service")
            except (requests.RequestException, ValueError):
                missing.append("CPU retrieval service")
        return missing

    def annotate(self, tracks):
        if not tracks:
            return []
        try:
            response = requests.post(self.retrieval_url + "/coverage", json={"tracks": tracks}, timeout=5)
            response.raise_for_status()
            matches = response.json()
        except (requests.RequestException, ValueError):
            matches = {}
        return [
            {**track, "seed_eligible": matches.get(track["video_id"], {}).get("seed_eligible"),
             "recording_key": matches.get(track["video_id"], {}).get("recording_key") or identity(track)}
            for track in tracks
        ]

    def search(self, query):
        # Both filters are public and expose tracks outside the embedded MPD catalog.
        client = make_client()
        results = []
        for category in ("songs", "videos"):
            results.extend(client.search(query, filter=category, limit=8)[:8])
        tracks = [playable_track(track) for track in clean_tracks(results, max_duration_seconds=0)
                  if VIDEO_ID.fullmatch(track["video_id"])]
        return self.annotate(tracks)

    @staticmethod
    def preview(track):
        key = identity(track)
        if not re.fullmatch(r"isrc:[A-Za-z0-9]{12}", key):
            return None
        url = fresh_preview(requests, key)
        if not url:
            return None
        parts = urlsplit(url)
        return url if parts.scheme == "https" and (parts.hostname or "").endswith(".dzcdn.net") else None

    def community_playlists(self, prompt):
        client = make_client()
        results = client.search(prompt, filter="community_playlists", limit=20)
        playlists = select_playlists(results[:20], set(), 5)
        tracks_by_playlist = [clean_tracks(client.get_playlist(pid, limit=100).get("tracks", [])[:100])
                              for pid in playlists]
        metadata = {track["video_id"]: track for tracks in tracks_by_playlist for track in tracks}
        return [playable_track(metadata[video_id]) for video_id, _ in rank_songs(tracks_by_playlist, 30)
                if VIDEO_ID.fullmatch(video_id)]

    def playlist_suggestions(self, seeds):
        """Get native suggestions from a temporary private copy of the seed songs."""
        if self.ytm_auth is None or not self.ytm_auth.is_file():
            raise BackendUnavailable("YouTube Music browser credentials are missing.")
        client = make_client(self.ytm_auth)
        snapshot = {"seed_tracks": seeds}
        title = f"Playlist Lab temporary {uuid4().hex[:12]}"
        try:
            playlist_id = create_seed_playlist(client, snapshot, title)
            response = get_suggestions(client, playlist_id, count=TOP_K * 3)
            if response["owned_by_authenticated_user"] is not True or response["raw"].get("privacy") != "PRIVATE":
                raise BackendUnavailable("Expected a private playlist owned by the study account.")
            return [playable_track(track) for track in response["suggested_tracks"]
                    if VIDEO_ID.fullmatch(track["video_id"])]
        finally:
            # Creation records the ID before verifying the contents, so failed reads can also clean up.
            if playlist_id := snapshot.get("created_playlist_id"):
                try:
                    result = client.delete_playlist(playlist_id)
                    if result != "STATUS_SUCCEEDED":
                        remaining = client.get_library_playlists(limit=None)
                        if any(item.get("playlistId") == playlist_id for item in remaining):
                            LOG.warning("Check cleanup of temporary YouTube Music playlist %s", playlist_id)
                except Exception:
                    LOG.warning("Could not confirm cleanup of temporary YouTube Music playlist %s", playlist_id)

    def llm_candidates(self, prompt, seeds):
        if not self.llm_model or not self.llm_url:
            raise BackendUnavailable
        if prompt:
            messages = prompts.prompt_only(prompt, 12)
            if seeds:
                listing = "\n".join(prompts.format_track(song) for song in seeds)
                messages[-1]["content"] += (
                    "\n\nThese songs are already in the playlist. Use them as context while "
                    "prioritizing the current request, and avoid repeating them:\n" + listing
                )
        else:
            messages = prompts.seeds_only(seeds, 12)
        headers = {"Authorization": f"Bearer {self.llm_key}"} if self.llm_key else {}
        options = None
        if self.llm_url == OPENROUTER_URL:
            options = {"provider": {"zdr": True, "data_collection": "deny", "require_parameters": True}}
            if self.llm_model == OPENROUTER_MODEL:
                options["reasoning"] = {"enabled": False}
        outcome = chat_client.complete(
            messages, self.llm_model, response_format=prompts.song_schema(), max_tokens=1200,
            attempts=1, endpoint=self.llm_url, headers=headers, timeout=45, extra=options,
        )
        songs, _ = parse.parse_songs(outcome["text"], exclude=parse.track_keys(seeds))
        return songs

    @staticmethod
    @lru_cache(maxsize=2048)
    def resolve_candidate(title, artist):
        match = resolve.resolve_song(make_client(), title, artist, {})
        return playable_track(match) if match and VIDEO_ID.fullmatch(match["video_id"]) else None

    def resolve_candidates(self, candidates, exclusions):
        """Resolve in small parallel batches while retaining original recommendation order."""
        tracks = []

        def resolve_one(candidate):
            try:
                track = self.resolve_candidate(candidate["title"], candidate["artist"])
            except requests.RequestException:
                return None
            if not track:
                return None
            duration = candidate.get("duration_seconds")
            if duration and track["duration_seconds"] and abs(duration - track["duration_seconds"]) > 5:
                return None
            return track

        with ThreadPoolExecutor(max_workers=5) as executor:
            for start in range(0, len(candidates), 5):
                hits = [track for track in executor.map(resolve_one, candidates[start:start + 5]) if track]
                tracks = eligible_tracks(tracks + self.annotate(hits), exclusions)
                if len(tracks) >= TOP_K:
                    break
        return tracks[:TOP_K]

    def recommend(self, arm, prompt, seeds, exclusions):
        if arm == "playlist_search":
            if prompt and seeds:
                raise ValueError("YouTube Music does not combine text with playlist songs.")
            tracks = self.community_playlists(prompt) if prompt else self.playlist_suggestions(seeds)
            return eligible_tracks(self.annotate(tracks), exclusions)[:TOP_K]
        if arm == "llm":
            candidates = self.llm_candidates(prompt, seeds)
        elif arm == "retrieval":
            response = requests.post(
                self.retrieval_url + "/recommend",
                json={"prompt": prompt, "seeds": seeds,
                      "exclusions": sorted({key for _, key in exclusions})},
                timeout=45,
            )
            response.raise_for_status()
            candidates = response.json()["tracks"]
        else:
            raise ValueError("Unknown recommender")
        return self.resolve_candidates(candidates, exclusions)


# Known public recordings for offline UI and database rehearsal only.
_FIXTURES = [
    ("FGBhQbmPwH8", "One More Time", ["Daft Punk"]),
    ("gAjR4_CbPpQ", "Harder, Better, Faster, Stronger", ["Daft Punk"]),
    ("5NV6Rdv1a3I", "Get Lucky", ["Daft Punk", "Pharrell Williams"]),
    ("9EcjWd-O4jI", "Around the World", ["Daft Punk"]),
    ("DWcJFNfaw9c", "Intro", ["The xx"]),
    ("3YxaaGgTQYM", "Bring Me to Life", ["Evanescence"]),
    ("btPJPFnesV4", "Eye of the Tiger", ["Survivor"]),
    ("rYEDA3JcQqw", "Rolling in the Deep", ["Adele"]),
    ("RgKAFK5djSk", "See You Again", ["Wiz Khalifa", "Charlie Puth"]),
    ("LjhCEhWiKXk", "Just the Way You Are", ["Bruno Mars"]),
]


class RehearsalBackends:
    tracks = [
        {"video_id": video_id, "title": title, "artists": artists, "duration_seconds": None,
         "seed_eligible": position % 3 != 0, "recording_key": "yt:" + video_id}
        for position, (video_id, title, artists) in enumerate(_FIXTURES)
    ]

    def ready(self, arms):
        return []

    def search(self, query):
        query = query.casefold()
        return [track for track in self.tracks if query in " ".join([track["title"], *track["artists"]]).casefold()]

    def annotate(self, tracks):
        return tracks

    def preview(self, track):
        return None

    def recommend(self, arm, prompt, seeds, exclusions):
        shift = {"retrieval": 0, "llm": 2, "playlist_search": 3}[arm]
        return eligible_tracks(self.tracks[shift:] + self.tracks[:shift], exclusions)[:TOP_K]


def timed_recommend(backends, arm, prompt, seeds, exclusions):
    if arm == "playlist_search" and prompt and seeds:
        return {"arm": arm, "tracks": [], "status": "not_applicable", "elapsed_ms": 0}
    start = perf_counter()
    try:
        tracks = backends.recommend(arm, prompt, seeds, exclusions)
        status = "ok"
    except Exception as exc:
        # Record a failure without logging external responses or participant prompts.
        LOG.warning("%s panel unavailable (%s)", arm, type(exc).__name__)
        tracks, status = [], "unavailable"
    return {"arm": arm, "tracks": tracks, "status": status,
            "elapsed_ms": round((perf_counter() - start) * 1000)}
