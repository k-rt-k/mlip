#!/usr/bin/env bash
# Run on a Babel node with the data mounts. Stage the serving bundle on data storage.
set -euo pipefail

if (( $# != 3 )); then
    printf 'Usage: %s BUNDLE_DIR MPD_ROOT YTM_EMBEDDINGS_DIR\n' "$0" >&2
    exit 2
fi

bundle=$1
mpd=$2
ytm=$3
index="$mpd/indexes/build-04/index"
required=(
    "$index/index.faiss" "$index/catalog.json" "$index/metadata.json"
    "$mpd/evaluation-app-lookup.sqlite" "$ytm/clap.npz" "$ytm/seed-youtube-clap.npz"
)

for file in "${required[@]}"; do
    if [[ ! -r "$file" ]]; then
        printf 'Missing serving artifact: %s\n' "$file" >&2
        exit 1
    fi
done

install -d -m 0755 "$bundle/index"
install -m 0644 "${required[@]:0:3}" "$bundle/index"
install -m 0644 "${required[@]:3}" "$bundle"
(
    cd "$bundle"
    sha256sum index/index.faiss index/catalog.json index/metadata.json \
        evaluation-app-lookup.sqlite clap.npz seed-youtube-clap.npz > SHA256SUMS
)
