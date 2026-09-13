"""EDA step 4: join coverage of external datasets over our pulled track ids.

Reads a user's inventory cache (data/spotify/<user>/) and the Kaggle 114k
dump (data/kaggle/), joins on Spotify track_id, and reports coverage.

    ~/mamba/envs/claude/bin/python spotify/scripts/coverage.py --user <slug>
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "spotify" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory import TIME_RANGES, track_ids, user_arg  # noqa: E402
from users import data_dir  # noqa: E402

KAGGLE_CSV = REPO_ROOT / "data" / "kaggle" / "spotify_tracks_114k.csv"


def main():
    src = data_dir(user_arg(__doc__).parse_args().user)

    def load(name):
        return json.loads((src / f"{name}.json").read_text())

    pools = {
        f"top_{tr}": track_ids(load(f"top_tracks_{tr}")) for tr in TIME_RANGES
    }
    pools["saved"] = track_ids(load("saved_tracks"))
    pools["recent"] = track_ids(load("recently_played"))
    pools["playlists"] = set().union(
        *(track_ids(v) for v in load("playlist_tracks").values()), set()
    )
    all_ids = set().union(*pools.values())

    with open(KAGGLE_CSV) as f:
        rows = {r["track_id"]: r for r in csv.DictReader(f)}
    matched = all_ids & rows.keys()

    print(f"Kaggle 114k dump: {len(rows)} unique track ids")
    print(f"our tracks matched: {len(matched)}/{len(all_ids)} "
          f"({len(matched) / len(all_ids):.1%})\n")
    print("== Coverage by collection ==")
    for name, ids in pools.items():
        if ids:
            print(f"{name:16}: {len(ids & rows.keys()):4}/{len(ids):4} "
                  f"({len(ids & rows.keys()) / len(ids):.1%})")

    genres = Counter(rows[i]["track_genre"] for i in matched)
    print("\nmatched-track genres:",
          ", ".join(f"{g} ({n})" for g, n in genres.most_common(8)))


if __name__ == "__main__":
    main()
