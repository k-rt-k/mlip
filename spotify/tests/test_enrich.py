"""Tests for the enrichment API clients (no network; HTTP is mocked)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import enrich  # noqa: E402
from enrich import (  # noqa: E402
    GetSongBPM,
    LastFM,
    ascii_fold,
    clean_title,
    enrich_track,
    title_variants,
)


class TestAsciiFold:
    def test_curly_apostrophe(self):
        assert ascii_fold("Same Ol’ Mistakes") == "Same Ol' Mistakes"

    def test_diacritics(self):
        assert ascii_fold("Thème Rythme Léger") == "Theme Rythme Leger"

    def test_never_returns_empty(self):
        assert ascii_fold("マフィア") == "マフィア"


class TestSearchVariants:
    def test_honorific_and_punct_variants(self):
        pairs = GetSongBPM._search_variants("Ms. Lauryn Hill", "Ex-Factor")
        assert pairs[0] == ("Ms. Lauryn Hill", "Ex-Factor")
        assert ("Lauryn Hill", "Ex-Factor") in pairs
        assert ("Lauryn Hill", "Ex‐Factor") in pairs

    def test_plain_names_collapse_to_one(self):
        assert GetSongBPM._search_variants("Frank Ocean", "Nights") == [
            ("Frank Ocean", "Nights")
        ]

    def test_aka_gets_trailing_period(self):
        pairs = GetSongBPM._search_variants(
            "Kendrick Lamar", "Sherane a.k.a Master Splinter’s Daughter"
        )
        assert ("Kendrick Lamar", "Sherane a.k.a. Master Splinter's Daughter") in pairs

    def test_aka_already_dotted_unchanged(self):
        from enrich import dot_aka
        assert dot_aka("Sherane a.k.a. Daughter") == "Sherane a.k.a. Daughter"


class TestTitleVariants:
    def test_ordered_and_deduped(self):
        assert title_variants("Same Ol’ Mistakes (Live)") == [
            "Same Ol’ Mistakes (Live)",
            "Same Ol’ Mistakes",
            "Same Ol' Mistakes",
        ]

    def test_plain_title_single_variant(self):
        assert title_variants("Nights") == ["Nights"]


class TestCleanTitle:
    def test_strips_feat_parenthetical(self):
        assert clean_title("SIR BAUDELAIRE (feat. DJ Drama)") == "SIR BAUDELAIRE"

    def test_strips_dash_suffix(self):
        assert clean_title("Nights - 2019 Remaster") == "Nights"

    def test_plain_title_unchanged(self):
        assert clean_title("Nights") == "Nights"

    def test_hyphenated_word_kept(self):
        assert clean_title("Twenty-One") == "Twenty-One"

    def test_never_returns_empty(self):
        assert clean_title("(Intro)") == "(Intro)"


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

    def test_track_info_falls_back_to_clean_title(self, http):
        http.get.return_value.json.side_effect = [
            {"error": 6, "message": "Track not found"},           # raw title
            {"track": {"listeners": "5", "playcount": "9"}},      # cleaned
        ]
        client = LastFM(api_key="k", min_interval=0)
        info = client.track_info("The Weeknd", "Open Hearts (Live)")
        assert info == {"listeners": "5", "playcount": "9"}

    def test_track_info_none_when_unknown(self, http):
        http.get.return_value.json.return_value = {"error": 6, "message": "no"}
        client = LastFM(api_key="k", min_interval=0)
        assert client.track_info("x", "y") is None


def dispatch_by_url(gsb_search, gsb_song, lastfm_tags, lastfm_info):
    """URL-keyed mock responses — enrich_track's API chains run concurrently,
    so ordered side_effect lists would be racy."""
    def fake_get(url, params=None, timeout=None):
        response = MagicMock()
        if "getsong" in url:
            response.json.return_value = gsb_song if "/song/" in url else gsb_search
        elif params.get("method") == "track.gettoptags":
            response.json.return_value = lastfm_tags
        else:
            response.json.return_value = lastfm_info
        return response
    return fake_get


class TestEnrichTrack:
    def test_merges_both_sources(self, http):
        http.get.side_effect = dispatch_by_url(
            {"search": [SEARCH_HIT]}, SONG_DETAIL,
            {"toptags": {"tag": [{"name": "soul", "count": 100}]}},
            {"track": {"listeners": "800", "playcount": "9000"}},
        )
        merged = enrich_track(
            "Frank Ocean", "Nights",
            gsb=GetSongBPM(api_key="k", min_interval=0),
            lastfm=LastFM(api_key="k", min_interval=0),
        )
        assert merged["tempo"] == 89.0
        assert merged["genres"] == ["r&b", "pop"]
        assert merged["tags"] == [("soul", 100)]
        assert merged["listeners"] == 800
        assert merged["playcount"] == 9000

    def test_gsb_miss_still_returns_tags(self, http):
        http.get.side_effect = dispatch_by_url(
            {"search": {"error": "no result"}}, {},
            {"toptags": {"tag": [{"name": "soul", "count": 100}]}},
            {"error": 6, "message": "Track not found"},
        )
        merged = enrich_track(
            "a", "t",
            gsb=GetSongBPM(api_key="k", min_interval=0),
            lastfm=LastFM(api_key="k", min_interval=0),
        )
        assert merged["tempo"] is None
        assert merged["tags"] == [("soul", 100)]
        assert merged["listeners"] is None
