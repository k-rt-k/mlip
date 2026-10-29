import json

import numpy as np
import pytest

from experiments.retrieval.playlist_data import load_seed_inputs, merge_embeddings
from experiments.retrieval.playlist_model import fused_query, mean_seed_vector, rank_candidates


def test_merge_embeddings_keeps_earlier_sources_first():
    primary = {"a": np.array([1.0, 0.0])}
    fallback = {"a": np.array([0.0, 1.0]), "b": np.array([0.0, 1.0])}
    merged, sources = merge_embeddings([primary, fallback])
    np.testing.assert_allclose(merged["a"], [1.0, 0.0])
    assert sources == {"a": 0, "b": 1}
    with pytest.raises(ValueError):
        merge_embeddings([primary, {"c": np.array([1.0, 0.0, 0.0])}])


def test_seed_inputs_need_no_prompts_and_reject_hidden_tracks(tmp_path):
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps({"examples": [{"example_id": 1, "seed_tracks": [{"video_id": "a"}]}]}))
    [example] = load_seed_inputs(path)
    assert example.example_id == "1" and example.seed_video_ids == ("a",) and example.prompt == ""
    path.write_text(json.dumps({"examples": [{"example_id": 1, "seed_tracks": [{"video_id": "a"}],
                                              "held_out_tracks": []}]}))
    with pytest.raises(ValueError):
        load_seed_inputs(path)


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
