"""Evaluate one or many prediction JSON files and save comparable reports.

  python -m evaluation.evaluate_many predictions/a.json --results-dir results/a
  python -m evaluation.evaluate_many predictions/experiment-matrix --results-dir results/matrix
"""
import argparse
import csv
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from evaluation.evaluate import run_evaluation


def prediction_files(targets):
    files = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            files.append(path)
        else:
            files.extend(sorted(Path().glob(target)))
    return sorted(set(files))


def safe_name(path):
    return path.stem.replace(" ", "_")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", nargs="+", help="JSON file, directory, or quoted glob")
    parser.add_argument("--dataset", type=Path, default=Path("data/youtube_music/partial_examples/v3/dataset.json"))
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()
    files = prediction_files(args.predictions)
    if not files:
        parser.error("no prediction JSON files found")
    args.results_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for prediction in files:
        stem = safe_name(prediction)
        summary_path = args.results_dir / f"{stem}.json"
        text = io.StringIO()
        with redirect_stdout(text):
            run_evaluation(args.dataset, prediction, summary_path)
        (args.results_dir / f"{stem}.txt").write_text(text.getvalue(), encoding="utf-8")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for seed_count, metrics in summary["per_seed_mean_metrics"].items():
            rows.append({"prediction_file": str(prediction), "seed_count": seed_count, **metrics})
    fields = ["prediction_file", "seed_count"] + sorted({key for row in rows for key in row if key not in {"prediction_file", "seed_count"}})
    with (args.results_dir / "combined.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    print(f"Saved {len(files)} individual reports and {args.results_dir / 'combined.csv'}")


if __name__ == "__main__":
    main()
