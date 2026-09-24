"""Tests for the embedding interface (no model weights downloaded)."""

import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import embeddings  # noqa: E402
from embeddings import (  # noqa: E402
    EMBEDDERS,
    Clamp3,
    batched,
    get_embedder,
    l2_normalise,
    windows,
)


class TestHelpers:
    def test_batched_splits_with_remainder(self):
        assert [len(b) for b in batched(range(20), 8)] == [8, 8, 4]

    def test_batched_empty(self):
        assert list(batched([], 4)) == []

    def test_l2_normalise_gives_unit_rows(self):
        out = l2_normalise(np.array([[3.0, 4.0], [0.0, 2.0]]))
        assert np.allclose(np.linalg.norm(out, axis=1), 1.0)

    def test_windows_splits_30s_into_three(self):
        assert len(windows(np.zeros(30 * 48000), 10 * 48000)) == 3

    def test_windows_drops_only_tiny_tail(self):
        # a 10% tail is noise; a 50% tail is worth keeping
        assert len(windows(np.zeros(110), 100)) == 1
        assert len(windows(np.zeros(150), 100)) == 2

    def test_windows_never_returns_empty(self):
        assert len(windows(np.zeros(10), 100)) == 1


class TestDevice:
    def test_explicit_preference_wins(self):
        assert embeddings.pick_device("cuda:1") == "cuda:1"

    def test_env_var_is_honoured(self, monkeypatch):
        monkeypatch.setenv("EMBED_DEVICE", "cpu")
        assert embeddings.pick_device() == "cpu"

    def test_falls_back_to_cpu_with_a_warning(self, monkeypatch):
        monkeypatch.delenv("EMBED_DEVICE", raising=False)
        fake = MagicMock()
        fake.cuda.is_available.return_value = False
        fake.backends.mps.is_available.return_value = False
        monkeypatch.setitem(sys.modules, "torch", fake)
        with pytest.warns(UserWarning, match="cpu"):
            assert embeddings.pick_device() == "cpu"

    def test_explicit_cpu_does_not_warn(self, monkeypatch):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert embeddings.pick_device("cpu") == "cpu"

    def test_prefers_cuda_over_mps(self, monkeypatch):
        monkeypatch.delenv("EMBED_DEVICE", raising=False)
        fake = MagicMock()
        fake.cuda.is_available.return_value = True
        monkeypatch.setitem(sys.modules, "torch", fake)
        assert embeddings.pick_device() == "cuda"


class TestRegistry:
    def test_all_three_models_registered(self):
        assert sorted(EMBEDDERS) == ["clamp3", "clap", "muq"]

    def test_unknown_model_lists_choices(self):
        with pytest.raises(ValueError, match="clamp3"):
            get_embedder("nope")


class TestClamp3:
    def test_missing_setup_points_at_setup_script(self, tmp_path):
        with pytest.raises(RuntimeError, match="setup_clamp3.sh"):
            Clamp3(venv=tmp_path / "absent", repo=tmp_path / "absent")

    @pytest.fixture
    def installed(self, tmp_path):
        venv, repo = tmp_path / "venv", tmp_path / "repo"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").touch()
        repo.mkdir()
        (repo / "clamp3_embd.py").touch()
        return Clamp3(venv=venv, repo=repo)

    def test_embed_text_stages_files_and_reads_back(self, installed, monkeypatch):
        """Its CLI writes one .npy per input; check we read them in order."""
        def fake_run(cmd, **kwargs):
            out = Path(cmd[3])
            out.mkdir(parents=True, exist_ok=True)
            for i in range(len(list(Path(cmd[2]).iterdir()))):
                np.save(out / f"{i}.npy", np.full((1, 4), float(i) + 1))
            return MagicMock(returncode=0)
        monkeypatch.setattr(embeddings.subprocess, "run", fake_run)
        out = installed.embed_text(["a", "b"])
        assert out.shape == (2, 4)
        assert np.allclose(np.linalg.norm(out, axis=1), 1.0)

    def test_failure_surfaces_cli_output(self, installed, monkeypatch):
        monkeypatch.setattr(embeddings.subprocess, "run",
                            lambda cmd, **kw: MagicMock(returncode=1, stdout="boom"))
        with pytest.raises(RuntimeError, match="boom"):
            installed.embed_text(["a"])
