#!/usr/bin/env bash
# Creates a consistent SQLite backup and JSON export, then streams both over SSH.
set -euo pipefail
source "$(dirname "$0")/common.sh"
[[ $# -le 1 ]] || die 'Usage: export-results.sh [private-output-directory]'
aws_ready
need tar
need sha256sum
id=$(instance_id)
host=$(ssh_ready "$id")
out_parent=${1:-$ops_root/data/evaluation_app/live-exports}
mkdir -p "$out_parent"
chmod 700 "$out_parent"
out=$(mktemp -d "$out_parent/export-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
chmod 700 "$out"
send_key "$id"
if ! ssh -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
    -i "$key" "ubuntu@$host" 'bash -se' <<'REMOTE' | tar -xf - -C "$out"; then
set -euo pipefail
cd /opt/playlist-lab/app
d=$(sudo -u playlist-lab mktemp -d /var/lib/playlist-lab/export.XXXXXXXX)
trap 'sudo -u playlist-lab rm -f "$d/export.json" "$d/live.sqlite"; sudo -u playlist-lab rmdir "$d"' EXIT
sudo -u playlist-lab .venv/bin/python - "$d/live.sqlite" <<'PY'
import sqlite3
import sys
from pathlib import Path

source = sqlite3.connect(Path('/var/lib/playlist-lab/live.sqlite').as_uri() + '?mode=ro', uri=True)
destination = sqlite3.connect(sys.argv[1])
with destination:
    source.backup(destination)
assert destination.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
destination.close()
source.close()
PY
sudo -u playlist-lab .venv/bin/python -m evaluation_app --db "$d/live.sqlite" --export "$d/export.json"
sudo -u playlist-lab tar -C "$d" -cf - export.json live.sqlite
REMOTE
    die "Export/transfer failed. Incomplete files, if any, are in $out; do not use them."
fi
python3 -m json.tool "$out/export.json" >/dev/null || die 'JSON export is invalid.'
sqlite_check=$(python3 - "$out/live.sqlite" <<'PY'
import sqlite3, sys
db = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)
print(db.execute('PRAGMA integrity_check').fetchone()[0])
PY
)
[[ "$sqlite_check" == ok ]] || die "SQLite backup failed integrity check: $sqlite_check"
(cd "$out" && sha256sum export.json live.sqlite > SHA256SUMS && sha256sum -c SHA256SUMS)
chmod 600 "$out"/*
printf 'Private JSON export and SQLite backup: %s\n' "$out"
printf 'Analyze: uv run python -m evaluation_app.results --input "%s/export.json" --output "%s/results.json" --participants-csv "%s/participants.csv"\n' "$out" "$out" "$out"
