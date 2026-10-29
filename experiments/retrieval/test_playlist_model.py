import numpy as np

from experiments.retrieval.playlist_model import fused_query, mean_seed_vector, rank_candidates


def test_seed_mean_and_fusion_are_normalized():
    vectors = {"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0])}
    seed, missing = mean_seed_vector(("a", "b", "missing"), vectors)
    assert missing == ("missing",)
    np.testing.assert_allclose(seed, [2**-0.5, 2**-0.5])
    query = fused_query(np.array([1.0, 0.0]), seed, 0.5)
    np.testing.assert_allclose(np.linalg.norm(query), 1.0)


def test_ranking_excludes_seeds_and_reranks_first_stage():
    ranked = rank_candidates(
        candidate_ids=("seed", "text", "both", "outside"),
        candidate_vectors=np.array([[1., 0.], [1., .1], [.8, .8], [0., 1.]]),
        query=np.array([1., 0.]), seed_vector=np.array([0., 1.]),
        excluded_ids=("seed",), top_k=2, retrieve_k=3, rerank_seed_weight=.5,
    )
    assert [item.video_id for item in ranked] == ["both", "text"]
