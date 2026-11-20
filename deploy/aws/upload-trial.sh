#!/usr/bin/env bash
# Upload a committed app revision and staged model bundle over SSH.
set -euo pipefail

if (( $# != 3 )); then
    printf 'Usage: %s BUNDLE_DIR ubuntu@EC2_HOST SSH_PRIVATE_KEY\n' "$0" >&2
    exit 2
fi

bundle=$1
target=$2
key=$3
root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)

if [[ ! -r "$bundle/SHA256SUMS" || ! -r "$key" || "$key" == *"'"* ]]; then
    printf 'Provide a staged bundle and a readable SSH key path.\n' >&2
    exit 1
fi
if [[ ! "$target" =~ ^ubuntu@[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
    printf 'Use an SSH destination such as ubuntu@EC2_HOST.\n' >&2
    exit 1
fi
source_paths=(.python-version pyproject.toml uv.lock deploy/aws evaluation_app
    baselines retrieval llm/src spotify/src youtube_music/src)
if ! git -C "$root" diff --quiet HEAD -- "${source_paths[@]}"; then
    printf 'Commit the deployment changes before uploading the app revision.\n' >&2
    exit 1
fi

ssh_args=(-o IdentitiesOnly=yes -i "$key")
ssh "${ssh_args[@]}" "$target" \
    'if ! command -v rsync >/dev/null; then sudo apt-get update && sudo apt-get install -y rsync || exit; fi
     sudo install -d -o ubuntu -g ubuntu -m 0755 /opt/playlist-lab/app /opt/playlist-lab/artifacts'
git -C "$root" archive HEAD -- "${source_paths[@]}" |
    ssh "${ssh_args[@]}" "$target" 'tar -xf - -C /opt/playlist-lab/app'
rsync -rt --relative --partial-dir=.rsync-partial \
    -e "ssh -o IdentitiesOnly=yes -i '$key'" \
    "$bundle/./SHA256SUMS" "$bundle/./evaluation-app-lookup.sqlite" "$bundle/./clap.npz" \
    "$bundle/./seed-youtube-clap.npz" "$bundle/./index/index.faiss" \
    "$bundle/./index/catalog.json" "$bundle/./index/metadata.json" "$target:/opt/playlist-lab/artifacts/"
printf 'Upload complete. On EC2 run sudo bash /opt/playlist-lab/app/deploy/aws/bootstrap.sh\n'
