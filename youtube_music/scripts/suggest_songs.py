"""Snapshot platform suggestions, preserving ranking and excluding seed songs.

    uv run python youtube_music/scripts/suggest_songs.py --playlist-id NEW_PLAYLIST_ID --auth data/youtube_music/browser.json --output data/youtube_music/suggestions.json

Use the seed-only copy ID for evaluation, never the original full playlist ID.
Suggestions require an authenticated account that owns the playlist in the
current library implementation. Missing suggestions are recorded as a shortfall;
the script returns exit code 1 when fewer than --count usable suggestions exist.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playlists import get_suggestions, make_client, save_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist-id", required=True)
    parser.add_argument("--auth", type=Path)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--max-duration-seconds", type=int, default=900, help="Pilot song-length cutoff; 0 disables")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    if args.max_duration_seconds < 0:
        parser.error("--max-duration-seconds must be nonnegative")
    if args.output.exists():
        parser.error("Output already exists; choose a new --output path.")
    result = get_suggestions(make_client(args.auth), args.playlist_id, args.count, args.max_duration_seconds)
    save_json(args.output, result)
    print(f"Saved {len(result['suggested_tracks'])}/{args.count} suggestions to {args.output}")
    if result["owned_by_authenticated_user"] is False:
        print("The current session does not own this playlist; authenticate as its owner to request suggestions.")
    return 1 if result["shortfall"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
