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
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

CLAMP3_VENV = Path(os.environ.get("CLAMP3_VENV", Path.home() / "mamba/envs/clamp3"))
CLAMP3_REPO = Path(os.environ.get("CLAMP3_REPO", Path.home() / ".cache/clamp3"))


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

    def embed_audio(self, paths, batch_size=None):
        """L2-normalised (len(paths), dim) embeddings of audio files."""
        raise NotImplementedError

    def embed_text(self, texts):
        """L2-normalised (len(texts), dim) embeddings of text phrases."""
        raise NotImplementedError

    def _load(self, path):
        import librosa

        signal, _ = librosa.load(path, sr=self.sample_rate, mono=True)
        return signal


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

    def __init__(self):
        import torch
        from transformers import ClapModel, ClapProcessor

        self._torch = torch
        self._model = ClapModel.from_pretrained(self.repo).eval()
        self._processor = ClapProcessor.from_pretrained(self.repo)

    def embed_audio(self, paths, batch_size=None):
        rows = []
        for batch in batched(paths, batch_size or self.batch_size):
            # Encode every window of every clip in one pass, then average the
            # windows belonging to each clip back together.
            per_clip = [windows(self._load(p), self.window_seconds * self.sample_rate)
                        for p in batch]
            encoded = self._encode([w for clip in per_clip for w in clip])
            offset = 0
            for clip in per_clip:
                rows.append(encoded[offset:offset + len(clip)].mean(axis=0))
                offset += len(clip)
        return l2_normalise(np.stack(rows))

    def _encode(self, chunks):
        inputs = self._processor(audio=list(chunks), sampling_rate=self.sample_rate,
                                 return_tensors="pt", padding=True)
        with self._torch.no_grad():
            return self._model.get_audio_features(**inputs).pooler_output.numpy()

    def embed_text(self, texts):
        inputs = self._processor(text=list(texts), return_tensors="pt", padding=True)
        with self._torch.no_grad():
            out = self._model.get_text_features(**inputs).pooler_output.numpy()
        return l2_normalise(out)


class MuQMuLan(Embedder):
    """MuQ-MuLan: open reproduction of Google's (unreleased) MuLan."""

    name = "muq"
    sample_rate = 24000
    repo = "OpenMuQ/MuQ-MuLan-large"

    def __init__(self):
        import torch
        from muq import MuQMuLan as _MuQMuLan

        self._torch = torch
        self._model = _MuQMuLan.from_pretrained(self.repo).eval()

    def embed_audio(self, paths, batch_size=None):
        rows = []
        for batch in batched(paths, batch_size or self.batch_size):
            signals = [self._load(p) for p in batch]
            shortest = min(len(s) for s in signals)  # previews are all 30s, but be safe
            wavs = self._torch.from_numpy(np.stack([s[:shortest] for s in signals]))
            with self._torch.no_grad():
                rows.append(self._model(wavs=wavs).numpy())
        return l2_normalise(np.concatenate(rows))

    def embed_text(self, texts):
        with self._torch.no_grad():
            return l2_normalise(self._model(texts=list(texts)).numpy())


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

    def embed_audio(self, paths, batch_size=None):
        # Its CLI already processes a whole directory per call, so one pass is
        # the batch; batch_size is accepted only to honour the interface.
        return self._run({p.name: p.read_bytes() for p in paths},
                         [p.stem for p in paths])

    def embed_text(self, texts):
        files = {f"{i}.txt": t.encode() for i, t in enumerate(texts)}
        return self._run(files, [str(i) for i in range(len(texts))])

    def _run(self, files, stems):
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
            rows = [np.load(out / f"{stem}.npy").reshape(-1) for stem in stems]
        return l2_normalise(np.stack(rows))


EMBEDDERS = {cls.name: cls for cls in (Clap, MuQMuLan, Clamp3)}


def get_embedder(name):
    """Instantiate one embedder by name; loads weights on first use."""
    if name not in EMBEDDERS:
        raise ValueError(f"unknown model {name!r}; choose from {sorted(EMBEDDERS)}")
    return EMBEDDERS[name]()
