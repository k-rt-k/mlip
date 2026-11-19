#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
aws_ready
id=$(instance_id)
host=$(ssh_ready "$id")
send_key "$id"
ssh -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
    -i "$key" "ubuntu@$host" 'bash -se' <<'REMOTE'
set -euo pipefail
cd /opt/playlist-lab/app
sudo -u playlist-lab .venv/bin/python - <<'PY'
from pathlib import Path
from youtube_music.src.playlists import make_client

path = Path('/etc/playlist-lab/browser.json')
assert path.is_file(), 'YouTube Music browser credentials missing'
try:
    authenticated = bool(make_client(path).get_account_info().get('accountName'))
except Exception:
    raise SystemExit('YouTube Music authentication failed; refresh browser headers')
assert authenticated, 'YouTube Music authentication failed'
print('YouTube Music account check: OK')
PY
sudo .venv/bin/python - <<'PY'
import urllib.error
import urllib.request

with open('/etc/playlist-lab/app.env', encoding='utf-8') as stream:
    values = [line.removeprefix('OPENROUTER_API_KEY=').strip() for line in stream
              if line.startswith('OPENROUTER_API_KEY=')]
assert len(values) == 1 and values[0], 'OpenRouter key missing'
request = urllib.request.Request('https://openrouter.ai/api/v1/key',
                                 headers={'Authorization': 'Bearer ' + values[0]})
try:
    with urllib.request.urlopen(request, timeout=12) as response:
        assert response.status == 200
except urllib.error.HTTPError as error:
    raise SystemExit(f'OpenRouter key check failed: HTTP {error.code}')
except urllib.error.URLError:
    raise SystemExit('OpenRouter key check failed: network error')
print('OpenRouter key authentication: OK')
PY
REMOTE
