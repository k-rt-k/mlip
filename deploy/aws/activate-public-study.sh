#!/usr/bin/env bash
# Switch the existing HTTPS origin from the preview to the paired study.
set -euo pipefail

if (( EUID != 0 )); then
    printf 'Run this script with sudo on the study instance.\n' >&2
    exit 1
fi

app=/opt/playlist-lab/app
env_file=/etc/playlist-lab/app.env
auth_file=/etc/playlist-lab/browser.json
if [[ ! -s "$env_file" || ! -s "$auth_file" ]] ||
    ! grep -Eq '^OPENROUTER_API_KEY=[^[:space:]]+' "$env_file"; then
    printf 'Install the OpenRouter environment file and YouTube Music browser credentials first.\n' >&2
    exit 1
fi

install -m 0644 "$app/deploy/aws/playlist-lab-study.service" /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/playlist-lab-study.service
systemctl daemon-reload
systemctl disable --now playlist-lab-preview.service
if ! systemctl enable --now playlist-lab-study.service ||
    ! curl -fsS --max-time 5 http://127.0.0.1:8063/api/session >/dev/null; then
    systemctl disable --now playlist-lab-study.service || true
    systemctl enable --now playlist-lab-preview.service
    printf 'Study service failed; restored the retrieval preview.\n' >&2
    exit 1
fi
printf 'Public origin now serves the paired study using /var/lib/playlist-lab/live.sqlite.\n'
