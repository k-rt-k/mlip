"""Write evaluator-ready prompt-plus-playlist predictions from cached CLAP vectors.

The candidate catalog is the public prompt-reference pool, so output IDs are
YouTube Music video IDs and can be passed directly to evaluation/evaluate.py.
This runner never reads dataset.json or held-out tracks.

Example (on Babel, where the cached eval vectors exist):
  /path/to/encoder-venv/bin/python -m experiments.retrieval.run_playlist_conditioned \
    --embeddings /data/user_data/ksnair/mlip/embeddings/ytm-eval/clap.npz \
    --output predictions/prompt_playlist_clap.json \
    --report data/retrieval/prompt_playlist_clap/report.json
"""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from experiments.retrieval.playlist_data import (
    candidate_matrix,
    load_partial_examples,
    load_reference_candidate_ids,
    load_video_embeddings,
)
from experiments.retrieval.playlist_model import fused_query, mean_seed_vector, rank_candidates

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "spotify" / "src"))
from embeddings import get_embedder  # noqa: E402


def pad(ids: list[str], top_k: int, example_id: str) -> list[str]:
    return ids + [f"__missing_{example_id}_{rank}__" for rank in range(len(ids), top_k)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inputs", type=Path, default=Path("data/youtube_music/partial_examples/v3/model_inputs.json"))
    parser.add_argument("--prompts", type=Path, default=Path("data/youtube_music/partial_examples/v3/prompt_inputs.json"))
    parser.add_argument("--references", type=Path, default=Path("data/youtube_music/references/v2/reference_pools.json"))
    parser.add_argument("--embeddings", type=Path, required=True, help="cached YTM CLAP NPZ keyed by video ID")
    parser.add_argument("--output", type=Path, required=True, help="new {example_id: [video_id]} JSON")
    parser.add_argument("--report", type=Path, required=True, help="new diagnostics JSON")
    parser.add_argument("--prompt-weight", type=float, default=0.5)
    parser.add_argument("--rerank-seed-weight", type=float, default=0.25)
    parser.add_argument("--retrieve-k", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    # if args.output.exists() or args.report.exists():
    #     parser.error("output and report paths must both be new")

    examples = load_partial_examples(args.inputs, args.prompts)
    embeddings = load_video_embeddings(args.embeddings)
    candidate_ids, candidates = candidate_matrix(embeddings, load_reference_candidate_ids(args.references))
    print(f"Loaded {len(examples)} inputs, {len(embeddings)} song vectors, and {len(candidate_ids)} embedded candidates", flush=True)
    print("Loading CLAP text encoder…", flush=True)
    encoder = get_embedder("clap", device=args.device)
    print("Encoding frozen prompts…", flush=True)
    prompt_vectors = encoder.embed_text([example.prompt for example in examples])
    if prompt_vectors.shape != (len(examples), candidates.shape[1]):
        raise ValueError("text and song embeddings have incompatible dimensions")

    predictions, diagnostics = {}, []
    for example, prompt_vector in zip(examples, prompt_vectors):
        seed_vector, missing = mean_seed_vector(example.seed_video_ids, embeddings)
        query = fused_query(prompt_vector, seed_vector, args.prompt_weight)
        ranked = rank_candidates(
            candidate_ids=candidate_ids, candidate_vectors=candidates, query=query,
            seed_vector=seed_vector, excluded_ids=example.seed_video_ids,
            top_k=args.top_k, retrieve_k=min(args.retrieve_k, len(candidate_ids)),
            rerank_seed_weight=args.rerank_seed_weight,
        )
        ids = [item.video_id for item in ranked]
        predictions[example.example_id] = pad(ids, args.top_k, example.example_id)
        diagnostics.append({
            "example_id": example.example_id,
            "seed_count": len(example.seed_video_ids),
            "embedded_seed_count": len(example.seed_video_ids) - len(missing),
            "missing_seed_ids": list(missing),
            "mode": "prompt_only_fallback" if seed_vector is None else "prompt_plus_seed",
            "recommendations": [{"video_id": item.video_id, "score": item.score} for item in ranked],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(predictions, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps({
        "schema_version": 1,
        "inputs": str(args.inputs), "prompts": str(args.prompts), "references": str(args.references),
        "embeddings": str(args.embeddings), "candidate_count": len(candidate_ids),
        "top_k": args.top_k, "retrieve_k": args.retrieve_k,
        "prompt_weight": args.prompt_weight, "rerank_seed_weight": args.rerank_seed_weight,
        "examples": diagnostics,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(predictions)} prediction lists to {args.output}")


if __name__ == "__main__":
    main()


# python   -m experiments.retrieval.run_playlist_conditioned   --embeddings /data/user_data/ksnair/mlip/embeddings/ytm-eval/clap.npz   --output predictions/prompt_playlist_clap_fusion.json   --report data/retrieval/prompt_playlist_clap_fusion/report.json   --prompt-weight 0.5   --rerank-seed-weight 0.25 --top-k 10