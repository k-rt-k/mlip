#!/usr/bin/env bash
# Run as root on the trial instance after copying the source and serving artifacts.
set -euo pipefail

root=/opt/playlist-lab
app="$root/app"
artifacts="$root/artifacts"
encoder="$root/encoder-venv"
service_user=playlist-lab

if (( EUID != 0 )); then
    printf 'Run this script with sudo on the trial instance.\n' >&2
    exit 1
fi

for file in index/index.faiss index/catalog.json index/metadata.json \
    evaluation-app-lookup.sqlite clap.npz seed-youtube-clap.npz SHA256SUMS; do
    if [[ ! -r "$artifacts/$file" ]]; then
        printf 'Missing serving artifact: %s\n' "$artifacts/$file" >&2
        exit 1
    fi
done
(cd "$artifacts" && sha256sum --check SHA256SUMS)

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl ec2-instance-connect libgomp1 libsndfile1 python3.12 rsync

if [[ ! -x /usr/local/bin/uv ]]; then
    curl -fsSL https://astral.sh/uv/0.9.26/install.sh |
        env UV_UNMANAGED_INSTALL=/usr/local/bin sh
fi
uv=/usr/local/bin/uv
export UV_PYTHON_DOWNLOADS=never
cd "$app"
"$uv" sync --frozen --no-dev --python /usr/bin/python3.12
"$uv" pip install --python "$app/.venv/bin/python" 'waitress==3.0.2'

"$uv" venv --allow-existing --python /usr/bin/python3.12 "$encoder"
"$uv" pip install --python "$encoder/bin/python" \
    --index https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
"$uv" pip install --python "$encoder/bin/python" \
    'transformers==5.17.0' 'numpy==2.4.6' 'librosa==0.11.0'

if ! id "$service_user" >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --home-dir /var/lib/playlist-lab \
        --shell /usr/sbin/nologin "$service_user"
fi
install -d -m 0750 -o "$service_user" -g "$service_user" /var/lib/playlist-lab
install -d -m 0750 -o root -g "$service_user" /etc/playlist-lab
units=(playlist-lab-encoder.service playlist-lab-retrieval.service playlist-lab-app.service)
for unit in "${units[@]}"; do
    install -m 0644 "$app/deploy/aws/$unit" "/etc/systemd/system/$unit"
done
systemd-analyze verify "${units[@]/#//etc/systemd/system/}"
systemctl daemon-reload
systemctl enable "${units[@]}"
systemctl restart "${units[@]}"
