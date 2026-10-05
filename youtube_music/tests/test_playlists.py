"""Offline checks for reproducible splits and seed-only platform writes."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playlists import (  # noqa: E402
    clean_tracks,
    create_seed_playlist,
    get_suggestions,
    playlist_id,
    prepare_partial,
    verify_seed_playlist,
    make_client,
)


def track(video_id, **extra):
    return {"videoId": video_id, "title": video_id, "artists": [{"name": "Artist"}], **extra}


def test_playlist_identifiers_and_urls():
    assert playlist_id("VLPLexample") == "PLexample"
    assert playlist_id("https://music.youtube.com/playlist?list=PLexample") == "PLexample"
    with pytest.raises(ValueError):
        playlist_id("https://music.youtube.com/watch?v=song")
    with pytest.raises(ValueError):
        playlist_id("../../outside")


def test_cleaning_retains_order_and_excludes_invalid_and_duplicate_ids():
    raw = [track("a"), track("a"), track("b", isAvailable=False), {"title": "missing"},
           track("c", artists=[]), track("d")]
    cleaned = clean_tracks(raw)
    assert [t["video_id"] for t in cleaned] == ["a", "d"]
    assert cleaned[0]["artists"] == ["Artist"]


def test_long_mixes_are_filtered_but_raw_data_and_unknown_lengths_survive():
    raw = [track("short", duration="4:15"), track("mix", duration="2:03:05"), track("unknown")]
    assert [t["video_id"] for t in clean_tracks(raw)] == ["short", "unknown"]
    assert clean_tracks(raw)[0]["duration_seconds"] == 255
    assert len(clean_tracks(raw, max_duration_seconds=0)) == 3
    assert len(raw) == 3


def test_split_is_reproducible_disjoint_and_complete():
    source = {"id": "PLsource", "title": "Theme", "tracks": [track(str(i)) for i in range(20)]}
    first = prepare_partial(source, seed_count=5, random_seed=42)
    assert first == prepare_partial(source, seed_count=5, random_seed=42)
    seeds = {t["video_id"] for t in first["seed_tracks"]}
    hidden = {t["video_id"] for t in first["held_out_tracks"]}
    assert len(seeds) == 5
    assert not seeds & hidden
    assert seeds | hidden == {str(i) for i in range(20)}
    with pytest.raises(ValueError):
        prepare_partial(source, seed_count=20, random_seed=42)


def test_platform_creation_sends_only_seeds_and_verifies_contents():
    example = prepare_partial({"id": "PLsource", "tracks": [track(str(i)) for i in range(8)]}, 3, 42)
    client = MagicMock()
    client.create_playlist.return_value = "PLnew"
    seed_ids = [t["video_id"] for t in example["seed_tracks"]]
    client.get_playlist.return_value = {"tracks": [track(i) for i in seed_ids]}
    assert create_seed_playlist(client, example, "Baseline sample") == "PLnew"
    kwargs = client.create_playlist.call_args.kwargs
    assert kwargs["video_ids"] == seed_ids
    assert kwargs["privacy_status"] == "PRIVATE"
    assert kwargs["description"] == ""
    assert "source_playlist" not in kwargs
    client.get_playlist.assert_called_once_with("PLnew", limit=None)


def test_creation_failure_keeps_created_id_for_recovery():
    example = prepare_partial({"id": "PLsource", "tracks": [track(str(i)) for i in range(8)]}, 3, 42)
    client = MagicMock()
    client.create_playlist.return_value = "PLnew"
    client.get_playlist.return_value = {"tracks": [track("unexpected")]}
    with pytest.raises(RuntimeError, match="contents"):
        create_seed_playlist(client, example, "Baseline sample")
    assert example["created_playlist_id"] == "PLnew"
    assert example["creation_verified"] is False


def test_suggestions_exclude_seeds_and_preserve_platform_order():
    client = MagicMock()
    client.get_playlist.return_value = {
        "tracks": [track("seed")],
        "suggestions": [track("seed"), track("a"), track("a"), track("b"), track("c")],
    }
    result = get_suggestions(client, "PLnew", count=2)
    assert [t["video_id"] for t in result["suggested_tracks"]] == ["a", "b"]
    assert result["requested_count"] == 2


def test_duplicate_platform_contents_do_not_pass_verification():
    example = prepare_partial({"id": "PLsource", "tracks": [track(str(i)) for i in range(8)]}, 3, 42)
    client = MagicMock()
    client.create_playlist.return_value = "PLnew"
    ids = [t["video_id"] for t in example["seed_tracks"]]
    client.get_playlist.return_value = {"tracks": [track(i) for i in ids + [ids[0]]]}
    with pytest.raises(RuntimeError):
        create_seed_playlist(client, example, "Baseline sample")


def test_api_error_response_does_not_count_as_creation():
    client = MagicMock()
    client.create_playlist.return_value = {"error": {"code": 403}}
    with pytest.raises(RuntimeError, match="did not return"):
        create_seed_playlist(client, {"seed_tracks": [{"video_id": "a"}]}, "Baseline sample")
    client.get_playlist.assert_not_called()


def test_existing_copy_can_be_reverified_without_writing():
    client = MagicMock()
    example = {"created_playlist_id": "PLnew", "seed_tracks": [{"video_id": "a"}], "creation_verified": False}
    client.get_playlist.return_value = {"tracks": [track("a")]}
    verify_seed_playlist(client, example)
    assert example["creation_verified"] is True
    client.create_playlist.assert_not_called()


def test_new_copy_read_retries_transient_missing_contents_without_recreating(monkeypatch):
    client = MagicMock()
    example = prepare_partial({"id": "PLsource", "tracks": [track(str(i)) for i in range(8)]}, 3, 42)
    client.create_playlist.return_value = "PLnew"
    ids = [t["video_id"] for t in example["seed_tracks"]]
    client.get_playlist.side_effect = [KeyError("missing contents"), {"tracks": [track(i) for i in ids]}]
    sleep = MagicMock()
    monkeypatch.setattr("playlists.time.sleep", sleep)
    assert create_seed_playlist(client, example, "Baseline sample") == "PLnew"
    client.create_playlist.assert_called_once()
    assert client.get_playlist.call_count == 2
    assert example["creation_verified"] is True
    sleep.assert_called_once_with(1)


def test_browser_auth_path_is_forwarded_without_network(tmp_path, monkeypatch):
    path = tmp_path / "browser.json"
    path.write_text('{"cookie": "test-cookie", "x-goog-authuser": "0"}')
    factory = MagicMock()
    monkeypatch.setattr("playlists.YTMusic", factory)
    make_client(path)
    assert factory.call_args.kwargs["auth"] == str(path)
    assert "oauth_credentials" not in factory.call_args.kwargs


def test_new_copy_read_retries_incomplete_songs_without_recreating(monkeypatch):
    client = MagicMock()
    client.create_playlist.return_value = "PLnew"
    example = {"seed_tracks": [{"video_id": "a"}, {"video_id": "b"}]}
    client.get_playlist.side_effect = [{"tracks": [track("a")]}, {"tracks": [track("a"), track("b")]}]
    sleep = MagicMock()
    monkeypatch.setattr("playlists.time.sleep", sleep)
    assert create_seed_playlist(client, example, "Baseline sample") == "PLnew"
    client.create_playlist.assert_called_once()
    assert client.get_playlist.call_count == 2
    assert example["creation_verified"] is True
    sleep.assert_called_once_with(1)


def test_oauth_tokens_are_rejected_without_echoing_contents(tmp_path):
    path = tmp_path / "oauth.json"
    path.write_text('{"access_token": "sensitive-value"}')
    with pytest.raises(ValueError, match="browser authentication") as error:
        make_client(path)
    assert "sensitive-value" not in str(error.value)


def test_missing_browser_credentials_raise_before_network(tmp_path):
    with pytest.raises(FileNotFoundError, match="Credential file not found"):
        make_client(tmp_path / "browser.json")
