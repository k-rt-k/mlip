# Playlist Lab AWS operations

This is the operator runbook for the existing public study at
**https://d262qnc2nmnhhz.cloudfront.net**. Run commands from a Babel Bash terminal
in the repository root. They use AWS profile `mlip` and region `us-east-1` by
default; no exported variables are needed. The instance is the `TrialInstance`
resource in CloudFormation stack `playlist-lab-migration`. The public URL and
distribution ID come from stack `playlist-lab-preview`. EC2 serves NGINX on
port 8080 through a CloudFront VPC origin, which proxies to the paired study on
loopback port 8063. `playlist-lab-study.service` uses
`/var/lib/playlist-lab/live.sqlite` on the encrypted EBS root disk. Stopping
EC2 retains that disk; **terminating the instance or deleting its stack removes
the root disk**. The private acceptance and older preview use different SQLite
files. Do not analyze those as participant results.

## 1. Fresh Babel terminal

Use the same checkout on any login node. If needed, clone the private repository
with your ordinary Git access, then `cd` to its root. Install AWS CLI v2, `curl`,
`ssh`, `tar`, `python3`, and `uv` if missing; `bash scripts/operations/status.sh`
reports missing CLI tools. CLI v2.32 or newer supports the team IAM sign-in:

```bash
cd /home/sanaokar/Projects/10718/mlip
aws --version
aws login --remote --profile mlip --region us-east-1
aws --profile mlip --region us-east-1 sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json
bash scripts/operations/status.sh
```

Sign in as the team-authorized IAM identity and verify the account/ARN before
operating resources. If the profile is configured for IAM Identity Center, use
`aws sso login --profile mlip` instead. Sign-in is interactive and may need
repeating after a long break; the scripts fail clearly when AWS authentication
is unavailable. `status.sh` discovers the instance ID, current public IP,
CloudFront URL, EC2 state, and HTTPS session endpoint. A stopped instance has
no public IP.

Create a private SSH key on the Babel account if it is absent. A new key works
because EC2 Instance Connect temporarily installs its **public** half at each
connection; the original launch key is unnecessary. Keep the private key out
of Git and do not copy it to EC2. If you use a different Babel home directory,
make a new key there.

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
test -f ~/.ssh/playlist-lab-aws || ssh-keygen -t ed25519 -f ~/.ssh/playlist-lab-aws
chmod 600 ~/.ssh/playlist-lab-aws
```

The scripts need no exported variables. `AWS_PROFILE` may select another
configured profile. Never set AWS access keys or application secrets as shell
variables for this runbook.

## 2. Start, check, and stop

These commands operate the **existing** instance. Start waits for EC2 status
checks and a successful public HTTPS `/api/session` response (up to about four
minutes). If health fails, the instance can still be running and billing.

```bash
bash scripts/operations/start.sh
bash scripts/operations/status.sh
# After exporting results, when the site should go offline:
bash scripts/operations/stop.sh
bash scripts/operations/status.sh
```

The website is offline while stopped; CloudFront keeps its URL. EBS storage
continues to incur charges. A stop does not delete `live.sqlite`. A start
does not reset it. Do not stop during an active participant session.

## 3. Connect to EC2 from Babel

Run `status.sh` first and start EC2 if stopped. The first command below checks
whether TCP 22 admits the current Babel node's **outbound public IPv4/32**.
If not, it prints the required action. `--authorize-ssh` deliberately adds
that one narrow rule to the instance's discovered security group; use it only
when you intend to change the rule. Neither command uses a fixed public IP.

```bash
bash scripts/operations/connect.sh
# Only if the command says SSH is closed to this Babel IP:
bash scripts/operations/connect.sh --authorize-ssh
```

EC2 Instance Connect accepts the public key for about 60 seconds; `connect.sh`
sends it immediately before SSH. If you switch Babel nodes, repeat the command.
Afterward, review old SSH `/32` rules and remove stale ones in the EC2 console
(instance → Security → attached security group → Inbound rules). Do not remove
the CloudFront-origin rule on port 8080. If SSH times out, check the Babel IP
from `curl -4 -fsS https://checkip.amazonaws.com`, the security group rule,
and EC2 status. `Permission denied` usually means the key push, login name
(`ubuntu`), or 60-second window failed.

