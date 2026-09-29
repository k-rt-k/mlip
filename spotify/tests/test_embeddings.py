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


@pytest.fixture
def tiny_muq():
    import torch

    class TinyModel(torch.nn.Module):
        def forward(self, wavs=None, texts=None):
            if wavs is not None:
                return torch.stack((wavs.sum(dim=1), wavs[:, -1]), dim=1)
            return torch.ones((len(texts), 2), device=self.anchor.device)

    model = TinyModel()
    model.register_buffer("anchor", torch.ones(1))
    embedder = embeddings.MuQMuLan.__new__(embeddings.MuQMuLan)
    embedder._torch = torch
    embedder.device = "cpu"
    embedder._model = model
    return embedder


def test_muq_batch_composition_preserves_vectors_and_order(tiny_muq):
    signals = {"long": np.array([1, 2, 3, 8], dtype=np.float32),
               "short": np.array([2, 1], dtype=np.float32),
               "other": np.array([4, 3, 2, 1], dtype=np.float32)}
    tiny_muq._load = signals.__getitem__
    paths = list(signals)
    individual = np.concatenate([tiny_muq.embed_audio([p]) for p in paths])
    np.testing.assert_allclose(tiny_muq.embed_audio(paths), individual)
    np.testing.assert_allclose(tiny_muq.embed_audio(paths, batch_size=2), individual)


@pytest.mark.parametrize("device", ["cpu", "cuda", "mps"])
def test_muq_text_runs_on_device(tiny_muq, device):
    torch = tiny_muq._torch
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    if device == "mps" and not torch.backends.mps.is_available():
        pytest.skip("MPS unavailable")
    tiny_muq.device = device
    tiny_muq._model.to(device)
    out = tiny_muq.embed_text(["jazz", "rock"])
    assert isinstance(out, np.ndarray) and out.shape == (2, 2)
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1, rtol=1e-6)


@pytest.mark.parametrize("model", ["clap", "muq"])
def test_decode_failure_skips_only_bad_clip(model, tiny_muq):
    embedder = tiny_muq if model == "muq" else embeddings.Clap.__new__(embeddings.Clap)
    if model == "clap":
        embedder._encode = lambda chunks: np.array([[s.sum(), s[-1]] for s in chunks])
    def load(path):
        if path == "bad":
            raise ValueError("cannot decode")
        if path == "empty":
            return np.array([])
        return np.array([1, 2] if path == "first" else [3, 1], dtype=np.float32)
    embedder._load = load
    failed = {}
    out = embedder.embed_audio(["first", "bad", "empty", "last"],
                              on_error=lambda p, e: failed.update({p: e}))
    expected = embedder.embed_audio(["first", "last"])
    np.testing.assert_allclose(out, expected)
    assert set(failed) == {"bad", "empty"}
    assert embedder.embed_audio(["bad"], on_error=lambda *args: None).shape == (0, 0)
    with pytest.raises(ValueError, match="cannot decode"):
        embedder.embed_audio(["bad"])


def test_clamp_missing_outputs_preserve_alignment(tmp_path, monkeypatch):
    embedder = Clamp3.__new__(Clamp3)
    embedder.venv = tmp_path
    embedder.repo_dir = tmp_path
    def run(cmd, **kwargs):
        out = Path(cmd[3])
        out.mkdir()
        for stem, row in [("a", [3., 4.]), ("c", [4., 3.])]:
            np.save(out / f"{stem}.npy", row)
        return MagicMock(returncode=0)
    monkeypatch.setattr(embeddings.subprocess, "run", run)
    paths = [tmp_path / f"{stem}.mp3" for stem in "abc"]
    for path in paths:
        path.write_bytes(b"audio")
    failures = {}
    out = embedder.embed_audio(paths, on_error=lambda p, e: failures.update({p: e}))
    assert list(failures) == [paths[1]]
    np.testing.assert_allclose(out, [[.6, .8], [.8, .6]])
    monkeypatch.setattr(embeddings.subprocess, "run", lambda *a, **kw: MagicMock(returncode=0))
    assert embedder.embed_audio(paths, on_error=lambda *a: None).shape == (0, 0)


def test_muq_text_moves_output_to_cpu_before_numpy(tiny_muq):
    class DeviceTensor:
        def __init__(self):
            self.on_cpu = False
        def cpu(self):
            self.on_cpu = True
            return self
        def numpy(self):
            assert self.on_cpu, "device tensors must move to CPU first"
            return np.array([[3., 4.]])
    tiny_muq._model = lambda **kwargs: DeviceTensor()
    np.testing.assert_allclose(tiny_muq.embed_text(["jazz"]), [[.6, .8]])
