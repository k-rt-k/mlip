"""Write evaluator-ready seed-only predictions from cached CLAP vectors (no text, no training).

Each input's seed vectors are mean-pooled and the embedded public reference pool
is ranked by cosine similarity to that centroid, excluding the seeds. Pass the
Deezer-preview cache first and the YouTube-clip seed fallback second; earlier
files win when both hold an ID. Needs only NumPy (no CLAP model), and never
reads dataset.json or held-out tracks.

  uv run python -m experiments.retrieval.run_seed_only \
    --embeddings data/embeddings/clap.npz data/embeddings/seed-youtube-clap.npz \
    --output predictions/seed_only_clap_v1.json \
    --report data/retrieval/seed_only_clap_v1/report.json
  uv run python evaluation/evaluate.py \
    --predictions predictions/seed_only_clap_v1.json \
    --output data/retrieval/seed_only_clap_v1/evaluation.json

On Babel the caches are /data/user_data/ksnair/mlip/embeddings/ytm-eval/clap.npz
and /data/user_data/ksnair/mlip/embeddings/seed-youtube-clap.npz.
"""

import argparse
from collections import Counter
import json
from pathlib import Path

from experiments.retrieval.playlist_data import (
    candidate_matrix,
    load_reference_candidate_ids,
    load_seed_inputs,
    load_video_embeddings,
    merge_embeddings,
)
from experiments.retrieval.playlist_model import mean_seed_vector, rank_candidates
from experiments.retrieval.run_playlist_conditioned import pad


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inputs", type=Path, default=Path("data/youtube_music/partial_examples/v3/model_inputs.json"))
    parser.add_argument("--references", type=Path, default=Path("data/youtube_music/references/v2/reference_pools.json"))
    parser.add_argument("--embeddings", type=Path, nargs="+", required=True,
                        help="ids/vectors NPZ caches keyed by video ID, highest priority first")
    parser.add_argument("--output", type=Path, required=True, help="{example_id: [video_id]} JSON")
    parser.add_argument("--report", type=Path, required=True, help="diagnostics JSON")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    examples = load_seed_inputs(args.inputs)
    embeddings, origin = merge_embeddings([load_video_embeddings(path) for path in args.embeddings])
    candidate_ids, candidates = candidate_matrix(embeddings, load_reference_candidate_ids(args.references))
    print(f"Loaded {len(examples)} inputs, {len(embeddings)} song vectors, "
          f"and {len(candidate_ids)} embedded candidates", flush=True)

    predictions, diagnostics = {}, []
    for example in examples:
        seed_vector, missing = mean_seed_vector(example.seed_video_ids, embeddings)
        ranked = [] if seed_vector is None else rank_candidates(
            candidate_ids=candidate_ids, candidate_vectors=candidates, query=seed_vector,
            seed_vector=seed_vector, excluded_ids=example.seed_video_ids,
            top_k=args.top_k, retrieve_k=len(candidate_ids), rerank_seed_weight=0.0,
        )
        predictions[example.example_id] = pad([item.video_id for item in ranked], args.top_k, example.example_id)
        found = [video_id for video_id in example.seed_video_ids if video_id in embeddings]
        diagnostics.append({
            "example_id": example.example_id,
            "seed_count": len(example.seed_video_ids),
            "embedded_seed_count": len(found),
            "seed_vector_sources": dict(Counter(str(args.embeddings[origin[v]]) for v in found)),
            "missing_seed_ids": list(missing),
            "mode": "no_seed_vectors" if seed_vector is None else "seed_centroid",
            "recommendations": [{"video_id": item.video_id, "score": item.score} for item in ranked],
        })
    unembedded = [row["example_id"] for row in diagnostics if row["mode"] == "no_seed_vectors"]
    if unembedded:
        print(f"WARNING: no seed vectors for examples {unembedded}; their lists are padding only", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(predictions, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps({
        "schema_version": 1, "method": "seed_centroid_cosine",
        "inputs": str(args.inputs), "references": str(args.references),
        "embeddings": [str(path) for path in args.embeddings],
        "song_vector_count": len(embeddings), "candidate_count": len(candidate_ids),
        "top_k": args.top_k, "examples": diagnostics,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(predictions)} prediction lists to {args.output}")


if __name__ == "__main__":
    main()
