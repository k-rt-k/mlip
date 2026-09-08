"""Tests for the SpotifyClient wrapper (no network; spotipy is mocked)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from client import (  # noqa: E402
    BLOCKED_METHODS,
    DeprecatedEndpointError,
    SpotifyClient,
    unwrap_item,
)
import auth  # noqa: E402


def make_sp(pages):
    """Mock spotipy.Spotify whose next() walks a canned list of pages."""
    sp = MagicMock()
    sp.next.side_effect = lambda page: pages[pages.index(page) + 1]
    return sp


def page(items, has_next=True):
    return {"items": items, "next": "url" if has_next else None}


class TestPagination:
    def test_follows_next_pages(self):
        pages = [page([1, 2]), page([3, 4]), page([5], has_next=False)]
        sp = make_sp(pages)
        client = SpotifyClient(sp)
        assert client._paginate(pages[0]) == [1, 2, 3, 4, 5]

    def test_respects_max_items(self):
        pages = [page([1, 2]), page([3, 4], has_next=False)]
        sp = make_sp(pages)
        client = SpotifyClient(sp)
        assert client._paginate(pages[0], max_items=3) == [1, 2, 3]

    def test_single_page(self):
        sp = MagicMock()
        client = SpotifyClient(sp)
        assert client._paginate(page([1], has_next=False)) == [1]
        sp.next.assert_not_called()


class TestDeprecationBlocking:
    def test_blocked_method_raises(self):
        client = SpotifyClient(MagicMock())
        for name in ("audio_features", "recommendations", "artist_related_artists"):
            with pytest.raises(DeprecatedEndpointError, match=name):
                getattr(client, name)

    def test_blocked_error_names_reason(self):
        client = SpotifyClient(MagicMock())
        with pytest.raises(DeprecatedEndpointError, match="Nov 2024"):
            client.audio_features
        with pytest.raises(DeprecatedEndpointError, match="Feb 2026"):
            client.new_releases

    def test_unknown_attr_is_plain_attribute_error(self):
        client = SpotifyClient(MagicMock())
        with pytest.raises(AttributeError):
            client.not_a_real_method

    def test_all_blocked_methods_have_reasons(self):
        assert all(isinstance(v, str) and v for v in BLOCKED_METHODS.values())


class TestWrapperMethods:
    def test_search_unwraps_typed_items(self):
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": [{"id": "t1"}], "next": None}}
        client = SpotifyClient(sp)
        assert client.search("query", type="track") == [{"id": "t1"}]

    def test_followed_artists_unwraps_nested_page(self):
        sp = MagicMock()
        sp.current_user_followed_artists.return_value = {
            "artists": {"items": [{"id": "a1"}], "next": None}
        }
        client = SpotifyClient(sp)
        assert client.followed_artists() == [{"id": "a1"}]

    def test_top_tracks_passes_time_range(self):
        sp = MagicMock()
        sp.current_user_top_tracks.return_value = page([{"id": "t1"}], has_next=False)
        client = SpotifyClient(sp)
        assert client.top_tracks(time_range="short_term") == [{"id": "t1"}]
        assert sp.current_user_top_tracks.call_args.kwargs["time_range"] == "short_term"


class TestUnwrapItem:
    def test_playlist_item_wrapper(self):
        assert unwrap_item({"item": {"id": "t1"}, "added_at": "x"}) == {"id": "t1"}

    def test_saved_track_wrapper(self):
        assert unwrap_item({"track": {"id": "t1"}}) == {"id": "t1"}

    def test_bare_track_passes_through(self):
        assert unwrap_item({"id": "t1", "name": "n"}) == {"id": "t1", "name": "n"}

    def test_local_file_none_item(self):
        assert unwrap_item({"item": None, "is_local": True}) is None


class TestAuthConfig:
    def test_scopes_cover_eda_needs(self):
        required = {
            "user-top-read",
            "user-library-read",
            "playlist-read-private",
            "user-follow-read",
            "user-read-recently-played",
        }
        assert required <= set(auth.SCOPES)

    def test_missing_client_id_raises_helpful_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
        monkeypatch.setattr(auth, "ENV_PATH", tmp_path / ".env")  # no .env file
        with pytest.raises(RuntimeError, match="SPOTIPY_CLIENT_ID"):
            auth.get_spotify()
