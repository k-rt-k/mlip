"""No-training query fusion and reranking for playlist continuation."""

from dataclasses import dataclass

import numpy as np

from retrieval.catalog import normalized_vectors


@dataclass(frozen=True)
class Recommendation:
    video_id: str
    score: float


def mean_seed_vector(seed_ids: tuple[str, ...], embeddings: dict[str, np.ndarray]) -> tuple[np.ndarray | None, tuple[str, ...]]:
    """Mean-pool available seed vectors and report IDs missing cached audio."""
    found = [embeddings[video_id] for video_id in seed_ids if video_id in embeddings]
    missing = tuple(video_id for video_id in seed_ids if video_id not in embeddings)
    if not found:
        return None, missing
    return normalized_vectors(np.mean(found, axis=0, keepdims=True))[0], missing


def fused_query(prompt_vector: np.ndarray, seed_vector: np.ndarray | None, prompt_weight: float) -> np.ndarray:
    """Blend text and playlist intent; no seed vector means transparent text fallback."""
    if not 0.0 <= prompt_weight <= 1.0:
        raise ValueError("prompt_weight must lie in [0, 1]")
    prompt = normalized_vectors(np.asarray(prompt_vector).reshape(1, -1))[0]
    if seed_vector is None:
        return prompt
    seed = normalized_vectors(np.asarray(seed_vector).reshape(1, -1), dimension=len(prompt))[0]
    return normalized_vectors((prompt_weight * prompt + (1 - prompt_weight) * seed).reshape(1, -1))[0]


def rank_candidates(
    *,
    candidate_ids: tuple[str, ...],
    candidate_vectors: np.ndarray,
    query: np.ndarray,
    seed_vector: np.ndarray | None,
    excluded_ids: tuple[str, ...],
    top_k: int,
    retrieve_k: int,
    rerank_seed_weight: float,
) -> list[Recommendation]:
    """Retrieve by fused intent then rerank candidates by playlist coherence."""
    if not 0.0 <= rerank_seed_weight <= 1.0:
        raise ValueError("rerank_seed_weight must lie in [0, 1]")
    if top_k <= 0 or retrieve_k < top_k:
        raise ValueError("retrieve_k must be at least top_k and both must be positive")
    vectors = normalized_vectors(candidate_vectors)
    query = normalized_vectors(np.asarray(query).reshape(1, -1), dimension=vectors.shape[1])[0]
    initial = vectors @ query
    # Stable secondary key makes ties reproducible without depending on NumPy's sort.
    rows = sorted(range(len(candidate_ids)), key=lambda row: (-float(initial[row]), candidate_ids[row]))[:retrieve_k]
    excluded = set(excluded_ids)
    if seed_vector is not None:
        seed = normalized_vectors(np.asarray(seed_vector).reshape(1, -1), dimension=vectors.shape[1])[0]
        seed_scores = vectors @ seed
    else:
        seed_scores = initial
    scored = [
        Recommendation(candidate_ids[row], float((1 - rerank_seed_weight) * initial[row] + rerank_seed_weight * seed_scores[row]))
        for row in rows if candidate_ids[row] not in excluded
    ]
    return sorted(scored, key=lambda item: (-item.score, item.video_id))[:top_k]
