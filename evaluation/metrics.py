"""Evaluation metric definitions for recommendation/continuation quality."""

from typing import Iterable, List, Set, TypeVar

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
    if not ground_truth:
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


def calculate_all_metrics(recommended: List[str], ground_truth: Iterable[str], k: List[int] = [1, 5, 10, 20, 30]) -> dict:
    """Evaluates a single prediction list against ground truth across all metrics.
    
    To add a new metric to the system, register it here.
    """
    if len(recommended) < max(k):
        raise ValueError(
            f"Recommended list length ({len(recommended)}) is less than "
            f"the maximum k ({max(k)})."
        )
    gt_set = set(ground_truth)
    return {
        f"precision@{k}": precision_at_k(recommended, gt_set, k=k),
        f"recall@{k}": recall_at_k(recommended, gt_set, k=k),
        f"hit_rate@{k}": hit_rate_at_k(recommended, gt_set, k=k),
        "r_precision": r_precision(recommended, gt_set),
    }

