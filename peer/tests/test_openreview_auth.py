"""Tests for OpenReview auth: token-first precedence and .env token writing (no network)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import openreview_auth as auth  # noqa: E402


@pytest.fixture
def fake_clients(monkeypatch):
    v1, v2 = MagicMock(name="Client"), MagicMock(name="OpenReviewClient")
    monkeypatch.setattr(auth.openreview, "Client", v1)
    monkeypatch.setattr(auth.openreview.api, "OpenReviewClient", v2)
    return v1, v2


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("OPENREVIEW_TOKEN", "OPENREVIEW_USERNAME", "OPENREVIEW_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


class TestGetClient:
    def test_token_wins_over_password(self, tmp_path, fake_clients, clean_env):
        env = tmp_path / ".env"
        env.write_text("OPENREVIEW_TOKEN=abc\nOPENREVIEW_USERNAME=u\nOPENREVIEW_PASSWORD=p\n")
        auth.get_client(2, env_path=env)
        fake_clients[1].assert_called_once_with(baseurl=auth.BASEURLS[2], token="abc")

    def test_password_fallback(self, tmp_path, fake_clients, clean_env):
        env = tmp_path / ".env"
        env.write_text("OPENREVIEW_USERNAME=u\nOPENREVIEW_PASSWORD=p\n")
        auth.get_client(1, env_path=env)
        fake_clients[0].assert_called_once_with(baseurl=auth.BASEURLS[1], username="u", password="p")

    def test_placeholders_are_not_credentials(self, tmp_path, fake_clients, clean_env):
        env = tmp_path / ".env"
        env.write_text("OPENREVIEW_USERNAME=you@example.com\nOPENREVIEW_PASSWORD=your-password-here\n")
        with pytest.raises(RuntimeError, match="openreview_login"):
            auth.get_client(2, env_path=env)

    def test_missing_everything_raises(self, tmp_path, fake_clients, clean_env):
        with pytest.raises(RuntimeError):
            auth.get_client(2, env_path=tmp_path / ".env")

    def test_bad_version(self, tmp_path, fake_clients, clean_env):
        with pytest.raises(ValueError):
            auth.get_client(3, env_path=tmp_path / ".env")


class TestWriteToken:
    def test_creates_file_with_token(self, tmp_path):
        env = tmp_path / ".env"
        auth.write_token(env, "tok")
        assert env.read_text() == "OPENREVIEW_TOKEN=tok\n"

    def test_replaces_existing_token_and_drops_password(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# comment\nOPENREVIEW_USERNAME=u\nOPENREVIEW_PASSWORD=p\nOPENREVIEW_TOKEN=old\n")
        auth.write_token(env, "new")
        text = env.read_text()
        assert "OPENREVIEW_TOKEN=new" in text
        assert "old" not in text
        assert "OPENREVIEW_PASSWORD" not in text
        assert "# comment" in text and "OPENREVIEW_USERNAME=u" in text

    def test_file_is_private(self, tmp_path):
        env = tmp_path / ".env"
        auth.write_token(env, "tok")
        assert (env.stat().st_mode & 0o777) == 0o600
