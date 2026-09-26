"""Tests for playlist pairing, the similarity recommender and scoring."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import enrich  # noqa: E402
from benchmark import (  # noqa: E402
    CachedSimilar,
    evaluate,
    pair_playlists,
    recommend_similar,
    track_key,
)


def pl(name, pid):
    return {"name": name, "id": pid}


class TestPairPlaylists:
    def test_pairs_seed_and_recs_by_name(self):
        pairs = pair_playlists([pl("seed: Jazz", "s1"), pl("recs: Jazz", "r1")])
        assert pairs == {"jazz": {"seed": "s1", "recs": "r1"}}

    def test_case_and_spacing_are_forgiven(self):
        pairs = pair_playlists([pl("SEED:  Night Drive ", "s1"), pl("Recs:night drive", "r1")])
        assert pairs == {"night drive": {"seed": "s1", "recs": "r1"}}

    def test_seed_without_recs(self):
        assert pair_playlists([pl("seed: solo", "s1")]) == {"solo": {"seed": "s1", "recs": None}}

    def test_orphan_recs_and_other_playlists_ignored(self):
        assert pair_playlists([pl("recs: lonely", "r1"), pl("My Mix", "x")]) == {}


class TestTrackKey:
    def test_ignores_feat_case_and_curly_quotes(self):
        assert track_key("Rihanna", "Same Ol’ Mistakes (feat. X)") == \
            track_key("rihanna", "same ol' mistakes")

    def test_different_songs_differ(self):
        assert track_key("A", "One") != track_key("A", "Two")


def fake_similar(table):
    return lambda artist, title: table.get((artist, title), [])


class TestRecommendSimilar:
    SEEDS = [("A", "a1"), ("A", "a2"), ("B", "b1")]
    TABLE = {
        ("A", "a1"): [("C", "c1", 0.5), ("A", "a3", 0.8), ("B", "b1", 1.0)],
        ("A", "a2"): [("C", "c1", 0.4), ("D", "d1", 0.6)],
        ("B", "b1"): [("E", "e1", 0.3)],
    }

    def test_sums_scores_across_seeds_and_ranks(self):
        recs = recommend_similar(self.SEEDS, fake_similar(self.TABLE))
        assert [r[:2] for r in recs] == [("C", "c1"), ("A", "a3"), ("D", "d1"), ("E", "e1")]
        assert recs[0][2] == 0.9  # 0.5 + 0.4

    def test_never_recommends_a_seed_track(self):
        recs = recommend_similar(self.SEEDS, fake_similar(self.TABLE))
        assert ("B", "b1") not in [r[:2] for r in recs]

    def test_can_exclude_seed_artists(self):
        recs = recommend_similar(self.SEEDS, fake_similar(self.TABLE),
                                 exclude_seed_artists=True)
        assert all(r[0] not in ("A", "B") for r in recs)

    def test_top_n(self):
        assert len(recommend_similar(self.SEEDS, fake_similar(self.TABLE), top_n=2)) == 2


class TestEvaluate:
    def test_hits_precision_recall(self):
        recommended = [("C", "c1", 1.0), ("D", "d1", 0.5), ("X", "x1", 0.1), ("Y", "y1", 0.1)]
        reference = [("C", "c1"), ("D", "d9"), ("Z", "z1")]
        m = evaluate(recommended, reference)
        assert m["hits"] == 1
        assert m["precision"] == 0.25 and m["recall"] == 1 / 3
        assert m["artist_recall"] == 2 / 3  # reached C and D, missed Z

    def test_matches_through_normalisation(self):
        m = evaluate([("Rihanna", "Same Ol’ Mistakes", 1.0)],
                     [("rihanna", "Same Ol' Mistakes (feat. X)")])
        assert m["hits"] == 1

    def test_empty_inputs(self):
        assert evaluate([], [])["recall"] == 0.0


class TestCachedSimilar:
    def test_caches_and_persists(self, tmp_path):
        lookup = MagicMock(return_value=[("C", "c1", 0.5)])
        path = tmp_path / "cache.json"
        cached = CachedSimilar(lookup, path)
        cached("A", "a1")
        cached("A", "a1")
        assert lookup.call_count == 1
        cached.save()
        again = CachedSimilar(lookup, path)
        assert [tuple(x) for x in again("A", "a1")] == [("C", "c1", 0.5)]
        assert lookup.call_count == 1


class TestLastFmSimilarTracks:
    def test_parses_and_falls_back_to_clean_title(self, monkeypatch):
        http = MagicMock()
        http.get.return_value.json.side_effect = [
            {"error": 6, "message": "Track not found"},
            {"similartracks": {"track": [{"name": "Nikes", "match": "0.95",
                                          "artist": {"name": "Frank Ocean"}}]}},
        ]
        monkeypatch.setattr(enrich, "requests", http)
        client = enrich.LastFM(api_key="k", min_interval=0)
        assert client.similar_tracks("Frank Ocean", "Nights (Live)") == \
            [("Frank Ocean", "Nikes", 0.95)]

    def test_unknown_track_gives_empty(self, monkeypatch):
        http = MagicMock()
        http.get.return_value.json.return_value = {"error": 6, "message": "no"}
        monkeypatch.setattr(enrich, "requests", http)
        assert enrich.LastFM(api_key="k", min_interval=0).similar_tracks("x", "y") == []
