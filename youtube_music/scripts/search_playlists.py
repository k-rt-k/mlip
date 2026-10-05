"""Search YouTube Music and snapshot matching playlists and their songs.

    uv run python youtube_music/scripts/search_playlists.py --prompts-file prompts.txt --queries-file youtube_music/search_queries.txt
    uv run python youtube_music/scripts/search_playlists.py --query "mellow jazz dinner" --limit 3 --output data/youtube_music/jazz.json

No authentication required. --limit is a per-query playlist cap, not a corpus
coverage guarantee. Reuse the saved snapshot for all methods in an experiment;
use a different output path for a fresh run. API errors are checkpointed and
produce exit code 1. Search relevance and recording identity still need review.
Optional queries-file lines correspond one-to-one to prompt lines, keeping
evaluation prompts separate from shorter discovery queries. Long mixes are
excluded from cleaned tracks using a configurable 15-minute pilot cutoff;
raw playlist contents remain intact.
"""

import argparse
from importlib.metadata import version
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playlists import clean_tracks, make_client, playlist_id, save_json, timestamp  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query")
    source.add_argument("--prompts-file", type=Path)
    parser.add_argument("--queries-file", type=Path)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--filter", choices=["community_playlists", "featured_playlists"], default="community_playlists")
    parser.add_argument("--output", type=Path, default=Path("data/youtube_music/search.json"))
    parser.add_argument("--max-duration-seconds", type=int, default=900, help="Pilot song-length cutoff; 0 disables")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.max_duration_seconds < 0:
        parser.error("--max-duration-seconds must be nonnegative")
    if args.queries_file and not args.prompts_file:
        parser.error("--queries-file requires --prompts-file")
    if args.output.exists():
        parser.error("Output already exists; reuse it or choose a new --output path.")
    prompts = [args.query] if args.query is not None else args.prompts_file.read_text(encoding="utf-8").splitlines()
    prompts = [p.strip() for p in prompts if p.strip()]
    queries = prompts
    if args.queries_file:
        queries = [q.strip() for q in args.queries_file.read_text(encoding="utf-8").splitlines() if q.strip()]
        if len(queries) != len(prompts):
            parser.error("Prompt and query files must have the same number of nonempty lines")
    if not prompts:
        parser.error("No nonempty queries supplied")
    client = make_client()
    snapshot = {"schema_version": 1, "collected_at": timestamp(), "ytmusicapi_version": version("ytmusicapi"),
                "filter": args.filter, "limit_per_query": args.limit,
                "track_filter": {"max_duration_seconds": args.max_duration_seconds},
                "queries": [], "playlists": {}, "complete": False}
    errors = 0
    for prompt, query in zip(prompts, queries):
        record = {"prompt": prompt, "query": query, "playlist_ids": [], "errors": []}
        snapshot["queries"].append(record)
        try:
            found = client.search(query, filter=args.filter, limit=args.limit)
            record["raw_search_results"] = found
            ids = []
            for item in found:
                candidate = item.get("browseId") or item.get("playlistId")
                if candidate:
                    value = playlist_id(candidate)
                    if value not in ids:
                        ids.append(value)
            record["playlist_ids"] = ids[:args.limit]
            for value in record["playlist_ids"]:
                if value in snapshot["playlists"]:
                    continue
                try:
                    raw = client.get_playlist(value, limit=None)
                    snapshot["playlists"][value] = {"collected_at": timestamp(), "raw": raw,
                                                   "tracks": clean_tracks(raw.get("tracks", []), args.max_duration_seconds)}
                except Exception as exc:
                    errors += 1
                    record["errors"].append({"playlist_id": value, "error_type": type(exc).__name__, "message": str(exc)})
                save_json(args.output, snapshot)
        except Exception as exc:
            errors += 1
            record["errors"].append({"error_type": type(exc).__name__, "message": str(exc)})
        save_json(args.output, snapshot)
        usable = sum(bool(snapshot["playlists"].get(i, {}).get("tracks")) for i in record["playlist_ids"])
        print(f"{query}: {usable}/{len(record['playlist_ids'])} playlists with usable songs", flush=True)
    snapshot["complete"] = errors == 0
    save_json(args.output, snapshot)
    print(f"Saved {len(snapshot['playlists'])} playlists to {args.output}; {errors} API errors.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
