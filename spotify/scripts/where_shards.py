"""Show which node last ran each shard, i.e. where its preview audio lives.

    python spotify/scripts/where_shards.py --out-dir /data/user_data/$USER/mlip/embeddings
    python spotify/scripts/where_shards.py --out-dir ... --node clap-shard-0-of-4

The second form prints only the node name, for `sbatch --nodelist=...`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobs import DEFAULT_OUT_DIR, shard_locations  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--node", metavar="SHARD_TAG",
                        help="print just the node for this shard tag")
    args = parser.parse_args()

    locations = shard_locations(args.out_dir / "manifest")
    if args.node:
        if args.node not in locations:
            sys.exit(f"no record of {args.node}")
        print(locations[args.node]["node"])
        return
    for tag, entry in sorted(locations.items()):
        print(f"{tag:28} {entry['node']:14} {entry['event']:6} {entry['time']}  "
              f"job {entry['job_id']}  {entry.get('preview_dir', '')}")


if __name__ == "__main__":
    main()
