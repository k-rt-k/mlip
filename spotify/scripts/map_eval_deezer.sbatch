#!/bin/bash
#SBATCH --job-name=ytm-eval-deezer
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=1-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/data/user_data/ksnair/mlip/logs/%x-%j.out
# Map eval songs to Deezer and CLAP-embed previews; resumable, so requeues continue.
# Submit from the repo root: sbatch spotify/scripts/map_eval_deezer.sbatch [extra args, e.g. --limit 30 --out ...]
set -euo pipefail
ROOT=/data/user_data/ksnair/mlip
CACHE=/scratch/ksnair/mlip
RUNTIME="$CACHE/runtime-ytm-$SLURM_JOB_ID"
mkdir -p "$RUNTIME"
if [ ! -f "$RUNTIME/.ready" ]; then
    tar -xf "$ROOT/runtime.tar" -C "$RUNTIME"
    touch "$RUNTIME/.ready"
fi
export HF_HOME="$ROOT/cache/huggingface" TORCH_HOME="$ROOT/cache/torch"
export XDG_CACHE_HOME="$CACHE/cache-ytm-$SLURM_JOB_ID" NUMBA_CACHE_DIR="$CACHE/numba-ytm-$SLURM_JOB_ID"
export TMPDIR="$CACHE/tmp-ytm-$SLURM_JOB_ID" PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
mkdir -p "$TMPDIR"
"$RUNTIME/bin/python" "$SLURM_SUBMIT_DIR/spotify/scripts/map_eval_deezer.py" --embed "$@"
