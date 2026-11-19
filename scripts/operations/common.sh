#!/usr/bin/env bash
# Shared, stateless discovery for the existing Playlist Lab deployment.
set -euo pipefail

ops_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
profile=${AWS_PROFILE:-mlip}
region=us-east-1
aws_cmd=(aws --profile "$profile" --region "$region" --no-cli-pager)
key="$HOME/.ssh/playlist-lab-aws"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "Install $1 first."; }
aws_ready() {
    need aws
    "${aws_cmd[@]}" sts get-caller-identity --query Account --output text >/dev/null ||
        die "AWS profile $profile is unavailable. Run: aws login --remote --profile $profile --region $region"
}
instance_id() {
    local id
    id=$("${aws_cmd[@]}" cloudformation describe-stack-resource \
        --stack-name playlist-lab-migration --logical-resource-id TrialInstance \
        --query StackResourceDetail.PhysicalResourceId --output text)
    [[ "$id" == i-* ]] || die 'Could not discover TrialInstance from playlist-lab-migration.'
    printf '%s\n' "$id"
}
instance_field() {
    "${aws_cmd[@]}" ec2 describe-instances --instance-ids "$1" \
        --query "Reservations[0].Instances[0].$2" --output text
}
study_url() {
    local url
    url=$("${aws_cmd[@]}" cloudformation describe-stacks --stack-name playlist-lab-preview \
        --query 'Stacks[0].Outputs[?OutputKey==`Url`].OutputValue | [0]' --output text)
    [[ "$url" =~ ^https://[a-z0-9]+\.cloudfront\.net$ ]] || die 'CloudFront URL missing from playlist-lab-preview.'
    printf '%s\n' "$url"
}
distribution_id() {
    "${aws_cmd[@]}" cloudformation describe-stacks --stack-name playlist-lab-preview \
        --query 'Stacks[0].Outputs[?OutputKey==`DistributionId`].OutputValue | [0]' --output text
}
study_healthy() {
    local url=$1
    local page
    curl -fs --max-time 10 -o /dev/null "$url/api/session" || return 1
    page=$(curl -fs --max-time 10 "$url/") || return 1
    [[ "$page" == *'body data-setup="paired"'* ]]
}
ssh_ready() {
    [[ -f "$key" && -f "$key.pub" ]] || die "SSH key missing. Run: mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keygen -t ed25519 -f $key"
    chmod 600 "$key"
    local state host
    state=$(instance_field "$1" State.Name)
    [[ "$state" == running ]] || die "Instance is $state. Run scripts/operations/start.sh first."
    host=$(instance_field "$1" PublicIpAddress)
    [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Running instance has no public IPv4 address.'
    printf '%s\n' "$host"
}
send_key() {
    local success
    success=$("${aws_cmd[@]}" ec2-instance-connect send-ssh-public-key \
        --instance-id "$1" --instance-os-user ubuntu \
        --ssh-public-key "file://$key.pub" --query Success --output text)
    [[ "$success" == True ]] || die 'EC2 Instance Connect rejected the public key.'
}
