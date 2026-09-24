#!/bin/sh
# One-time setup for the CLaMP 3 embedder.
#
# CLaMP 3 pins transformers 4.40 and numpy<2, which would break CLAP and
# MuQ-MuLan in the main environment, so it gets its own venv and a clone of
# its repo. Override the locations with CLAMP3_VENV / CLAMP3_REPO.
set -e

VENV="${CLAMP3_VENV:-$HOME/mamba/envs/clamp3}"
REPO="${CLAMP3_REPO:-$HOME/.cache/clamp3}"
BASE_PYTHON="${BASE_PYTHON:-$HOME/mamba/envs/claude/bin/python}"

if [ ! -d "$REPO" ]; then
  echo "cloning CLaMP 3 into $REPO"
  git clone --depth 1 https://github.com/sanderwood/clamp3.git "$REPO"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "creating venv at $VENV"
  "$BASE_PYTHON" -m venv "$VENV"
fi

echo "installing pinned dependencies"
# torch 2.3.1 matches the weight_norm format MERT's checkpoint was saved with
# and can still decode mp3 without torchcodec; mido/samplings/abctoolkit are
# imported unconditionally by their code even for the audio-only path.
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q \
  "numpy==1.26.4" "transformers==4.40.0" "torch==2.3.1" "torchaudio==2.3.1" \
  "nnAudio==0.3.3" "accelerate==0.34.0" "mido==1.3.0" "samplings==0.1.7" \
  abctoolkit soundfile librosa tqdm unidecode

echo "done. CLaMP 3 weights (~1GB) download on first use."
