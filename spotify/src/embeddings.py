"""Audio-text embedding models over track previews, behind one interface.

These replace the audio features Spotify deprecated: each model maps a 30s
preview and a text phrase into one shared space, so audio-audio similarity
(for recommendations) and audio-text similarity (for zero-shot tagging) are
both just cosine distance.

Weights download once from HuggingFace and then run locally — there is no
API, no key and no rate limit at inference time.

    clap    LAION CLAP. ~0.15s/clip, best short-prompt tagging.
    muq     MuQ-MuLan-large: the open reproduction of Google's MuLan, whose
            own weights were never released. ~1.9s/clip.
    clamp3  Strongest retrieval in our spike. Pinned to old transformers and
            numpy, so it runs in its own venv via subprocess — see
            scripts/setup_clamp3.sh.

Usage:
    emb = get_embedder("clap")
    audio = emb.embed_audio([Path("a.mp3"), Path("b.mp3")])   # (2, dim)
    text = emb.embed_text(["mellow jazz", "aggressive rap"])  # (2, dim)
    similarity = audio @ text.T
"""

import os
import subprocess
import warnings
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

CLAMP3_VENV = Path(os.environ.get("CLAMP3_VENV", Path.home() / "mamba/envs/clamp3"))
CLAMP3_REPO = Path(os.environ.get("CLAMP3_REPO", Path.home() / ".cache/clamp3"))


def pick_device(preference=None):
    """cuda if present, else Apple mps, else cpu. EMBED_DEVICE overrides.

    Warns when it lands on cpu, since an unnoticed cpu fallback is the
    difference between minutes and days over a full library.
    """
    import torch

    choice = preference or os.environ.get("EMBED_DEVICE")
    if choice:
        return choice
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    warnings.warn("no cuda or mps device found - embedding on cpu will be "
                  "roughly an order of magnitude slower", stacklevel=2)
    return "cpu"


