#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
aws_ready
id=$(instance_id)
state=$(instance_field "$id" State.Name)
ip=$(instance_field "$id" PublicIpAddress)
url=$(study_url)
printf 'AWS account: %s | profile: %s | region: %s\n' "$("${aws_cmd[@]}" sts get-caller-identity --query Account --output text)" "$profile" "$region"
printf 'EC2: %s | state: %s | public IP: %s\nCloudFront: %s\n' "$id" "$state" "$ip" "$url"
if [[ "$state" == running ]]; then
    printf 'HTTPS /api/session: '
    if study_healthy "$url"; then echo healthy; else echo UNHEALTHY; exit 1; fi
fi
