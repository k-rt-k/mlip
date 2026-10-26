"""Score prompt-only predictions against each prompt's reference playlists.

uv run python evaluation/evaluate_prompt_only.py --predictions predictions/llm_qwen_prompt_only.json

A recommendation is relevant if its exact video ID appears in any of the
prompt's three reference playlists (the union: keys of `song_support`). Uses the
same metric functions as evaluate.py; each prompt counts equally.
"""

import argparse
import json
from pathlib import Path

from metrics import calculate_all_metrics


def run_evaluation(references_path, predictions_path, k=(1, 5, 10), output_path=None):
    prompts = json.loads(Path(references_path).read_text(encoding="utf-8"))["prompts"]
    predictions = json.loads(Path(predictions_path).read_text(encoding="utf-8"))
    per_prompt = {}
    for prompt in prompts:
        pid = str(prompt["prompt_id"])
        if pid in predictions:
            per_prompt[pid] = calculate_all_metrics(predictions[pid], prompt["song_support"].keys(), k=list(k))
    keys = next(iter(per_prompt.values())).keys() if per_prompt else []
    means = {key: sum(m[key] for m in per_prompt.values()) / len(per_prompt) for key in keys}
    print(f"Prompt-only: {predictions_path} ({len(per_prompt)}/{len(prompts)} prompts)")
    for key, value in means.items():
        print(f"  {key:<14}: {value:.4f}")
    if output_path:
        Path(output_path).write_text(json.dumps({"mean_metrics": means, "per_prompt": per_prompt}, indent=2) + "\n",
                                     encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--references", type=Path, default="data/youtube_music/references/v2/reference_pools.json")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_evaluation(args.references, args.predictions, output_path=args.output)
