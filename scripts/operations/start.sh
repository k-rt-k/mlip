#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
aws_ready
need curl
id=$(instance_id)
state=$(instance_field "$id" State.Name)
url=$(study_url)
case "$state" in
    running|pending) ;;
    stopping) "${aws_cmd[@]}" ec2 wait instance-stopped --instance-ids "$id"; state=stopped ;;
    stopped) ;;
    *) die "Cannot start instance in state $state." ;;
esac
if [[ "$state" == stopped ]]; then
    "${aws_cmd[@]}" ec2 start-instances --instance-ids "$id" >/dev/null
fi
"${aws_cmd[@]}" ec2 wait instance-status-ok --instance-ids "$id"
printf 'Waiting for study HTTPS health at %s/api/session ...\n' "$url"
for attempt in {1..48}; do
    if study_healthy "$url"; then
        printf 'Study healthy: %s\n' "$url"
        exit 0
    fi
    sleep 5
done
die 'EC2 is healthy but the paired study is not. Check status.sh and service logs; EC2 continues billing.'
