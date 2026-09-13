"""EDA step 2: inventory all personal data the dev-mode API exposes.

Pulls every user-side collection, caches raw JSON under data/spotify/<user>/,
and prints sizes/overlap/freshness. Rerun anytime; overwrites the cache.

    ~/mamba/envs/claude/bin/python spotify/scripts/inventory.py --user <slug>
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "spotify" / "src"))

from spotipy.exceptions import SpotifyException

from auth import get_spotify
from client import SpotifyClient, unwrap_item
from users import data_dir

TIME_RANGES = ("short_term", "medium_term", "long_term")


def user_arg(description):
    """Shared argparse setup: every script needs a required --user slug."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--user", required=True, help="slug naming whose data (e.g. kartik)")
    return parser


def dump(name, obj, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(obj, indent=1))
    return obj


def track_ids(entries):
    """Unique non-local track ids from a list of (possibly wrapped) entries."""
    unwrapped = (unwrap_item(e) for e in entries)
    return {t["id"] for t in unwrapped if t and t.get("id")}


def main():
    user = user_arg(__doc__).parse_args().user
    out_dir = data_dir(user)
    client = SpotifyClient(get_spotify(user))

    def save(name, obj):
        return dump(name, obj, out_dir)

    top = {tr: save(f"top_tracks_{tr}", client.top_tracks(time_range=tr, max_items=None))
           for tr in TIME_RANGES}
    top_artists = {tr: save(f"top_artists_{tr}", client.top_artists(time_range=tr, max_items=None))
                   for tr in TIME_RANGES}
    saved = save("saved_tracks", client.saved_tracks())
    recent = save("recently_played", client.recently_played())
    followed = save("followed_artists", client.followed_artists())
    playlists = save("playlists", client.playlists())
    # Non-owned (followed/editorial) playlists 403 in dev mode — skip those.
    playlist_tracks, blocked_playlists = {}, []
    for p in playlists:
        try:
            playlist_tracks[p["id"]] = client.playlist_tracks(p["id"])
        except SpotifyException as e:
            if e.http_status != 403:
                raise
            blocked_playlists.append(f"{p['name']} (owner: {p['owner']['display_name']})")
    save("playlist_tracks", playlist_tracks)

    print(f"Raw JSON cached in {out_dir}\n")
    print("== Sizes ==")
    for tr in TIME_RANGES:
        print(f"top tracks {tr:12}: {len(top[tr]):4}   top artists {tr}: {len(top_artists[tr])}")
    print(f"saved tracks        : {len(saved)}")
    print(f"recently played     : {len(recent)}")
    print(f"followed artists    : {len(followed)}")
    print(f"playlists           : {len(playlists)} "
          f"({sum(len(v) for v in playlist_tracks.values())} tracks pulled; "
          f"{len(blocked_playlists)} blocked 403)")
    for name in blocked_playlists:
        print(f"  blocked: {name}")

    saved_ids = track_ids(saved)
    pool = {
        "top(all ranges)": set().union(*(track_ids(top[tr]) for tr in TIME_RANGES)),
        "saved": saved_ids,
        "playlists": set().union(*(track_ids(v) for v in playlist_tracks.values())) if playlist_tracks else set(),
        "recent": track_ids(recent),
    }
    all_ids = set().union(*pool.values())
    print(f"\n== Coverage ==\nunique tracks overall: {len(all_ids)}")
    for name, ids in pool.items():
        overlap = len(ids & saved_ids) / len(ids) if ids and name != "saved" else None
        extra = f"  ({overlap:.0%} also saved)" if overlap is not None else ""
        print(f"{name:16}: {len(ids):4} unique{extra}")

    artist_counts = Counter(
        a["name"]
        for e in saved + recent
        if (t := unwrap_item(e))
        for a in t["artists"]
    )
    print("\ntop artists across saved+recent:",
          ", ".join(f"{a} ({n})" for a, n in artist_counts.most_common(5)))


if __name__ == "__main__":
    main()
