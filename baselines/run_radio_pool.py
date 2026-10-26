"""Save Radio Pool's first five candidate IDs as the non-LLM control.

uv run python -m baselines.run_radio_pool
uv run python evaluation/evaluate.py --predictions predictions/radio_pool.json
"""

import argparse
from pathlib import Path

from baselines.candidates import load_pools
from youtube_music.src.playlists import save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pools", type=Path, default=Path("data/youtube_music/candidates/v1/pools.json"))
    parser.add_argument("--output", type=Path, default=Path("predictions/radio_pool.json"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing overwrite: {args.output}")
    pools = load_pools(args.pools)
    predictions = {eid: [t["video_id"] for t in ex["candidates"][:5]] for eid, ex in pools.items()}
    save_json(args.output, predictions)
    print(f"Radio Pool: saved five IDs for each of {len(predictions)} examples to {args.output}")


if __name__ == "__main__":
    main()
