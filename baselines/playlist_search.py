"""Run the prompt-only playlist-frequency baseline using public YouTube Music.

    .venv/bin/python -m baselines.playlist_search
    .venv/bin/python evaluation/evaluate_prompt_only.py \
        --predictions predictions/playlist_search_v1.json \
        --output results/playlist_search_v1.json

Defaults are fixed before scoring: original prompt text, first five distinct
non-reference community playlists among 20 search results, first 100 tracks per
playlist, the existing 15-minute filter, then playlist support / video-ID order.
Ten predictions are exported for evaluator compatibility; the report uses @5.
Missing slots count as misses. Responses are cached for offline reproduction.
"""

import argparse
from collections import Counter
from importlib.metadata import version
import json
from pathlib import Path
import time

from youtube_music.src.playlists import clean_tracks, make_client, playlist_id, save_json, timestamp


def select_playlists(results, excluded, limit):
    """Exclude reference IDs and duplicates before applying the playlist cap."""
    selected = []
    for item in results:
        value = item.get("browseId") or item.get("playlistId")
        if not value:
            continue
        value = playlist_id(value)
        if value not in excluded and value not in selected:
            selected.append(value)
        if len(selected) == limit:
            break
    return selected


def rank_songs(playlists, top_k):
    """Count a song once per playlist, with deterministic video-ID tie breaking."""
    counts = Counter()
    for tracks in playlists:
        counts.update({t["video_id"] for t in tracks})
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top_k]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--references", type=Path, default=Path("data/youtube_music/references/v2/reference_pools.json"))
    parser.add_argument("--cache", type=Path, default=Path("data/youtube_music/playlist_search/v1/snapshot.json"))
    parser.add_argument("--output", type=Path, default=Path("predictions/playlist_search_v1.json"))
    parser.add_argument("--playlists", type=int, default=5)
    parser.add_argument("--search-limit", type=int, default=20)
    parser.add_argument("--tracks-per-playlist", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()
    if not 0 < args.playlists <= args.search_limit or args.tracks_per_playlist < 1 or args.delay < 0:
        parser.error("Require 0 < playlists <= search-limit, positive track cap, and nonnegative delay")
    prompts = json.loads(args.references.read_text())["prompts"]
    # Reference song memberships are never consulted during retrieval or ranking.
    inputs = [{"prompt_id": str(p["prompt_id"]), "prompt": p["prompt"],
               "excluded_playlist_ids": sorted(playlist_id(x["playlist_id"]) for x in p["playlists"])}
              for p in prompts]
    settings = {"playlists": args.playlists, "search_limit": args.search_limit,
                "tracks_per_playlist": args.tracks_per_playlist, "filter": "community_playlists",
                "max_duration_seconds": 900, "top_k": 10,
                "ranking": "playlist_support_desc_video_id_asc", "ytmusicapi_version": version("ytmusicapi")}
    snapshot = (json.loads(args.cache.read_text()) if args.cache.exists() else
                {"schema_version": 1, "started_at": timestamp(), "settings": settings,
                 "inputs": inputs, "prompts": {}, "playlists": {}, "complete": False})
    if snapshot["settings"] != settings or snapshot["inputs"] != inputs:
        parser.error("Cached run has different settings or inputs; choose another cache path")
    client = make_client()
    predictions = {}
    for entry in inputs:
        pid = entry["prompt_id"]
        record = snapshot["prompts"].setdefault(pid, dict(entry))
        if "search_results" not in record:
            record["search_results"] = client.search(entry["prompt"], filter=settings["filter"], limit=args.search_limit)
            record["searched_at"] = timestamp()
            save_json(args.cache, snapshot)
            time.sleep(args.delay)
        # ytmusicapi can return more than the requested limit in its first page.
        selected = select_playlists(record["search_results"][:args.search_limit],
                                    set(entry["excluded_playlist_ids"]), args.playlists)
        record["selected_playlist_ids"] = selected
        for value in selected:
            if value not in snapshot["playlists"]:
                raw = client.get_playlist(value, limit=args.tracks_per_playlist)
                raw_tracks = raw.get("tracks", [])[:args.tracks_per_playlist]
                snapshot["playlists"][value] = {"fetched_at": timestamp(), "title": raw.get("title"),
                                                "raw": raw, "tracks": clean_tracks(raw_tracks, 900)}
                save_json(args.cache, snapshot)
                time.sleep(args.delay)
        ranked = rank_songs([snapshot["playlists"][value]["tracks"] for value in selected], 10)
        record["ranked_songs"] = [{"video_id": vid, "playlist_support": support} for vid, support in ranked]
        ids = [vid for vid, _ in ranked]
        ids += [f"__missing_playlist_search_{pid}_{i}__" for i in range(len(ids), 10)]
        predictions[pid] = ids
        record["prediction"] = ids
        save_json(args.cache, snapshot)
        print(f"Prompt {pid}: {len(selected)} non-reference playlists; {len(ranked)} recommendations", flush=True)
    snapshot["complete"] = True
    snapshot["completed_at"] = timestamp()
    save_json(args.cache, snapshot)
    save_json(args.output, predictions)
    print(f"Saved {len(predictions)} prompt predictions to {args.output}", flush=True)


if __name__ == "__main__":
    main()