def l2_normalise(matrix):
    """Row-wise unit norm, so a dot product is a cosine similarity."""
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def batched(items, size):
    """Yield consecutive slices of `items` of at most `size`."""
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def windows(signal, size):
    """Split a signal into consecutive chunks of `size` samples.

    The tail is kept if it is at least a quarter window, so a 30s clip split
    at 10s gives three full windows and nothing is silently dropped.
    """
    chunks = [signal[i:i + size] for i in range(0, len(signal), size)]
    return [c for c in chunks if len(c) >= size // 4] or [signal]


class Embedder:
    """Shared interface. Subclasses set `name`/`sample_rate` and the two methods."""

    name = ""
    sample_rate = 0

    #: clips encoded per forward pass; raise for more speed, lower for less memory
    batch_size = 8
    #: threads used to decode mp3s; the decoder releases the GIL, and decoding
    #: (~0.15s/clip) dominates once the forward pass runs on a real GPU
    decode_workers = 4

    def embed_audio(self, paths, batch_size=None, on_error=None):
        """L2-normalised audio embeddings, in input order.

        With on_error(path, message), omit undecodable clips and report each
        failure. Without a callback, fail immediately. All-failed/empty inputs
        return shape (0, 0), since the embedding dimension is not yet known.
        """
        raise NotImplementedError

    def embed_text(self, texts):
        """L2-normalised (len(texts), dim) embeddings of text phrases."""
        raise NotImplementedError

    def _load(self, path):
        import librosa

        signal, _ = librosa.load(path, sr=self.sample_rate, mono=True)
        return signal

    def _load_many(self, paths, on_error=None):
        """Decode a batch of clips in parallel."""
        def decode(path):
            try:
                signal = self._load(path)
                if not len(signal):
                    raise ValueError("empty audio")
                return signal, None
            except Exception as exc:
                if on_error is None:
                    raise
                return None, str(exc)

        with ThreadPoolExecutor(max_workers=self.decode_workers) as pool:
            results = list(pool.map(decode, paths))
        signals = []
        for path, (signal, error) in zip(paths, results):
            if error is not None:
                on_error(path, error)
            else:
                signals.append(signal)
        return signals


class Clap(Embedder):
    """LAION CLAP, music-and-speech checkpoint.

    CLAP only accepts 10s of audio. Its feature extractor defaults to
    `rand_trunc`, which picks a *random* 10s window and so embeds the same
    clip differently on every run. We window the clip ourselves and average,
    which is both deterministic and uses all 30 seconds.
    """

    name = "clap"
    sample_rate = 48000
    repo = "laion/larger_clap_music_and_speech"
    window_seconds = 10

    def __init__(self, device=None):
        import torch
        from transformers import ClapModel, ClapProcessor

        self._torch = torch
        self.device = pick_device(device)
        self._model = ClapModel.from_pretrained(self.repo).eval().to(self.device)
        self._processor = ClapProcessor.from_pretrained(self.repo)

    def embed_audio(self, paths, batch_size=None, on_error=None):
        rows = []
        for batch in batched(paths, batch_size or self.batch_size):
            # Encode every window of every clip in one pass, then average the
            # windows belonging to each clip back together.
            per_clip = [windows(signal, self.window_seconds * self.sample_rate)
                        for signal in self._load_many(batch, on_error)]
            if not per_clip:
                continue
            encoded = self._encode([w for clip in per_clip for w in clip])
            offset = 0
            for clip in per_clip:
                rows.append(encoded[offset:offset + len(clip)].mean(axis=0))
                offset += len(clip)
        return l2_normalise(np.stack(rows)) if rows else np.empty((0, 0))

    def _encode(self, chunks):
        inputs = self._processor(audio=list(chunks), sampling_rate=self.sample_rate,
                                 return_tensors="pt", padding=True).to(self.device)
        with self._torch.no_grad():
            return self._model.get_audio_features(**inputs).pooler_output.cpu().numpy()

    def embed_text(self, texts):
        inputs = self._processor(text=list(texts), return_tensors="pt",
                                 padding=True).to(self.device)
        with self._torch.no_grad():
            out = self._model.get_text_features(**inputs).pooler_output.cpu().numpy()
        return l2_normalise(out)


class MuQMuLan(Embedder):
    """MuQ-MuLan: open reproduction of Google's (unreleased) MuLan."""

    name = "muq"
    sample_rate = 24000
    repo = "OpenMuQ/MuQ-MuLan-large"

    def __init__(self, device=None):
        import torch
        from muq import MuQMuLan as _MuQMuLan

        self._torch = torch
        self.device = pick_device(device)
        self._model = _MuQMuLan.from_pretrained(self.repo).eval().to(self.device)

    def embed_audio(self, paths, batch_size=None, on_error=None):
        rows = []
        for batch in batched(paths, batch_size or self.batch_size):
            signals = self._load_many(batch, on_error)
            # Equal-length groups preserve each clip regardless of neighbours.
            groups = {}
            for index, signal in enumerate(signals):
                groups.setdefault(len(signal), []).append(index)
            batch_rows = [None] * len(signals)
            for indices in groups.values():
                wavs = self._torch.from_numpy(
                    np.stack([signals[i] for i in indices])).to(self.device)
                with self._torch.no_grad():
                    encoded = self._model(wavs=wavs).cpu().numpy()
                for index, vector in zip(indices, encoded):
                    batch_rows[index] = vector
            rows.extend(batch_rows)
        return l2_normalise(np.stack(rows)) if rows else np.empty((0, 0))

    def embed_text(self, texts):
        with self._torch.no_grad():
            return l2_normalise(self._model(texts=list(texts)).cpu().numpy())


class Clamp3(Embedder):
    """CLaMP 3 (SAAS checkpoint), driven as a subprocess.

    It pins transformers 4.40 / numpy<2, which would break the other two
    models, so it lives in its own venv. Its CLI takes a directory of files
    and writes one .npy per input, so each call stages a temp directory.
    """

    name = "clamp3"
    sample_rate = 24000  # handled internally by its MERT stage

    def __init__(self, venv=CLAMP3_VENV, repo=CLAMP3_REPO):
        self.venv, self.repo_dir = Path(venv), Path(repo)
        missing = [p for p in (self.venv / "bin/python", self.repo_dir / "clamp3_embd.py")
                   if not p.exists()]
        if missing:
            raise RuntimeError(
                f"CLaMP 3 is not set up ({missing[0]} is absent). "
                "Run spotify/scripts/setup_clamp3.sh, or point CLAMP3_VENV / "
                "CLAMP3_REPO at an existing install."
            )

    def embed_audio(self, paths, batch_size=None, on_error=None):
        # Its CLI already processes a whole directory per call, so one pass is
        # the batch; batch_size is accepted only to honour the interface.
        # Each call costs ~16s fixed (loads MERT + CLaMP3 from disk, spawns the
        # subprocess, stages temp files) on top of ~1.2s/clip, so always pass
        # every clip at once rather than calling this in a loop.
        paths = list(paths)
        by_stem = {p.stem: p for p in paths}
        return self._run({p.name: p.read_bytes() for p in paths},
                         [p.stem for p in paths],
                         on_error=(lambda stem, error: on_error(
                             by_stem[stem], error))
                         if on_error else None)

    def embed_text(self, texts):
        files = {f"{i}.txt": t.encode() for i, t in enumerate(texts)}
        return self._run(files, [str(i) for i in range(len(texts))])

    def _run(self, files, stems, on_error=None):
        """Stage `files`, run the CLI, and read back embeddings in `stems` order."""
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "in", Path(tmp) / "out"
            src.mkdir()
            for name, blob in files.items():
                (src / name).write_bytes(blob)
            # Its CLI shells out to a bare `python`, so put the venv first on PATH.
            env = {**os.environ, "PATH": f"{self.venv / 'bin'}:{os.environ['PATH']}",
                   "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
            result = subprocess.run(
                [str(self.venv / "bin/python"), "clamp3_embd.py",
                 str(src), str(out), "--get_global"],
                cwd=self.repo_dir, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"clamp3_embd.py failed:\n{result.stdout[-2000:]}")
            rows = []
            for stem in stems:
                path = out / f"{stem}.npy"
                if not path.exists() and on_error is not None:
                    on_error(stem, "CLaMP 3 produced no embedding")
                    continue
                rows.append(np.load(path).reshape(-1))
        return l2_normalise(np.stack(rows)) if rows else np.empty((0, 0))


EMBEDDERS = {cls.name: cls for cls in (Clap, MuQMuLan, Clamp3)}


def get_embedder(name, device=None):
    """Instantiate one embedder by name; loads weights on first use.

    `device` applies to clap/muq (cuda > mps > cpu by default). CLaMP 3 picks
    its own device inside its venv via accelerate.
    """
    if name not in EMBEDDERS:
        raise ValueError(f"unknown model {name!r}; choose from {sorted(EMBEDDERS)}")
    cls = EMBEDDERS[name]
    return cls() if cls is Clamp3 else cls(device=device)
