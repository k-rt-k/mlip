#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
[[ $# == 0 || ( $# == 1 && "$1" == --authorize-ssh ) ]] || die 'Usage: connect.sh [--authorize-ssh]'
aws_ready
need curl
need ssh
id=$(instance_id)
host=$(ssh_ready "$id")
cidr="$(curl -4 -fsS --max-time 10 https://checkip.amazonaws.com | tr -d '\n')/32"
[[ "$cidr" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/32$ ]] || die 'Could not discover Babel outbound IPv4.'
group=$(instance_field "$id" 'SecurityGroups[0].GroupId')
[[ "$group" == sg-* ]] || die 'Could not discover EC2 security group.'
allowed=$("${aws_cmd[@]}" ec2 describe-security-groups --group-ids "$group" \
    --query 'SecurityGroups[0].IpPermissions[?FromPort==`22` && ToPort==`22`].IpRanges[].CidrIp' --output text)
if ! grep -qwF "$cidr" <<<"$allowed"; then
    if [[ ${1:-} != --authorize-ssh ]]; then
        die "SSH is closed to $cidr. Run connect.sh --authorize-ssh to add this Babel IP to $group."
    fi
    "${aws_cmd[@]}" ec2 authorize-security-group-ingress --group-id "$group" \
        --protocol tcp --port 22 --cidr "$cidr" >/dev/null || die 'Failed to authorize Babel IP for SSH.'
    printf 'Authorized SSH from %s on %s. Remove stale SSH /32 rules after changing nodes.\n' "$cidr" "$group" >&2
fi
send_key "$id"
exec ssh -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i "$key" "ubuntu@$host"
