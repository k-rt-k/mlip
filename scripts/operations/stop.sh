#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
aws_ready
id=$(instance_id)
state=$(instance_field "$id" State.Name)
case "$state" in
    stopped) printf 'Already stopped; EBS data retained.\n'; exit 0 ;;
    stopping) ;;
    pending) "${aws_cmd[@]}" ec2 wait instance-running --instance-ids "$id"; state=running ;;
    running) ;;
    *) die "Cannot stop instance in state $state." ;;
esac
if [[ "$state" == running ]]; then
    "${aws_cmd[@]}" ec2 stop-instances --instance-ids "$id" >/dev/null
fi
"${aws_cmd[@]}" ec2 wait instance-stopped --instance-ids "$id"
printf 'EC2 stopped; EBS volume and participant database retained. CloudFront is offline.\n'
