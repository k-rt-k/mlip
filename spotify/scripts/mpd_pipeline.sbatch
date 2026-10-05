#!/bin/bash
#SBATCH --job-name=mpd-fetch
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=28-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
set -euo pipefail
ROOT=/data/user_data/ksnair/mlip
REPO=/home/ksnair/worktrees/mlip-mpd
CACHE=/scratch/ksnair/mlip
RUNTIME="$CACHE/runtime-pipeline-$SLURM_JOB_ID"
mkdir -p "$RUNTIME"
if [ ! -f "$RUNTIME/.ready" ]; then
    tar -xf "$ROOT/runtime.tar" -C "$RUNTIME"
    touch "$RUNTIME/.ready"
fi
export HF_HOME="$ROOT/cache/huggingface" TORCH_HOME="$ROOT/cache/torch"
export XDG_CACHE_HOME="$CACHE/cache-pipeline-$SLURM_JOB_ID"
export TMPDIR="$CACHE/tmp-pipeline-$SLURM_JOB_ID"
export NUMBA_CACHE_DIR="$CACHE/numba-pipeline-$SLURM_JOB_ID"
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
mkdir -p "$TMPDIR"
EXTRA=()
if [ -n "${MAX_CHUNKS:-}" ]; then EXTRA+=(--max-chunks "$MAX_CHUNKS"); fi
if [ -n "${RATE:-}" ]; then EXTRA+=(--rate "$RATE"); fi
"$RUNTIME/bin/python" "$REPO/spotify/scripts/mpd_pipeline.py" "${ROLE:-produce}" \
    --catalog "${PIPELINE_CATALOG:-$ROOT/data/mpd/catalog.sqlite}" \
    --output "${PIPELINE_OUTPUT:-$ROOT/embeddings/mpd-full/clap}" \
    --queue "${PIPELINE_QUEUE:-$ROOT/queue-v2}" \
    --scratch "$CACHE/pipeline-${ROLE:-produce}" "${EXTRA[@]}"
