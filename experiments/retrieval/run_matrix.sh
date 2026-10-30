#!/usr/bin/env bash
# Run every inference-only YAML combination, then evaluate them together.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG="$ROOT/experiments/retrieval/hp.yaml"
CONFIG_DIR="$ROOT/data/retrieval/prompt_playlist_matrix/configs"
PREDICTION_DIR="$ROOT/predictions/prompt_playlist_matrix"
RESULT_DIR="$ROOT/results/prompt_playlist_matrix"
PYTHON_BIN="${PYTHON_BIN:-/data/user_data/hpoonia/mlip/encoder-venv/bin/python}"
mkdir -p "$CONFIG_DIR" "$PREDICTION_DIR" "$RESULT_DIR"

for aggregation in mean prompt_weighted_mean top_k_mean; do
  for retrieval in text_only seed_only early_fusion multi_query; do
    for ranking in cosine weighted_score rrf; do
      for seed_similarity in mean max top_k_mean; do
        name="agg-${aggregation}__ret-${retrieval}__rank-${ranking}__seed-${seed_similarity}"
        config="$CONFIG_DIR/$name.yaml"
        output="$PREDICTION_DIR/$name.json"
        report="$RESULT_DIR/$name.report.json"
        if [[ -e "$output" || -e "$report" ]]; then
          echo "Skipping existing $name"
          continue
        fi
        BASE_CONFIG="$CONFIG" CONFIG_PATH="$config" EXP_NAME="$name" EXP_OUTPUT="$output" EXP_REPORT="$report" \
        EXP_AGG="$aggregation" EXP_RETRIEVAL="$retrieval" EXP_RANKING="$ranking" EXP_SEED_SIM="$seed_similarity" \
        "$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path
import yaml
cfg = yaml.safe_load(Path(os.environ['BASE_CONFIG']).read_text())
cfg['seed_aggregation']['method'] = os.environ['EXP_AGG']
cfg['retrieval']['method'] = os.environ['EXP_RETRIEVAL']
cfg['ranking']['method'] = os.environ['EXP_RANKING']
cfg['ranking']['seed_similarity'] = os.environ['EXP_SEED_SIM']
cfg['paths']['output'] = os.environ['EXP_OUTPUT']
cfg['paths']['report'] = os.environ['EXP_REPORT']
Path(os.environ['EXP_OUTPUT']).parent.mkdir(parents=True, exist_ok=True)
Path(os.environ['EXP_REPORT']).parent.mkdir(parents=True, exist_ok=True)
Path(os.environ['CONFIG_PATH']).write_text(yaml.safe_dump(cfg, sort_keys=False))
PY
        "$PYTHON_BIN" -m experiments.retrieval.run_configured_playlist --config "$config"
      done
    done
  done
done

"$PYTHON_BIN" -m evaluation.evaluate_many "$PREDICTION_DIR" --results-dir "$RESULT_DIR/evaluation"
