"""Evaluation metric definitions for recommendation/continuation quality."""

import math
from typing import Iterable, List, Set, TypeVar, Union

T = TypeVar("T")


def precision_at_k(recommended: List[T], ground_truth: Set[T], k: int = 5) -> float:
    """Computes Precision@K.
    
    Fraction of recommended items in top-K that are relevant.
    """
    if k <= 0:
        return 0.0
        
    top_k = recommended[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for item in top_k if item in ground_truth)
    return hits / float(k)


def recall_at_k(recommended: List[T], ground_truth: Set[T], k: int = 5) -> float:
    """Computes Recall@K.
    
    Fraction of ground truth items retrieved in top-K recommendations.
    """
    if not ground_truth or k <= 0:
        return 0.0
    top_k = recommended[:k]
    hits = sum(1 for item in top_k if item in ground_truth)
    return hits / float(len(ground_truth))


def hit_rate_at_k(recommended: List[T], ground_truth: Set[T], k: int = 5) -> float:
    """Computes Hit Rate@K (Binary Indicator).
    
    Returns 1.0 if at least one ground truth item is in top-K, else 0.0.
    """
    top_k = recommended[:k]
    return 1.0 if any(item in ground_truth for item in top_k) else 0.0


def r_precision(recommended: List[T], ground_truth: Set[T]) -> float:
    """Computes R-Precision.
    
    Precision evaluated at K = len(ground_truth).
    Used extensively in Spotify MPD / playlist continuation benchmarks.
    """
    r = len(ground_truth)
    if r == 0:
        return 0.0
    top_r = recommended[:r]
    hits = sum(1 for item in top_r if item in ground_truth)
    return hits / float(r)


def map_at_k(recommended: List[T], ground_truth: Set[T], k: int = 5) -> float:
    """Computes Average Precision@K (AP@K) for a single example.
    
    When averaged across all evaluation examples, this yields MAP@K.
    Nominator normalizes by min(k, len(ground_truth)) per standard RecSys protocols.
    """
    if not ground_truth or k <= 0:
        return 0.0

    top_k = recommended[:k]
    hits = 0
    sum_precisions = 0.0

    for idx, item in enumerate(top_k, start=1):
        if item in ground_truth:
            hits += 1
            sum_precisions += hits / float(idx)

    # Standard denominator is the maximum possible hits achievable at cut-off k
    denominator = min(len(ground_truth), k)
    return sum_precisions / float(denominator) if denominator > 0 else 0.0


def ndcg_at_k(recommended: List[T], ground_truth: Set[T], k: int = 5) -> float:
    """Computes Normalized Discounted Cumulative Gain@K (NDCG@K).
    
    Uses standard binary relevance with logarithmic rank decay (log2(rank + 1)).
    """
    if not ground_truth or k <= 0:
        return 0.0

    top_k = recommended[:k]
    
    # 1. Compute Discounted Cumulative Gain (DCG)
    dcg = 0.0
    for idx, item in enumerate(top_k, start=1):
        if item in ground_truth:
            dcg += 1.0 / math.log2(idx + 1)

    # 2. Compute Ideal Discounted Cumulative Gain (IDCG)
    ideal_hits = min(len(ground_truth), k)
    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_hits + 1))

    if idcg == 0.0:
        return 0.0

    return dcg / idcg


def calculate_all_metrics(
    recommended: List[str], 
    ground_truth: Iterable[str], 
    k: Union[int, List[int]] = 5
) -> dict:
    """Evaluates a single prediction list against ground truth across all metrics.
    
    Can evaluate a single int k (e.g. k=5) or a list of cutoffs (e.g. k=[1, 5, 10]).
    """
    gt_set = set(ground_truth)
    k_list = [k] if isinstance(k, int) else k

    max_k = max(k_list)
    if len(recommended) < max_k:
        raise ValueError(
            f"Recommended list length ({len(recommended)}) is less than "
            f"the maximum k ({max_k})."
        )

    results = {}
    for cutoff in k_list:
        results[f"precision@{cutoff}"] = precision_at_k(recommended, gt_set, k=cutoff)
        results[f"recall@{cutoff}"] = recall_at_k(recommended, gt_set, k=cutoff)
        results[f"hit_rate@{cutoff}"] = hit_rate_at_k(recommended, gt_set, k=cutoff)
        results[f"map@{cutoff}"] = map_at_k(recommended, gt_set, k=cutoff)
        results[f"ndcg@{cutoff}"] = ndcg_at_k(recommended, gt_set, k=cutoff)

    # R-precision is evaluated at K = len(ground_truth)
    results["r_precision"] = r_precision(recommended, gt_set)

    return results