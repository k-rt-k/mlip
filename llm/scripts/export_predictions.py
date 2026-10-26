"""Convert LLM run files into the evaluator's {example_id: [video_ids]} format.

uv run python llm/scripts/export_predictions.py \
    data/llm/runs/qwen3.8-27b-v1/seeds_only.json \
    data/llm/runs/qwen3.8-27b-modelrun-v1/seeds_only.json \
    --output predictions/llm_qwen.json
uv run python evaluation/evaluate.py --predictions predictions/llm_qwen.json

Several run files (e.g. five- and twenty-seed runs) merge into one file; an
example id may appear in only one run. Lists keep the run's top-K order. Short
or empty lists are padded with placeholder IDs that never match, so missing
places score as misses instead of being skipped (empty) or rejected (shorter
than K) by the evaluator.
"""

import argparse
import json
from pathlib import Path


def to_predictions(run, k=None):
    k = k or run["run"]["top_k"]
    predictions = {}
    for example in run["examples"]:
        ranked = sorted((r for r in example["recommendations"] if r["in_top_k"]), key=lambda r: r["rank"])
        ids = [r["track"]["video_id"] for r in ranked][:k]
        predictions[str(example["id"])] = ids + [f"__missing_{i}__" for i in range(len(ids), k)]
    return predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_files", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--k", type=int, help="list length (default: each run's top-K)")
    args = parser.parse_args()
    predictions = {}
    for path in args.run_files:
        new = to_predictions(json.loads(path.read_text(encoding="utf-8")), args.k)
        if set(new) & set(predictions):
            raise SystemExit(f"{path}: example ids already exported by an earlier run file")
        predictions.update(new)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(predictions, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(predictions)} examples to {args.output}")


if __name__ == "__main__":
    main()