## 4. Export and analyze participant results

Export while EC2 is running. The script opens the live database **read-only**,
uses SQLite's online backup API to create a consistent private snapshot, and
runs `evaluation_app`'s JSON exporter on that snapshot. It streams the JSON
and backup over SSH into a newly named, private, gitignored directory on
Babel. It checks JSON syntax and `PRAGMA integrity_check`, then writes and
checks SHA-256 hashes. It never overwrites an earlier export or writes to the
live database. The JSON and SQLite files describe the same snapshot.

```bash
bash scripts/operations/export-results.sh
```

Copy the printed directory path and use it below. Keep these files private:
they contain participant feedback. `results.py` refuses an export with zero
sessions, so the first command still succeeds before participant recruitment.

```bash
cd /home/sanaokar/Projects/10718/mlip
export_dir=$(find "$PWD/data/evaluation_app/live-exports" -mindepth 1 -maxdepth 1 -type d -name 'export-*' | sort | tail -1)
test -n "$export_dir"
( cd "$export_dir" && sha256sum -c SHA256SUMS )
uv run python -m evaluation_app.results --input "$export_dir/export.json" \
  --output "$export_dir/results.json" --participants-csv "$export_dir/participants.csv"
```

Confirm the printed screening counts and that `results.json` contains the
expected participant and baseline counts. Copy the entire export directory to
the team's approved private backup storage and run `sha256sum -c SHA256SUMS`
there too. Keep at least two verified copies before any EC2 deletion. A backup
on the EC2 root disk alone is lost when the instance is terminated.

## 5. Credential failures and renewal

The YouTube Music browser file is `/etc/playlist-lab/browser.json` on EC2,
owned by root and readable by the `playlist-lab` group. Browser cookies have
no reliable fixed lifetime: they may stop working after account sign-out,
Google security changes, or browser session changes. Check them when a
playlist-only YouTube Music panel fails, and before each study period. The
OpenRouter key is in root-only `/etc/playlist-lab/app.env`; it can be revoked,
expire if configured that way, or run out of usage credit. The key metadata
endpoint can report `expires_at`, but do not assume every key has one.
[OpenRouter key endpoint](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key)

```bash
bash scripts/operations/check-auth.sh
```

This makes authenticated, read-only account calls on EC2. It reports YouTube
Music account access and OpenRouter key validity without printing either
credential. It does not test a model completion or available spending balance;
if the LLM panel fails while the key check passes, inspect application logs,
OpenRouter credits/limits, and try one private test round. The public page and
`/api/session` can be healthy while either recommender fails.

To renew YouTube Music, sign in to **mlip.team0@gmail.com** in your own browser.
At `music.youtube.com`, open Developer Tools → Network, open Library, select an
authenticated `/browse` request, and choose **Copy as fetch (Node.js)**. Paste
only into your Babel terminal, never into chat, Git, or a shared file:

```bash
uv run python youtube_music/scripts/setup_auth.py --refresh
```

Press Ctrl-D after pasting. The script validates the account before atomically
replacing the local ignored `data/youtube_music/browser.json`. Check the email
in the browser: the validation prints a display name, not the email. Then, in
the EC2 shell opened by `connect.sh`, use the following secure transfer. First
run this **on Babel**, which discovers a fresh EC2 IP and sends a fresh key:

```bash
bash scripts/operations/connect.sh
```

In a *second* Babel terminal, run the following block to transfer the local
file; it refreshes Instance Connect so no old shell variables are needed:

