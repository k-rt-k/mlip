"""Tests for the enrichment API clients (no network; HTTP is mocked)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import enrich  # noqa: E402
from enrich import GetSongBPM, LastFM, enrich_track  # noqa: E402


@pytest.fixture
def http(monkeypatch):
    """Patch enrich.requests.get; test sets .json return values per call."""
    mock = MagicMock()
    mock.get.return_value.raise_for_status = MagicMock()
    monkeypatch.setattr(enrich, "requests", mock)
    return mock


def gsb(http, **kw):
    client = GetSongBPM(api_key="k", min_interval=0)
    for name, value in kw.items():
        setattr(client, name, value)
    return client


SEARCH_HIT = {
    "song_id": "s1",
    "song_title": "Nights",
    "tempo": "89",
    "artist": {"name": "Frank Ocean", "genres": ["r&b", "pop"], "mbid": "m1"},
}
SONG_DETAIL = {
    "song": {
        "id": "s1",
        "tempo": "89",
        "time_sig": "4/4",
        "key_of": "F#m",
        "open_key": "11m",
        "danceability": 60,
        "acousticness": 30,
        "artist": {"name": "Frank Ocean", "genres": ["r&b", "pop"], "mbid": "m1"},
    }
}


class TestGetSongBPM:
    def test_lookup_track_normalizes(self, http):
        http.get.return_value.json.side_effect = [{"search": [SEARCH_HIT]}, SONG_DETAIL]
        result = gsb(http).lookup_track("Frank Ocean", "Nights")
        assert result["tempo"] == 89.0
        assert result["key"] == "F#m"
        assert result["danceability"] == 60
        assert result["genres"] == ["r&b", "pop"]
        assert result["mbid"] == "m1"

    def test_lookup_track_no_match_returns_none(self, http):
        # API signals no results with an error dict instead of a list.
        http.get.return_value.json.return_value = {"search": {"error": "no result"}}
        assert gsb(http).lookup_track("x", "y") is None

    def test_api_key_sent_as_param(self, http):
        http.get.return_value.json.return_value = {"search": {"error": "no result"}}
        gsb(http).lookup_track("a", "t")
        assert http.get.call_args.kwargs["params"]["api_key"] == "k"

    def test_missing_env_key_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GETSONGBPM_API_KEY", raising=False)
        monkeypatch.setattr(enrich, "ENV_PATH", tmp_path / ".env")
        with pytest.raises(RuntimeError, match="GETSONGBPM_API_KEY"):
            GetSongBPM()


class TestLastFM:
    def test_track_tags_ordered_by_weight(self, http):
        http.get.return_value.json.return_value = {
            "toptags": {"tag": [{"name": "soul", "count": 100}, {"name": "rnb", "count": 60}]}
        }
        client = LastFM(api_key="k", min_interval=0)
        assert client.track_tags("Frank Ocean", "Nights") == [("soul", 100), ("rnb", 60)]

    def test_track_tags_missing_track_is_empty(self, http):
        http.get.return_value.json.return_value = {"error": 6, "message": "Track not found"}
        client = LastFM(api_key="k", min_interval=0)
        assert client.track_tags("x", "y") == []

    def test_missing_env_key_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LASTFM_API_KEY", raising=False)
        monkeypatch.setattr(enrich, "ENV_PATH", tmp_path / ".env")
        with pytest.raises(RuntimeError, match="LASTFM_API_KEY"):
            LastFM()


class TestEnrichTrack:
    def test_merges_both_sources(self, http):
        http.get.return_value.json.side_effect = [
            {"search": [SEARCH_HIT]},
            SONG_DETAIL,
            {"toptags": {"tag": [{"name": "soul", "count": 100}]}},
        ]
        merged = enrich_track(
            "Frank Ocean", "Nights",
            gsb=GetSongBPM(api_key="k", min_interval=0),
            lastfm=LastFM(api_key="k", min_interval=0),
        )
        assert merged["tempo"] == 89.0
        assert merged["genres"] == ["r&b", "pop"]
        assert merged["tags"] == [("soul", 100)]

    def test_gsb_miss_still_returns_tags(self, http):
        http.get.return_value.json.side_effect = [
            {"search": {"error": "no result"}},
            {"toptags": {"tag": [{"name": "soul", "count": 100}]}},
        ]
        merged = enrich_track(
            "a", "t",
            gsb=GetSongBPM(api_key="k", min_interval=0),
            lastfm=LastFM(api_key="k", min_interval=0),
        )
        assert merged["tempo"] is None
        assert merged["tags"] == [("soul", 100)]
