#!/bin/bash
#SBATCH --job-name=mpd-clap
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=28-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
set -euo pipefail
ROOT=/data/user_data/ksnair/mlip
REPO=/home/ksnair/worktrees/mlip-mpd
CACHE=/scratch/ksnair/mlip
mkdir -p "$CACHE" "$ROOT/logs"
# Each job owns its runtime and scratch previews. Weights share the persistent HF cache.
RUNTIME="$CACHE/runtime-$SLURM_JOB_ID"
mkdir -p "$RUNTIME"
if [ ! -f "$RUNTIME/.ready" ]; then
    if [ -f "$ROOT/runtime.tar" ]; then
        tar -xf "$ROOT/runtime.tar" -C "$RUNTIME"
    else
        /data/user_data/ksnair/micromamba/envs/fmg/bin/python -m venv "$RUNTIME"
        "$RUNTIME/bin/python" -m pip install --cache-dir "$CACHE/pip-cache" \
            -r "$ROOT/runtime-requirements.txt"
    fi
    touch "$RUNTIME/.ready"
fi
export HF_HOME="$ROOT/cache/huggingface"
export TORCH_HOME="$ROOT/cache/torch"
export XDG_CACHE_HOME="$CACHE/cache-$SLURM_JOB_ID"
export TMPDIR="$CACHE/tmp-$SLURM_JOB_ID"
export NUMBA_CACHE_DIR="$CACHE/numba-$SLURM_JOB_ID"
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=4
mkdir -p "$TMPDIR"
# Prevent simultaneous writers for the same shard (including manual reruns).
exec 9>"$ROOT/locks-${RUN_NAME:-full}-${SHARD:-0}.lock"
flock -n 9 || { echo 'shard already running'; exit 1; }
LIMIT_ARGS=()
if [ -n "${LIMIT:-}" ]; then LIMIT_ARGS=(--limit "$LIMIT"); fi
"$RUNTIME/bin/python" "$REPO/spotify/scripts/embed_mpd.py" \
    --catalog "${CATALOG:-$ROOT/data/mpd/catalog.sqlite}" \
    --out-dir "$ROOT/embeddings/mpd-${RUN_NAME:-full}" \
    --preview-dir "$CACHE/previews-${RUN_NAME:-full}-${SHARD:-0}" \
    --model "${MODEL:-clap}" --shard "${SHARD:-0}/${NSHARDS:-1}" \
    --device cuda "${LIMIT_ARGS[@]}"
