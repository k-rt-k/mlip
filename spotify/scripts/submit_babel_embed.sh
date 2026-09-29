#!/bin/bash
# Accept sbatch options; locate the checkout regardless of the caller's cwd.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$REPO_ROOT"
mkdir -p logs
exec sbatch "$@" --chdir="$REPO_ROOT" --output="$REPO_ROOT/logs/%x-%j.out" \
    "$REPO_ROOT/spotify/scripts/babel_embed.sbatch"
