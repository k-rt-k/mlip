"""Tests for per-user path resolution and the identity guard (no network)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import users  # noqa: E402
from users import cache_path, check_identity, data_dir, validate  # noqa: E402


class TestValidate:
    @pytest.mark.parametrize("slug", ["kartik", "alice-b", "user_2", "x"])
    def test_accepts_slugs(self, slug):
        assert validate(slug) == slug

    @pytest.mark.parametrize("bad", ["", "Kartik", "a b", "../x", "a/b", "é", None])
    def test_rejects_non_slugs(self, bad):
        with pytest.raises(ValueError, match="user"):
            validate(bad)


class TestPaths:
    def test_cache_path_per_user(self):
        assert cache_path("alice").name == ".cache-pkce-alice"
        assert cache_path("alice").parent == users.SPOTIFY_DIR

    def test_data_dir_per_user(self):
        assert data_dir("alice") == users.DATA_ROOT / "alice"

    def test_paths_validate(self):
        with pytest.raises(ValueError):
            cache_path("../etc")


@pytest.fixture
def data_root(monkeypatch, tmp_path):
    monkeypatch.setattr(users, "DATA_ROOT", tmp_path)
    return tmp_path


def sp_with_id(user_id):
    sp = MagicMock()
    sp.current_user.return_value = {"id": user_id, "display_name": "X"}
    return sp


class TestCheckIdentity:
    def test_first_run_writes_profile(self, data_root):
        profile = check_identity(sp_with_id("u1"), "alice")
        assert profile["id"] == "u1"
        saved = json.loads((data_root / "alice" / "profile.json").read_text())
        assert saved["id"] == "u1"

    def test_matching_profile_passes(self, data_root):
        check_identity(sp_with_id("u1"), "alice")
        assert check_identity(sp_with_id("u1"), "alice")["id"] == "u1"

    def test_mismatch_raises_and_names_cache(self, data_root):
        check_identity(sp_with_id("u1"), "alice")
        with pytest.raises(RuntimeError, match=r"\.cache-pkce-alice"):
            check_identity(sp_with_id("u2"), "alice")

    def test_mismatch_does_not_overwrite_profile(self, data_root):
        check_identity(sp_with_id("u1"), "alice")
        with pytest.raises(RuntimeError):
            check_identity(sp_with_id("u2"), "alice")
        assert json.loads((data_root / "alice" / "profile.json").read_text())["id"] == "u1"
