"""Retrieval correctness and integrity checks; no audio or model downloads."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import faiss
import numpy as np
import pytest

from retrieval import EmbeddingCatalog, IndexConfig, RetrievalIndex, load_embeddings
from retrieval.benchmark import ann_recall, compare


def normalized(rng, n, d=12):
    x = rng.normal(size=(n, d)).astype("float32")
    return x / np.linalg.norm(x, axis=1, keepdims=True)


@pytest.fixture
def corpus():
    return EmbeddingCatalog(
        [f"song-{i}" for i in range(256)], normalized(np.random.default_rng(8), 256)
    )


@pytest.fixture
def configs():
    return [
        IndexConfig("exact"),
        IndexConfig("ivf", nlist=4, nprobe=4, training_sample_size=200, seed=7),
        IndexConfig("hnsw", m=16, ef_construction=80, ef_search=80),
    ]


def test_loading_shards_preserves_file_and_row_order(tmp_path):
    for name, ids in [
        ("shard-1/chunk-0.npz", ["z", "b"]),
        ("shard-0/chunk-0.npz", ["a"]),
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True)
        np.savez(path, ids=ids, vectors=np.tile([3.0, 4.0], (len(ids), 1)))
    c = load_embeddings(tmp_path)
    assert c.ids == ("a", "z", "b")
    np.testing.assert_allclose(c.vectors, [[0.6, 0.8]] * 3)
    assert load_embeddings(tmp_path, limit=2).ids == ("a", "z")
    assert c.fingerprint == load_embeddings(tmp_path).fingerprint


def test_duplicate_ids_across_shards_are_rejected(tmp_path):
    for n in range(2):
        np.savez(tmp_path / f"{n}.npz", ids=["duplicate"], vectors=[[1.0, 0.0]])
    with pytest.raises(ValueError, match="duplicate"):
        load_embeddings(tmp_path)


def test_normalization_is_idempotent_and_independent_of_batch():
    first = EmbeddingCatalog(["a"], [[1.0, 2.0, 3.0]])
    restored = EmbeddingCatalog(first.ids, first.vectors)
    assert first.fingerprint == restored.fingerprint
    mixed = EmbeddingCatalog(["a", "b"], np.vstack([first.vectors, [[3.0, 4.0, 5.0]]]))
    np.testing.assert_array_equal(first.vectors[0], mixed.vectors[0])


@pytest.mark.parametrize(
    "vectors",
    [
        [[0.0, 0.0]],
        [[np.nan, 1.0]],
        [[np.inf, 1.0]],
        [[1e300, 1.0]],
        [1.0, 2.0],
        [[1 + 2j, 0]],
    ],
)
def test_bad_vectors_are_rejected(vectors):
    with pytest.raises(ValueError):
        EmbeddingCatalog(["a"], vectors)


def test_id_and_dimension_validation(tmp_path):
    for ids in [[""], ["x", "x"], [None], [1]]:
        with pytest.raises(ValueError):
            EmbeddingCatalog(ids, np.ones((len(ids), 2)))
    with pytest.raises(ValueError):
        EmbeddingCatalog(["x"], np.ones((2, 3)))
    with pytest.raises(ValueError):
        EmbeddingCatalog([], np.empty((0, 3)))
    with pytest.raises(FileNotFoundError):
        load_embeddings(tmp_path)
    np.savez(tmp_path / "a.npz", ids=["a"], vectors=[[1.0, 0.0]])
    np.savez(tmp_path / "b.npz", ids=["b"], vectors=[[1.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="dimension"):
        load_embeddings(tmp_path)


def test_exact_matches_independent_cosine_calculation(corpus):
    queries = np.random.default_rng(11).normal(size=(7, 12)).astype("float32") * 10
    before = queries.copy()
    result = RetrievalIndex.build(corpus, IndexConfig("exact")).search(queries, 9)
    expected = (
        queries / np.linalg.norm(queries, axis=1, keepdims=True)
    ) @ corpus.vectors.T
    rows = np.argsort(-expected, axis=1)[:, :9]
    np.testing.assert_array_equal(result.rows, rows)
    np.testing.assert_allclose(
        result.scores, np.take_along_axis(expected, rows, axis=1), atol=2e-6
    )
    assert result.song_ids[0] == tuple(corpus.ids[i] for i in rows[0])
    np.testing.assert_array_equal(queries, before)


def test_all_indexes_use_ip_and_round_trip(corpus, configs, tmp_path):
    faiss.omp_set_num_threads(1)
    queries = normalized(np.random.default_rng(12), 8)
    for config in configs:
        index = RetrievalIndex.build(corpus, config)
        assert index.index.metric_type == faiss.METRIC_INNER_PRODUCT
        np.testing.assert_array_equal(
            index.search(corpus.vectors[:8], 1).rows[:, 0], np.arange(8)
        )
        first = index.search(queries, 5)
        if config.method == "ivf":
            exact = RetrievalIndex.build(corpus, configs[0]).search(queries, 5)
            np.testing.assert_array_equal(first.rows, exact.rows)
            assert index.build_info["training_sample_size"] == 200
            assert index.build_info["training_seed"] == 7
        folder = tmp_path / config.method
        index.save(folder)
        restored = RetrievalIndex.load(folder)
        assert restored.config == config
        assert restored.corpus_fingerprint == corpus.fingerprint
        second = restored.search(queries, 5)
        np.testing.assert_array_equal(first.rows, second.rows)
        np.testing.assert_allclose(first.scores, second.scores)
        assert first.song_ids == second.song_ids
        with pytest.raises(FileExistsError):
            index.save(folder)


def test_persistence_detects_mixed_or_changed_mapping(corpus, tmp_path):
    index = RetrievalIndex.build(corpus, IndexConfig("exact"))
    index.save(tmp_path / "index")
    mapping = tmp_path / "index/catalog.json"
    ids = json.loads(mapping.read_text())
    ids[0], ids[1] = ids[1], ids[0]
    mapping.write_text(json.dumps(ids))
    with pytest.raises(ValueError, match="checksum"):
        RetrievalIndex.load(tmp_path / "index")


def test_ivf_training_is_repeatable_with_fixed_seed(corpus):
    faiss.omp_set_num_threads(1)
    config = IndexConfig("ivf", nlist=4, nprobe=1, training_sample_size=200, seed=9)
    first = RetrievalIndex.build(corpus, config)
    second = RetrievalIndex.build(corpus, config)
    np.testing.assert_array_equal(
        first.search(corpus.vectors[:12], 5).rows,
        second.search(corpus.vectors[:12], 5).rows,
    )
    np.testing.assert_array_equal(
        first.index.quantizer.reconstruct_n(0, 4),
        second.index.quantizer.reconstruct_n(0, 4),
    )


def test_persistence_detects_changed_hnsw_construction_config(corpus, tmp_path):
    config = IndexConfig("hnsw", m=16, ef_construction=80, ef_search=80)
    RetrievalIndex.build(corpus, config).save(tmp_path / "index")
    path = tmp_path / "index/metadata.json"
    metadata = json.loads(path.read_text())
    metadata["config"]["m"] = 32
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="HNSW construction"):
        RetrievalIndex.load(tmp_path / "index")


def test_missing_ivf_neighbors_never_become_last_song(corpus):
    index = RetrievalIndex.build(corpus, IndexConfig("ivf", nlist=4, nprobe=1))
    result = index.search(corpus.vectors[:1], 256)
    assert (result.rows == -1).any()
    for row, song_id, score in zip(
        result.rows[0], result.song_ids[0], result.scores[0]
    ):
        if row == -1:
            assert song_id is None and np.isneginf(score)


def test_search_validation_and_empty_queries(corpus):
    index = RetrievalIndex.build(corpus, IndexConfig("exact"))
    for q, k in [
        (np.zeros((1, 12)), 5),
        (np.ones((1, 11)), 5),
        (np.ones((1, 12)), 0),
        (np.ones((1, 12)), 257),
        (np.ones(12), 5),
        (np.ones((1, 12)), 1.5),
    ]:
        with pytest.raises(ValueError):
            index.search(q, k)
    assert index.search(np.empty((0, 12)), 5).rows.shape == (0, 5)


def test_runtime_tuning_does_not_rebuild(corpus, configs):
    for config, kwargs in [
        (configs[1], {"nprobe": 1}),
        (configs[2], {"ef_search": 120}),
    ]:
        index = RetrievalIndex.build(corpus, config)
        native = index.index
        index.set_search_parameters(**kwargs)
        assert index.index is native
        assert index.config == replace(config, **kwargs)
    with pytest.raises(ValueError):
        index.set_search_parameters(nprobe=3)
    with pytest.raises(ValueError):
        IndexConfig("ivf", nlist=2, nprobe=3)
    with pytest.raises(ValueError):
        RetrievalIndex.build(corpus, IndexConfig("ivf", nlist=300, nprobe=1))


def test_ann_recall_handles_duplicates_and_missing_results():
    exact = np.array([[1, 2, 3], [4, 5, 6]])
    approximate = np.array([[1, 1, -1], [6, 5, 4]])
    assert ann_recall(approximate, exact) == pytest.approx(2 / 3)


def test_benchmark_uses_same_queries_and_reuses_builds(corpus, configs, tmp_path):
    np.savez(tmp_path / "corpus.npz", ids=corpus.ids, vectors=corpus.vectors)
    np.savez(
        tmp_path / "queries.npz",
        ids=["q1", "q2", "q3"],
        vectors=normalized(np.random.default_rng(6), 3),
    )
    report = compare(
        tmp_path / "corpus.npz",
        tmp_path / "queries.npz",
        [configs[1], replace(configs[1], nprobe=1), configs[2]],
        k=5,
        repeats=2,
        warmups=1,
        threads=1,
        artifacts_dir=tmp_path / 'artifacts',
    )
    assert len(report["results"]) == 4  # exact reference automatically included
    for record in report['results']:
        saved = json.loads(Path(record['predictions_path']).read_text())
        assert saved['query_ids'] == ['q1', 'q2', 'q3']
        assert len(saved['song_ids']) == 3
        assert len(saved['song_ids'][0]) == 5
        assert saved['corpus_fingerprint'] == corpus.fingerprint
        restored = RetrievalIndex.load(record['index_path'])
        restored.set_search_parameters(nprobe=record['config']['nprobe'],
                                       ef_search=record['config']['ef_search'])
        q = load_embeddings(tmp_path / 'queries.npz')
        assert [list(s) for s in restored.search(q.vectors, 5).song_ids] == saved['song_ids']
        assert record['ann_recall_at_cutoffs']['5'] == record['ann_recall_at_k']
    assert report["results"][0]["ann_recall_at_k"] == 1
    ivf = [r for r in report["results"] if r["config"]["method"] == "ivf"]
    assert ivf[0]["build_id"] == ivf[1]["build_id"]
    assert all(r["corpus_fingerprint"] == corpus.fingerprint for r in report["results"])
    assert all(r["latency_ms"]["count"] == 6 for r in report["results"])
    assert all(
        r["index_file_bytes"] > 0 and r["process_peak_rss_bytes"] > 0
        for r in report["results"]
    )
    assert (
        report["results"][0]["queries_fingerprint"]
        == report["results"][-1]["queries_fingerprint"]
    )


def test_cli_build_search_and_missing_ivf_results_are_json_null(corpus, tmp_path):
    np.savez(tmp_path / "c.npz", ids=corpus.ids, vectors=corpus.vectors)
    np.savez(tmp_path / "q.npz", ids=["query"], vectors=corpus.vectors[:1])
    subprocess.run(
        [
            sys.executable,
            "-m",
            "retrieval",
            "build",
            "--corpus",
            str(tmp_path / "c.npz"),
            "--output",
            str(tmp_path / "idx"),
            "--method",
            "ivf",
            "--nlist",
            "4",
            "--nprobe",
            "1",
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "retrieval",
            "search",
            "--index",
            str(tmp_path / "idx"),
            "--queries",
            str(tmp_path / "q.npz"),
            "--k",
            "256",
            "--output",
            str(tmp_path / "hits.json"),
        ],
        check=True,
    )
    hits = json.loads((tmp_path / "hits.json").read_text())
    assert hits["query_ids"] == ["query"]
    assert None in hits["song_ids"][0]
    assert None in hits["scores"][0]


def test_catalog_import_does_not_load_faiss():
    subprocess.run(
        [sys.executable, "-c", "import sys; from retrieval import load_embeddings; assert 'faiss' not in sys.modules"],
        check=True,
    )