```bash
cd /home/sanaokar/Projects/10718/mlip
aws login --remote --profile mlip --region us-east-1
instance_id=$(aws --profile mlip --region us-east-1 cloudformation describe-stack-resource --stack-name playlist-lab-migration --logical-resource-id TrialInstance --query StackResourceDetail.PhysicalResourceId --output text)
host=$(aws --profile mlip --region us-east-1 ec2 describe-instances --instance-ids "$instance_id" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
aws --profile mlip --region us-east-1 ec2-instance-connect send-ssh-public-key --instance-id "$instance_id" --instance-os-user ubuntu --ssh-public-key "file://$HOME/.ssh/playlist-lab-aws.pub" --query Success --output text
scp -o IdentitiesOnly=yes -i "$HOME/.ssh/playlist-lab-aws" data/youtube_music/browser.json "ubuntu@$host:/tmp/playlist-lab-browser.json"
```

In the **EC2 shell**, install and restart the public service, then return to
Babel and run `check-auth.sh`. The install replaces only the credential file,
not participant data.

```bash
sudo install -o root -g playlist-lab -m 0640 /tmp/playlist-lab-browser.json /etc/playlist-lab/browser.json
rm -f /tmp/playlist-lab-browser.json
sudo systemctl restart playlist-lab-study.service
sudo systemctl is-active playlist-lab-study.service
```

For an OpenRouter failure, obtain a valid key through the team's private
credential channel. In the EC2 shell, edit the existing root-only environment
file directly. Never type the value in a command, paste it into chat, or put it
in Git. Keep its single `OPENROUTER_API_KEY=...` line and restart:

```bash
sudoedit /etc/playlist-lab/app.env
sudo chmod 0600 /etc/playlist-lab/app.env
sudo systemctl restart playlist-lab-study.service
```

From Babel, run `bash scripts/operations/check-auth.sh` and one private LLM
round. If the study service cannot read `/etc/playlist-lab/app.env`, check its
permissions and `systemctl status` before changing the key again.

## 6. Troubleshooting and costs

From Babel, these are read-only unless a service restart is explicitly shown:

```bash
bash scripts/operations/status.sh
instance_id=$(aws --profile mlip --region us-east-1 cloudformation describe-stack-resource --stack-name playlist-lab-migration --logical-resource-id TrialInstance --query StackResourceDetail.PhysicalResourceId --output text)
aws --profile mlip --region us-east-1 ec2 describe-instance-status --instance-ids "$instance_id" --include-all-instances --output table
distribution_id=$(aws --profile mlip --region us-east-1 cloudformation describe-stacks --stack-name playlist-lab-preview --query 'Stacks[0].Outputs[?OutputKey==`DistributionId`].OutputValue | [0]' --output text)
aws --profile mlip --region us-east-1 cloudfront get-distribution --id "$distribution_id" --query 'Distribution.{Status:Status,Enabled:DistributionConfig.Enabled,Domain:DomainName}' --output table
curl -i --max-time 15 https://d262qnc2nmnhhz.cloudfront.net/api/session
```

For CloudFront 5xx counts in the last hour (CloudWatch metrics can lag), run:

```bash
aws --profile mlip --region us-east-1 cloudwatch get-metric-statistics \
  --namespace AWS/CloudFront --metric-name 5xxErrorRate \
  --dimensions "Name=DistributionId,Value=$distribution_id" Name=Region,Value=Global \
  --start-time "$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 300 \
  --statistics Average --output table
```

Connect to EC2 for logs and local health. These checks do not read or change
participant rows. The SQLite `mode=ro` URI prevents writes:

```bash
bash scripts/operations/connect.sh
sudo systemctl status --no-pager playlist-lab-study.service playlist-lab-retrieval.service playlist-lab-encoder.service nginx
sudo journalctl -u playlist-lab-study.service -u playlist-lab-retrieval.service -u playlist-lab-encoder.service -n 100 --no-pager
sudo tail -n 100 /var/log/nginx/error.log
curl -fsS http://127.0.0.1:8063/api/session
curl -fsS http://127.0.0.1:8061/health
curl -fsS http://127.0.0.1:8062/health
sudo -u playlist-lab /opt/playlist-lab/app/.venv/bin/python -c "import sqlite3; db=sqlite3.connect('file:/var/lib/playlist-lab/live.sqlite?mode=ro',uri=True); print(db.execute('PRAGMA quick_check').fetchone()[0]); print('sessions:',db.execute('SELECT count(*) FROM sessions').fetchone()[0])"
df -h /var/lib/playlist-lab
```

