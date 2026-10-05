"""Evaluation runner for playlist continuation models."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

from metrics import calculate_all_metrics


def load_dataset_ground_truth(dataset_path: Path) -> dict:
    """Loads dataset.json and extracts example_id -> set of held_out video_ids."""
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    examples = raw.get("examples", raw) if isinstance(raw, dict) else raw
    
    ground_truth = {}
    for idx, ex in enumerate(examples, start=1):
        # 1. Try extracting explicit example_id
        raw_eid = ex.get("example_id")
        
        # 2. Normalize "example-01" or 1 into "1" to match prediction keys
        if raw_eid is not None:
            # Strip prefixes like "example-" if present
            cleaned_eid = str(raw_eid).lower().replace("example-", "").lstrip("0")
            eid = cleaned_eid if cleaned_eid else "1"
        else:
            eid = str(idx)

        # Extract video_ids from held_out_tracks
        held_out = ex.get("held_out_tracks", [])
        video_ids = [t["video_id"] for t in held_out if isinstance(t, dict) and "video_id" in t]
        ground_truth[eid] = video_ids
        
    return ground_truth


def run_evaluation(dataset_path: Path, predictions_path: Path, output_path: Path = None):
    """Executes full benchmark evaluation."""
    k = [1, 5, 10, 20, 30]

    ground_truth = load_dataset_ground_truth(dataset_path)
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))

    results_per_example = {}
    metric_sums = defaultdict(float)
    num_examples = len(ground_truth)

    print(f"\nEvaluating: {predictions_path.name}")
    print(f"Ground Truth: {dataset_path.name} ({num_examples} examples)\n")
    
    # Table Header
    header = f"{'Example ID':<12} | {'P@' + str(k):<8} | {'R@' + str(k):<8} | {'Hit@' + str(k):<8} | {'R-Prec':<8}"
    print(header)
    print("-" * len(header))

    for eid, gt_tracks in ground_truth.items():
        recs = predictions.get(eid, [])
        
        # Calculate metrics using metrics.py
        metrics = calculate_all_metrics(recommended=recs, ground_truth=gt_tracks, k=k)
        results_per_example[eid] = metrics

        for key, val in metrics.items():
            metric_sums[key] += val

        p_val = metrics[f"precision@{k}"]
        r_val = metrics[f"recall@{k}"]
        hit_val = metrics[f"hit_rate@{k}"]
        r_prec = metrics["r_precision"]

        print(f"{eid:<12} | {p_val:<8.4f} | {r_val:<8.4f} | {hit_val:<8.4f} | {r_prec:<8.4f}")

    # Compute Means
    means = {key: val / num_examples for key, val in metric_sums.items()}

    print("=" * len(header))
    print("MEAN AGGREGATED METRICS:")
    for key, val in means.items():
        print(f"  {key:<15}: {val:.4f}")
    print("=" * len(header) + "\n")

    # Save results to disk if requested
    if output_path:
        summary_payload = {
            "predictions_file": str(predictions_path),
            "dataset_file": str(dataset_path),
            "num_examples": num_examples,
            "mean_metrics": means,
            "per_example": results_per_example,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
        print(f"Detailed results saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate baseline recommendation outputs.")
    parser.add_argument("--dataset", type=Path, default="data/youtube_music/partial_examples/v1/dataset.json", help="Path to dataset.json file")
    parser.add_argument("--predictions", type=Path, required=True, help="Path to predictions JSON mapping example_id to video_ids")
    parser.add_argument("--output", type=Path, default=None, help="Optional path to save evaluation summary JSON")

    args = parser.parse_args()
    run_evaluation(args.dataset, args.predictions, output_path=args.output)