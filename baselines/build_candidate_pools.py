"""Build seed-only pools and score their ceiling separately.

uv run python -m baselines.build_candidate_pools --examples 1,21 --output data/youtube_music/candidates/pilot/pools.json
uv run python -m baselines.build_candidate_pools
uv run python -m baselines.build_candidate_pools --radio-seeds 1 --cache data/youtube_music/candidates/v1/radio_cache.json --output data/youtube_music/candidates/v1-one-radio/pools.json

--radio-seeds N caps radio calls per input to the first N seeds (budget-matched
variant); co-occurrence support still uses every seed and makes no calls.

Outputs refuse overwrite. Radios checkpoint per seed for recovery/reuse across
paired examples. Hidden answers are read only after every pool is constructed.
"""

import argparse
import json
from pathlib import Path
from statistics import median
import time

from baselines.candidates import build_pool, radio_candidates
from baselines.cooccurrence import CooccurrenceRecommender
from youtube_music.src.playlists import make_client, save_json, timestamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", help="Comma-separated example IDs; default all")
    parser.add_argument("--output", type=Path, default=Path("data/youtube_music/candidates/v1/pools.json"))
    parser.add_argument("--inputs", type=Path, default=Path("data/youtube_music/partial_examples/v3/model_inputs.json"))
    parser.add_argument("--dataset", type=Path, default=Path("data/youtube_music/partial_examples/v3/dataset.json"))
    parser.add_argument("--references", type=Path, default=Path("data/youtube_music/references/v2/reference_pools.json"))
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--radio-seeds", type=int, help="Radio calls per input (first N seeds); default all")
    parser.add_argument("--cache", type=Path, help="Radio cache; default radio_cache.json beside output")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing overwrite: {args.output}")
    if args.radio_seeds is not None and args.radio_seeds < 1:
        parser.error("--radio-seeds must be positive")
    examples = json.loads(args.inputs.read_text())["examples"]
    if args.examples:
        selected = {int(value) for value in args.examples.split(",")}
        if selected - {ex["example_id"] for ex in examples}:
            parser.error("Unknown example IDs")
        examples = [ex for ex in examples if ex["example_id"] in selected]
    reference = json.loads(args.references.read_text())
    catalog = {t["video_id"]: t for p in reference["prompts"] for pl in p["playlists"] for t in pl["tracks"]}
    model = CooccurrenceRecommender()
    model.fit(args.references)
    cache_path = args.cache or args.output.parent / "radio_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    client, pools = make_client(), {}
    for ex in examples:
        seeds = ex["seed_tracks"]
        ids = [t["video_id"] for t in seeds]
        radio_ids = ids[:args.radio_seeds]
        for vid in radio_ids:
            if vid not in cache:
                cache[vid] = radio_candidates(client, [vid], delay=args.delay)
                save_json(cache_path, cache)
                # Also pace requests across examples and checkpoint calls.
                time.sleep(args.delay)
        radio = {vid: cache[vid]["radios"][vid] for vid in radio_ids}
        # Reuse the recommender's candidate support, without its popularity fallback.
        support = {candidate for vid in ids for candidate in model.co_matrix.get(vid, {})} - set(ids)
        cooccurrence = [catalog[vid] for vid in sorted(support) if vid in catalog]
        pool = build_pool(seeds, radio, cooccurrence)
        pools[str(ex["example_id"])] = {"seed_count": len(ids), "seed_tracks": seeds, "candidates": pool,
                                       "errors": [error for vid in radio_ids for error in cache[vid]["errors"]]}
        print(f'Example {ex["example_id"]}: {len(pool)} candidates, {len(pools[str(ex["example_id"])]["errors"])} errors', flush=True)
    # Scoring is downstream of construction and cannot affect pool membership/order.
    truth = {str(ex["example_id"]): {t["video_id"] for t in ex["held_out_tracks"]}
             for ex in json.loads(args.dataset.read_text())["examples"]}
    summary = {}
    for size in sorted({ex["seed_count"] for ex in pools.values()}):
        group = [(eid, ex) for eid, ex in pools.items() if ex["seed_count"] == size]
        hits = sum(bool({t["video_id"] for t in ex["candidates"]} & truth[eid]) for eid, ex in group)
        summary[str(size)] = {"examples": len(group), "ceiling": hits / len(group),
                              "median_pool_size": median(len(ex["candidates"]) for _, ex in group)}
    payload = {"schema_version": 1, "collected_at": timestamp(), "settings": {"per_seed": 50, "max_size": 60,
               "radio_seeds": args.radio_seeds, "delay": args.delay, "cooccurrence_popularity_fallback": False}, "examples": pools, "ceiling": summary}
    save_json(args.output, payload)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
