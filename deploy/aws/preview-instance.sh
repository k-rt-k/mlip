#!/usr/bin/env bash
# Start or stop the existing EC2 instance behind the public retrieval preview.
set -euo pipefail

action=${1:-start}
profile=${2:-${AWS_PROFILE:-mlip}}
if (( $# > 2 )) || [[ "$action" != start && "$action" != stop ]]; then
    printf 'Usage: %s [start|stop] [aws-profile]\n' "$0" >&2
    exit 2
fi

aws_cmd=(aws --profile "$profile" --region us-east-1 --no-cli-pager)
instance_id=$("${aws_cmd[@]}" cloudformation describe-stack-resource \
    --stack-name playlist-lab-migration --logical-resource-id TrialInstance \
    --query StackResourceDetail.PhysicalResourceId --output text)
state=$("${aws_cmd[@]}" ec2 describe-instances --instance-ids "$instance_id" \
    --query 'Reservations[0].Instances[0].State.Name' --output text)

case "$state" in
    stopped|stopping|pending|running) ;;
    *)
        printf 'Cannot %s the preview instance in state %s.\n' "$action" "$state" >&2
        exit 1
        ;;
esac

if [[ "$action" == stop ]]; then
    if [[ "$state" == pending ]]; then
        "${aws_cmd[@]}" ec2 wait instance-running --instance-ids "$instance_id"
    fi
    if [[ "$state" == running || "$state" == pending ]]; then
        "${aws_cmd[@]}" ec2 stop-instances --instance-ids "$instance_id" >/dev/null
    fi
    "${aws_cmd[@]}" ec2 wait instance-stopped --instance-ids "$instance_id"
    printf 'Preview instance stopped. Its disk is retained.\n'
    exit
fi

url=$("${aws_cmd[@]}" cloudformation describe-stacks --stack-name playlist-lab-preview \
    --query 'Stacks[0].Outputs[?OutputKey==`Url`].OutputValue | [0]' --output text)
if [[ ! "$url" =~ ^https://[a-z0-9]+\.cloudfront\.net$ ]]; then
    printf 'Could not find the HTTPS preview address in the CloudFormation stack.\n' >&2
    exit 1
fi

if [[ "$state" == stopping ]]; then
    "${aws_cmd[@]}" ec2 wait instance-stopped --instance-ids "$instance_id"
fi
if [[ "$state" == stopped || "$state" == stopping ]]; then
    printf 'Starting the existing preview instance.\n' >&2
    "${aws_cmd[@]}" ec2 start-instances --instance-ids "$instance_id" >/dev/null
fi
"${aws_cmd[@]}" ec2 wait instance-running --instance-ids "$instance_id"

printf 'Waiting for the HTTPS app and retrieval worker.\n' >&2
if ! curl --fail --silent --show-error --max-time 10 --retry 36 --retry-delay 5 \
    --retry-all-errors --retry-max-time 180 --output /dev/null "$url/api/session"; then
    printf 'The instance was running, but the HTTPS preview did not respond. Check its services or stop it to pause compute charges.\n' >&2
    exit 1
fi

printf '%s\n' "$url"
