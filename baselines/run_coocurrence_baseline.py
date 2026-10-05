"""Runner script to generate non-ML co-occurrence predictions for YouTube Music."""

import argparse
import json
from pathlib import Path
import sys

# Add project root to Python path so we can import from `baselines`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cooccurrence import CooccurrenceRecommender 


def run_cooccurrence_experiment(
    dataset_path: Path,
    reference_path: Path,
    output_path: Path,
    count: int = 5,
):
    """Executes co-occurrence model pipeline and writes predictions JSON."""
    # 1. Initialize and train algorithm
    recommender = CooccurrenceRecommender()
    recommender.fit(reference_path)

    # 2. Load ground truth / test set
    raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    examples = raw_dataset if isinstance(raw_dataset, list) else raw_dataset.get("examples", [])

    predictions = {}

    print(f"\n[Runner] Generating top-{count} co-occurrence predictions for {len(examples)} test cases...")

    for idx, ex in enumerate(examples, start=1):
        # 1. Check for explicit example_id, otherwise generate a unique key using prompt/source ID and seed size
        raw_eid = ex.get("example_id")
        if raw_eid is not None:
            eid = str(raw_eid).lower().replace("example-", "").lstrip("0") or "1"
        else:
            # Construct unique key for v2 multi-seed sizes (e.g. "1_5" or "1_20" or fallback to index)
            source_id = ex.get("prompt_id") or ex.get("source_playlist_id") or f"ex_{idx}"
            seed_size = ex.get("selection", {}).get("seed_count", "default")
            eid = f"{source_id}_{seed_size}"

        # Extract seed track video_ids
        seed_tracks = ex.get("seed_tracks", [])
        seed_ids = [t["video_id"] for t in seed_tracks if isinstance(t, dict) and "video_id" in t]

        # Generate predictions using core engine
        recs = recommender.predict(seed_track_ids=seed_ids, top_k=count)
        predictions[eid] = recs

    # 3. Save output in standardized schema matching ytm_native.json
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    print(f"[Runner] Successfully saved predictions to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Non-ML Co-occurrence Baseline for YouTube Music.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/youtube_music/partial_examples/v3/dataset.json"),
        help="Path to dataset.json",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("data/youtube_music/references/v2/reference_pools.json"),
        help="Path to reference_pools.json corpus",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/youtube_music/predictions/cooccurrence.json"),
        help="Path to save predictions output",
    )
    parser.add_argument("--count", type=int, default=15, help="Number of recommendations per example")

    args = parser.parse_args()
    run_cooccurrence_experiment(
        dataset_path=args.dataset,
        reference_path=args.reference,
        output_path=args.output,
        count=args.count,
    )