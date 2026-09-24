#!/bin/bash
# One shard of the preview -> embedding pipeline on Babel.
#
# Submit from the repo root (logs/ must exist: `mkdir -p logs`):
#   sbatch --export=ALL,SHARD=0,NSHARDS=4,MODEL=clap,SPOTIFY_USER=kartik \
#          spotify/scripts/babel_embed.sbatch
#
# Previews are cached on the node's local /scratch. To reuse a shard's audio,
# pin the job to the node that holds it:
#   NODE=$(python spotify/scripts/where_shards.py \
#            --out-dir /data/user_data/$USER/mlip/embeddings --node clap-shard-0-of-4)
#   sbatch --nodelist=$NODE --export=ALL,SHARD=0,... spotify/scripts/babel_embed.sbatch
#
#SBATCH --job-name=embed
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=2-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=logs/%x-%j.out
set -euo pipefail

: "${SHARD:?set SHARD}" "${NSHARDS:?set NSHARDS}" "${MODEL:?set MODEL}"
: "${SPOTIFY_USER:?set SPOTIFY_USER}"
PYTHON="${PYTHON:-python}"
PREVIEW_DIR="${PREVIEW_DIR:-/scratch/$USER/mlip/previews}"
OUT_DIR="${OUT_DIR:-/data/user_data/$USER/mlip/embeddings}"
export PYTHONUNBUFFERED=1

# Where this attempt landed. With --requeue the same job id can resume on a
# different node, whose /scratch does not have the earlier attempt's audio.
echo "[$(date -Is)] job=$SLURM_JOB_ID restart=${SLURM_RESTART_COUNT:-0}" \
     "node=$(hostname) shard=$SHARD/$NSHARDS model=$MODEL previews=$PREVIEW_DIR"

mkdir -p "$PREVIEW_DIR" "$OUT_DIR"
"$PYTHON" spotify/scripts/embed.py --user "$SPOTIFY_USER" --model "$MODEL" \
    --shard "$SHARD/$NSHARDS" --preview-dir "$PREVIEW_DIR" --out-dir "$OUT_DIR"