Read cost-to-date from Babel. Cost Explorer may need separate IAM permission
and its data can lag; this is actual reported spend, not a forecast. EC2
compute, EBS, public IPv4, CloudFront traffic, and OpenRouter are separate
charges (OpenRouter is outside AWS):

```bash
aws --profile mlip --region us-east-1 ce get-cost-and-usage \
  --time-period "Start=$(date -u +%Y-%m-01),End=$(date -u -d tomorrow +%Y-%m-%d)" \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE --output table
```

## 7. Deploy a reviewed code update and roll back

Do this between participant sessions. First export results with section 4.
Commit and review the local change. The deployed service reads code from
`/opt/playlist-lab/app`; no database, credentials, or model artifacts are in
the source archive. The following transfer uses a fresh key and creates a
backup of the currently deployed source **on EC2** before replacing it. Keep
the Babel results backup independently.

```bash
cd /home/sanaokar/Projects/10718/mlip
git status --short
git archive HEAD .python-version pyproject.toml uv.lock deploy/aws evaluation_app baselines retrieval llm/src spotify/src youtube_music/src > /tmp/playlist-lab-update.tar
instance_id=$(aws --profile mlip --region us-east-1 cloudformation describe-stack-resource --stack-name playlist-lab-migration --logical-resource-id TrialInstance --query StackResourceDetail.PhysicalResourceId --output text)
host=$(aws --profile mlip --region us-east-1 ec2 describe-instances --instance-ids "$instance_id" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
aws --profile mlip --region us-east-1 ec2-instance-connect send-ssh-public-key --instance-id "$instance_id" --instance-os-user ubuntu --ssh-public-key "file://$HOME/.ssh/playlist-lab-aws.pub" --query Success --output text
scp -o IdentitiesOnly=yes -i "$HOME/.ssh/playlist-lab-aws" /tmp/playlist-lab-update.tar "ubuntu@$host:/tmp/playlist-lab-update.tar"
rm -f /tmp/playlist-lab-update.tar
bash scripts/operations/connect.sh
```

In the EC2 shell, record the printed backup path. `uv sync` can change the
app environment; the rollback command restores the previous lockfile and
syncs it again. The study database is outside this tree.

```bash
cd /opt/playlist-lab/app
backup_dir=$(sudo mktemp -d /opt/playlist-lab/source-backup.XXXXXXXX)
sudo tar -cf "$backup_dir/source.tar" .python-version pyproject.toml uv.lock deploy/aws evaluation_app baselines retrieval llm/src spotify/src youtube_music/src
printf 'Rollback backup: %s\n' "$backup_dir/source.tar"
tar -xf /tmp/playlist-lab-update.tar -C /opt/playlist-lab/app
rm -f /tmp/playlist-lab-update.tar
/usr/local/bin/uv sync --frozen --no-dev --python /usr/bin/python3.12
/usr/local/bin/uv pip install --python /opt/playlist-lab/app/.venv/bin/python 'waitress==3.0.2'
sudo install -m 0644 deploy/aws/playlist-lab-study.service /etc/systemd/system/
sudo install -m 0644 deploy/aws/playlist-lab-preview.nginx /etc/nginx/conf.d/playlist-lab-preview.conf
sudo systemctl daemon-reload
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl restart playlist-lab-encoder.service playlist-lab-retrieval.service playlist-lab-study.service
sudo systemctl is-active playlist-lab-study.service playlist-lab-retrieval.service playlist-lab-encoder.service nginx
curl -fsS http://127.0.0.1:8063/api/session
```

