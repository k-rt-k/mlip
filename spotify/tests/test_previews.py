"""Tests for Deezer preview resolution and caching (no network)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import previews  # noqa: E402
import users  # noqa: E402
from previews import download_previews, preview_url, track_isrcs  # noqa: E402


def track(tid, isrc, name="Song"):
    return {"id": tid, "name": name, "artists": [{"name": "Artist"}],
            "external_ids": {"isrc": isrc}, "album": {"release_date": "2021-05-01"}}


@pytest.fixture
def inventory(monkeypatch, tmp_path):
    """A minimal per-user inventory cache on disk."""
    monkeypatch.setattr(users, "DATA_ROOT", tmp_path)
    user_dir = tmp_path / "alice"
    user_dir.mkdir()
    (user_dir / "saved_tracks.json").write_text(json.dumps(
        [{"track": track("t1", "AAA111")}, {"track": track("t2", "BBB222")}]))
    (user_dir / "recently_played.json").write_text(json.dumps(
        [{"track": {**track("t3", "CCC333"), "external_ids": {}}}]))  # no ISRC
    (user_dir / "playlist_tracks.json").write_text(json.dumps(
        {"p1": [{"item": track("t4", "DDD444")}]}))
    return tmp_path


class TestTrackIsrcs:
    def test_collects_across_collections(self, inventory):
        got = track_isrcs("alice")
        assert set(got) == {"t1", "t2", "t4"}  # t3 has no ISRC

    def test_captures_metadata(self, inventory):
        assert track_isrcs("alice")["t1"] == {
            "artist": "Artist", "title": "Song", "isrc": "AAA111", "year": "2021"}

    def test_missing_collections_are_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(users, "DATA_ROOT", tmp_path)
        (tmp_path / "bob").mkdir()
        assert track_isrcs("bob") == {}


class TestPreviewUrl:
    def test_returns_url(self):
        session = MagicMock()
        session.get.return_value.json.return_value = {"preview": "https://cdn/x.mp3"}
        assert preview_url("AAA111", session) == "https://cdn/x.mp3"

    def test_withdrawn_track_gives_none(self):
        session = MagicMock()
        session.get.return_value.json.return_value = {"preview": "", "readable": False}
        assert preview_url("AAA111", session) is None

    def test_retries_then_succeeds_on_quota_error(self, monkeypatch):
        monkeypatch.setattr(previews.time, "sleep", lambda s: None)
        session = MagicMock()
        session.get.return_value.json.side_effect = [
            {"error": {"code": previews.QUOTA_ERROR}}, {"preview": "https://cdn/x.mp3"}]
        assert preview_url("AAA111", session) == "https://cdn/x.mp3"

    def test_gives_up_after_retries(self, monkeypatch):
        monkeypatch.setattr(previews.time, "sleep", lambda s: None)
        session = MagicMock()
        session.get.return_value.json.return_value = {"error": {"code": previews.QUOTA_ERROR}}
        assert preview_url("AAA111", session) is None
        assert session.get.call_count == 3


class TestDownloadPreviews:
    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        monkeypatch.setattr(previews.time, "sleep", lambda s: None)

    def fake_session(self, monkeypatch, preview="https://cdn/x.mp3"):
        session = MagicMock()
        session.get.return_value.json.return_value = {"preview": preview}
        session.get.return_value.content = b"ID3audio"
        session.get.return_value.status_code = 200
        monkeypatch.setattr(previews.requests, "Session", lambda: session)
        return session

    def test_downloads_and_returns_paths(self, monkeypatch, tmp_path):
        self.fake_session(monkeypatch)
        have, missing = download_previews({"t1": {"isrc": "A"}}, tmp_path)
        assert have == {"t1": tmp_path / "t1.mp3"}
        assert missing == []
        assert (tmp_path / "t1.mp3").read_bytes() == b"ID3audio"

    def test_existing_clips_are_not_refetched(self, monkeypatch, tmp_path):
        session = self.fake_session(monkeypatch)
        (tmp_path / "t1.mp3").write_bytes(b"ID3old")
        have, _ = download_previews({"t1": {"isrc": "A"}}, tmp_path)
        assert have["t1"].read_bytes() == b"ID3old"
        session.get.assert_not_called()

    def test_unavailable_tracks_are_reported(self, monkeypatch, tmp_path):
        self.fake_session(monkeypatch, preview="")
        have, missing = download_previews({"t1": {"isrc": "A"}}, tmp_path)
        assert have == {} and missing == ["t1"]


@pytest.mark.parametrize("status, content", [(403, b"ID3audio"), (200, b"<html>error"), (200, b"")])
def test_invalid_download_is_not_cached(monkeypatch, tmp_path, status, content):
    session = TestDownloadPreviews().fake_session(monkeypatch)
    session.get.return_value.status_code = status
    session.get.return_value.content = content
    have, missing = download_previews({"t": {"isrc": "A"}}, tmp_path, pause=0)
    assert have == {} and missing == ["t"]
    assert not list(tmp_path.iterdir())


def test_replaces_invalid_cache_and_stale_partial(monkeypatch, tmp_path):
    TestDownloadPreviews().fake_session(monkeypatch)
    (tmp_path / "t.mp3").write_bytes(b"<html>error")
    (tmp_path / "t.mp3.part").write_bytes(b"partial")
    have, missing = download_previews({"t": {"isrc": "A"}}, tmp_path, pause=0)
    assert have["t"].read_bytes() == b"ID3audio"
    assert missing == [] and not (tmp_path / "t.mp3.part").exists()


def test_failed_write_never_publishes_partial(monkeypatch, tmp_path):
    TestDownloadPreviews().fake_session(monkeypatch)
    original = Path.write_bytes
    def interrupted(path, content):
        original(path, content[:3])
        raise OSError("interrupted")
    monkeypatch.setattr(Path, "write_bytes", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        download_previews({"t": {"isrc": "A"}}, tmp_path, pause=0)
    assert not list(tmp_path.iterdir())


def test_mpeg_header_is_accepted(monkeypatch, tmp_path):
    session = TestDownloadPreviews().fake_session(monkeypatch)
    session.get.return_value.content = b"\xff\xfbtest"
    have, missing = download_previews({"t": {"isrc": "A"}}, tmp_path, pause=0)
    assert "t" in have and not missing


def test_network_failure_does_not_stop_other_tracks(monkeypatch, tmp_path):
    session = TestDownloadPreviews().fake_session(monkeypatch)
    response = session.get.return_value
    session.get.side_effect = [previews.requests.Timeout("timeout"), response, response]
    have, missing = download_previews({"a": {"isrc": "A"}, "b": {"isrc": "B"}}, tmp_path, pause=0)
    assert list(have) == ["b"] and missing == ["a"]
