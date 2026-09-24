"""End-to-end smoke test: auth + one call per endpoint family.

Run after filling spotify/.env (opens a browser for consent on first run):
    ~/mamba/envs/claude/bin/python spotify/scripts/smoke_test.py --user <slug>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auth import get_spotify
from client import DeprecatedEndpointError, SpotifyClient
from users import user_arg


def main():
    client = SpotifyClient(get_spotify(user_arg(__doc__).parse_args().user))

    me = client.profile()
    print(f"Authenticated as: {me['display_name']} ({me['id']})")

    top = client.top_tracks(max_items=5)
    print(f"\nTop {len(top)} tracks (medium_term):")
    for t in top:
        print(f"  {t['name']} — {t['artists'][0]['name']}")

    print(f"\nPlaylists: {len(client.playlists())}")
    print(f"Saved tracks (first 50): {len(client.saved_tracks(max_items=50))}")

    hits = client.search("Kendrick Lamar", type="artist", max_items=1)
    artist = client.artist(hits[0]["id"])
    # Dev-mode artist objects are slimmed: no genres/popularity/followers.
    print(f"\nSearch + lookup: {artist['name']} | fields={sorted(artist.keys())}")

    try:
        client.audio_features
    except DeprecatedEndpointError as e:
        print(f"\nDeprecation layer OK — blocked as expected: {e}")

    print("\nSmoke test passed.")


if __name__ == "__main__":
    main()