From Babel, run `status.sh` and `check-auth.sh`, then complete one private
representative round for each baseline and verify the public page. If anything
fails, run this on EC2 with the `backup_dir` value printed above:

```bash
cd /opt/playlist-lab/app
sudo tar -xf "$backup_dir/source.tar" -C /opt/playlist-lab/app
/usr/local/bin/uv sync --frozen --no-dev --python /usr/bin/python3.12
/usr/local/bin/uv pip install --python /opt/playlist-lab/app/.venv/bin/python 'waitress==3.0.2'
sudo install -m 0644 deploy/aws/playlist-lab-study.service /etc/systemd/system/
sudo install -m 0644 deploy/aws/playlist-lab-preview.nginx /etc/nginx/conf.d/playlist-lab-preview.conf
sudo systemctl daemon-reload
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl restart playlist-lab-encoder.service playlist-lab-retrieval.service playlist-lab-study.service
curl -fsS http://127.0.0.1:8063/api/session
```

Neither path touches `/var/lib/playlist-lab/live.sqlite`. Do not run
`deploy/aws/bootstrap.sh` for a routine update: it reinstalls dependencies
and also restarts the private acceptance service.

## 8. End the study and remove AWS charges

Use section 4 to export and verify JSON **and** SQLite, analyze screening
counts, and place a second checked copy in private storage. Then stop the
website with `stop.sh`. Deletion is irreversible: the `playlist-lab-migration`
root EBS volume is configured `DeleteOnTermination: true`.

For final removal, first delete the CloudFront stack and wait. The VPC origin
was created outside that stack; find its ID from the distribution's origin
before deletion and delete it after the distribution is gone. Then delete the
EC2 stack. Run these only after confirming backups and that the study is over:

```bash
distribution_id=$(aws --profile mlip --region us-east-1 cloudformation describe-stacks --stack-name playlist-lab-preview --query 'Stacks[0].Outputs[?OutputKey==`DistributionId`].OutputValue | [0]' --output text)
aws --profile mlip --region us-east-1 cloudfront get-distribution-config --id "$distribution_id" --query 'DistributionConfig.Origins.Items[].VpcOriginConfig.VpcOriginId' --output text
# Record the printed vo_... as origin_id before continuing.
aws --profile mlip --region us-east-1 cloudformation delete-stack --stack-name playlist-lab-preview
aws --profile mlip --region us-east-1 cloudformation wait stack-delete-complete --stack-name playlist-lab-preview
```

Delete the recorded VPC origin, wait for its network interface to disappear,
then delete the instance stack:

```bash
origin_id=vo_ID_PRINTED_ABOVE
origin_etag=$(aws --profile mlip --region us-east-1 cloudfront get-vpc-origin --id "$origin_id" --query ETag --output text)
aws --profile mlip --region us-east-1 cloudfront delete-vpc-origin --id "$origin_id" --if-match "$origin_etag"
# Wait until GetVpcOrigin reports that the origin is gone.
while aws --profile mlip --region us-east-1 cloudfront get-vpc-origin --id "$origin_id" --query 'VpcOrigin.Status' --output text 2>/dev/null; do sleep 15; done
aws --profile mlip --region us-east-1 cloudformation delete-stack --stack-name playlist-lab-migration
aws --profile mlip --region us-east-1 cloudformation wait stack-delete-complete --stack-name playlist-lab-migration
aws --profile mlip --region us-east-1 ec2 describe-volumes --filters Name=tag:Project,Values=PlaylistLab --query 'Volumes[].{Id:VolumeId,State:State,Size:Size}' --output table
aws --profile mlip --region us-east-1 ec2 describe-snapshots --owner-ids self --filters Name=tag:Project,Values=PlaylistLab --query 'Snapshots[].SnapshotId' --output text
```

Check Cost Explorer again after billing data settles. Remove any separately
created snapshots or other retained resources only after confirming they are
no longer the needed backup. The team planned a December 15, 2026 data review
and cleanup; verify actual retention obligations before deletion.
