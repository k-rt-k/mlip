"""Tests for shard assignment and the per-shard node log."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import jobs  # noqa: E402
from jobs import (  # noqa: E402
    parse_shard,
    record,
    require_persistent_out,
    shard_locations,
    shard_of,
    shard_tag,
)


class TestShardOf:
    def test_matches_sha1_so_it_is_stable_across_processes(self):
        expected = int.from_bytes(hashlib.sha1(b"abc").digest()[:8], "big") % 7
        assert shard_of("abc", 7) == expected

    def test_in_range(self):
        assert all(0 <= shard_of(f"id{i}", 5) < 5 for i in range(1000))

    def test_roughly_balanced(self):
        counts = [0] * 4
        for i in range(8000):
            counts[shard_of(f"track{i}", 4)] += 1
        assert min(counts) > 1800 and max(counts) < 2200

    def test_single_shard_takes_everything(self):
        assert {shard_of(f"x{i}", 1) for i in range(50)} == {0}


class TestParseShard:
    def test_valid(self):
        assert parse_shard("2/8") == (2, 8)

    @pytest.mark.parametrize("bad", ["8/8", "-1/4", "0/0", "3"])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            parse_shard(bad)


class TestLog:
    def test_record_stamps_node_and_slurm_job(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SLURM_JOB_ID", "123")
        monkeypatch.setenv("SLURM_RESTART_COUNT", "2")
        monkeypatch.setattr(jobs.socket, "gethostname", lambda: "babel-t9-20")
        log = tmp_path / "logs" / "a.jsonl"
        record(log, event="start")
        entry = json.loads(log.read_text())
        assert entry["node"] == "babel-t9-20"
        assert entry["job_id"] == "123" and entry["restart"] == 2
        assert entry["event"] == "start"

    def test_locations_report_latest_entry_per_shard(self, tmp_path, monkeypatch):
        nodes = iter(["node-a", "node-b"])
        monkeypatch.setattr(jobs.socket, "gethostname", lambda: next(nodes))
        tag = shard_tag("clap", 0, 2)
        record(tmp_path / f"{tag}.jsonl", event="start")
        record(tmp_path / f"{tag}.jsonl", event="start")  # requeued elsewhere
        assert shard_locations(tmp_path)[tag]["node"] == "node-b"

    def test_locations_of_empty_dir(self, tmp_path):
        assert shard_locations(tmp_path) == {}


class TestRequirePersistentOut:
    @pytest.fixture
    def root(self, tmp_path, monkeypatch):
        """A stand-in /data/user_data with one mounted user dir and a repo."""
        user_data = (tmp_path / "user_data").resolve()
        (user_data / "ksnair").mkdir(parents=True)
        repo = (tmp_path / "repo").resolve()
        repo.mkdir()
        monkeypatch.setattr(jobs, "USER_DATA_ROOT", user_data)
        return user_data, repo

    def test_accepts_path_under_user_data(self, root):
        user_data, repo = root
        out = user_data / "ksnair" / "mlip" / "embeddings"
        assert require_persistent_out(out, repo) == out

    def test_rejects_path_outside_user_data(self, root, tmp_path):
        _, repo = root
        with pytest.raises(RuntimeError, match="must live under"):
            require_persistent_out(tmp_path / "elsewhere", repo)

    def test_rejects_symlink_escaping_user_data(self, root, tmp_path):
        user_data, repo = root
        (tmp_path / "home").mkdir()
        link = user_data / "ksnair" / "sneaky"
        link.symlink_to(tmp_path / "home")
        with pytest.raises(RuntimeError, match="resolves to"):
            require_persistent_out(link / "embeddings", repo)

    def test_rejects_dotdot_escape(self, root, tmp_path):
        user_data, repo = root
        with pytest.raises(RuntimeError, match="must live under"):
            require_persistent_out(user_data / "ksnair" / ".." / ".." / "x", repo)

    def test_rejects_repo_clone_inside_user_data(self, root):
        user_data, _ = root
        repo = user_data / "ksnair" / "mlip"
        repo.mkdir()
        with pytest.raises(RuntimeError, match="inside the git repo"):
            require_persistent_out(repo / "data" / "embeddings", repo)

    def test_rejects_unmounted_user_dir(self, root):
        user_data, repo = root
        with pytest.raises(RuntimeError, match="not available here"):
            require_persistent_out(user_data / "someone_else" / "emb", repo)
