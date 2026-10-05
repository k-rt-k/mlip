"""Evaluation runner for playlist continuation models grouped by seed count."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

from metrics import calculate_all_metrics


def load_dataset_ground_truth(dataset_path: Path) -> dict:
    """Loads dataset.json and extracts metadata and held_out video_ids per example."""
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    examples = raw.get("examples", raw) if isinstance(raw, dict) else raw
    
    ground_truth = {}
    for idx, ex in enumerate(examples, start=1):
        # Extract explicit example_id
        raw_eid = ex.get("example_id")
        if raw_eid is not None:
            eid = str(raw_eid).lower().replace("example-", "").lstrip("0") or "1"
        else:
            source_id = ex.get("prompt_id") or ex.get("source_playlist_id") or f"ex_{idx}"
            seed_size = ex.get("selection", {}).get("seed_count", "default")
            eid = f"{source_id}_{seed_size}"

        # Extract seed track count (checking explicit field, seed_tracks list, or selection metadata)
        seed_count = (
            ex.get("seed_count")
            or len(ex.get("seed_tracks", []))
            or ex.get("selection", {}).get("seed_count", 0)
        )
        try:
            seed_count = int(seed_count)
        except (ValueError, TypeError):
            seed_count = 0

        # Extract video_ids from held_out_tracks
        held_out = ex.get("held_out_tracks", [])
        video_ids = [t["video_id"] for t in held_out if isinstance(t, dict) and "video_id" in t]
        
        ground_truth[eid] = {
            "video_ids": video_ids,
            "seed_count": seed_count,
            "order": idx  # preserve original position for stable sorting
        }
        
    return ground_truth


def run_evaluation(dataset_path: Path, predictions_path: Path, output_path: Path = None):
    """Executes full benchmark evaluation with per-seed aggregations."""
    k = [1, 5]

    ground_truth = load_dataset_ground_truth(dataset_path)
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))

    num_examples = len(ground_truth)
    print(f"\nEvaluating: {predictions_path.name}")
    print(f"Ground Truth: {dataset_path.name} ({num_examples} examples)\n")

    if not ground_truth:
        print("No ground truth examples found.")
        return

    # Sample metric calculation to dynamically discover result keys
    first_eid = next(iter(ground_truth))
    sample_recs = predictions.get(first_eid, [])
    sample_metrics = calculate_all_metrics(
        recommended=sample_recs, 
        ground_truth=ground_truth[first_eid]["video_ids"], 
        k=k
    )
    metric_keys = list(sample_metrics.keys())

    # Stable sort by seed_count (preserving original insertion order for ties)
    sorted_examples = sorted(
        ground_truth.items(),
        key=lambda item: (item[1]["seed_count"], item[1]["order"])
    )

    # Build metric-agnostic table header
    col_width = 12
    header_cols = [f"{'Example ID':<{col_width}}", f"{'Seeds':<{col_width}}"] + [f"{m:<{col_width}}" for m in metric_keys]
    header = " | ".join(header_cols)
    print(header)
    print("-" * len(header))

    results_per_example = {}
    metric_sums = defaultdict(float)
    
    # Per-seed aggregation structure: seed_count -> {metric_key: sum_val, 'count': num_examples}
    seed_aggregations = defaultdict(lambda: {"count": 0, "metrics": defaultdict(float)})
    evaluated_count = 0

    # Evaluation Loop (Sorted by Seeds)
    for eid, data in sorted_examples:
        gt_tracks = data["video_ids"]
        seed_cnt = data["seed_count"]
        recs = predictions.get(eid, [])
        
        if len(recs) == 0:
            continue
            
        metrics = calculate_all_metrics(recommended=recs, ground_truth=gt_tracks, k=k)
        results_per_example[eid] = metrics
        evaluated_count += 1

        row_str = f"{eid:<{col_width}} | {seed_cnt:<{col_width}}"
        for key in metric_keys:
            val = metrics.get(key, 0.0)
            
            # Aggregate totals
            metric_sums[key] += val
            seed_aggregations[seed_cnt]["metrics"][key] += val
            row_str += f" | {val:<{col_width}.4f}"
            
        seed_aggregations[seed_cnt]["count"] += 1
        print(row_str)

    print("=" * len(header))

    # --- PER-SEED SUMMARY ---
    print("\n" + "=" * 50)
    print("PER-SEED METRICS SUMMARY")
    print("=" * 50)
    
    per_seed_means = {}
    for seed_cnt in sorted(seed_aggregations.keys()):
        stats = seed_aggregations[seed_cnt]
        cnt = stats["count"]
        print(f"\n--- Seed Count: {seed_cnt} ({cnt} examples) ---")
        
        per_seed_means[seed_cnt] = {}
        max_key_len = max(len(k) for k in metric_keys) if metric_keys else 15
        
        for key in metric_keys:
            mean_val = stats["metrics"][key] / cnt if cnt > 0 else 0.0
            per_seed_means[seed_cnt][key] = mean_val
            print(f"  {key:<{max_key_len}} : {mean_val:.4f}")

    # --- ENTIRE DATASET SUMMARY ---
    total_eval = evaluated_count or 1
    overall_means = {key: metric_sums[key] / total_eval for key in metric_keys}

    print("\n" + "=" * 50)
    print(f"OVERALL DATASET SUMMARY ({evaluated_count}/{num_examples} evaluated)")
    print("=" * 50)
    max_key_len = max(len(k) for k in metric_keys) if metric_keys else 15
    for key, val in overall_means.items():
        print(f"  {key:<{max_key_len}} : {val:.4f}")
    print("=" * 50 + "\n")

    # Save detailed summary to JSON if path provided
    if output_path:
        summary_payload = {
            "predictions_file": str(predictions_path),
            "dataset_file": str(dataset_path),
            "num_examples": num_examples,
            "evaluated_examples": evaluated_count,
            "overall_mean_metrics": overall_means,
            "per_seed_mean_metrics": per_seed_means,
            "per_example": results_per_example,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
        print(f"Detailed results saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate baseline recommendation outputs grouped by seed size.")
    parser.add_argument("--dataset", type=Path, default="data/youtube_music/partial_examples/v3/dataset.json", help="Path to dataset.json file")
    parser.add_argument("--predictions", type=Path, required=True, help="Path to predictions JSON mapping example_id to video_ids")
    parser.add_argument("--output", type=Path, default=None, help="Optional path to save evaluation summary JSON")

    args = parser.parse_args()
    run_evaluation(args.dataset, args.predictions, output_path=args.output)