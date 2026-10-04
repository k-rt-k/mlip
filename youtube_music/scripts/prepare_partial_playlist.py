"""Save a seed/hidden split; optionally create and verify a seed-only private copy.

    uv run python youtube_music/scripts/prepare_partial_playlist.py --playlist-id PLAYLIST_ID --output data/youtube_music/partial.json
    uv run python youtube_music/scripts/prepare_partial_playlist.py --playlist-id PLAYLIST_ID --output data/youtube_music/partial.json --create --auth data/youtube_music/browser.json

Default is local preparation only. --snapshot can reuse a search snapshot to
avoid refetching the original. --create requires local ytmusicapi authentication.
Rerunning reuses a matching saved split and never recreates an already saved
platform copy. Original playlists are never modified. Keep hidden references
local: only seed_tracks are recommender inputs.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playlists import create_seed_playlist, make_client, playlist_id, prepare_partial, save_json, timestamp, verify_seed_playlist  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--snapshot", type=Path, help="Saved search snapshot containing the original")
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--max-duration-seconds", type=int, default=900, help="Pilot song-length cutoff; 0 disables")
    parser.add_argument("--create", action="store_true", help="Create a private playlist on the authenticated account")
    parser.add_argument("--auth", type=Path)
    parser.add_argument("--title", default="MLIP baseline sample", help="Use a neutral title for partial-only evaluation")
    args = parser.parse_args()
    if args.seed_count < 1:
        parser.error("--seed-count must be positive")
    if args.max_duration_seconds < 0:
        parser.error("--max-duration-seconds must be nonnegative")
    if args.create and args.auth is None:
        parser.error("--create requires --auth; run youtube_music/scripts/setup_auth.py first.")
    value = playlist_id(args.playlist_id)
    if args.output.exists():
        example = json.loads(args.output.read_text(encoding="utf-8"))
        expected = {"method": "random_sample", "seed_count": args.seed_count, "random_seed": args.random_seed}
        if (example.get("source_playlist_id") != value or example.get("selection") != expected
                or example.get("track_filter") != {"max_duration_seconds": args.max_duration_seconds}):
            parser.error("Existing example has different settings; choose a new output path.")
    else:
        if args.snapshot:
            saved = json.loads(args.snapshot.read_text(encoding="utf-8"))
            raw = saved["playlists"][value]["raw"]
        else:
            raw = make_client().get_playlist(value, limit=None)
        raw = {**raw, "id": value}
        example = prepare_partial(raw, args.seed_count, args.random_seed, args.max_duration_seconds)
        example["prepared_at"] = timestamp()
        original_path = args.output.with_suffix(".source.json")
        save_json(original_path, raw)
        example["source_snapshot"] = str(original_path)
        save_json(args.output, example)
    if args.create:
        try:
            client = make_client(args.auth)
            if example.get("created_playlist_id"):
                verify_seed_playlist(client, example)
                print(f"Reused and verified saved playlist {example['created_playlist_id']}")
            else:
                created = create_seed_playlist(client, example, args.title)
                print(f"Created and verified private playlist: https://music.youtube.com/playlist?list={created}")
        finally:
            save_json(args.output, example)
    print(f"Saved {len(example['seed_tracks'])} seeds and {len(example['held_out_tracks'])} hidden songs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
