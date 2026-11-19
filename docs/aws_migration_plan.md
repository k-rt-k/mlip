# AWS migration plan for Playlist Lab

The private CPU trial is deployed in **`playlist-lab-migration`** in **`us-east-1`**.
An operator can [connect from Babel](#connect-to-the-migrated-instance-from-babel)
with its app, model files, and SQLite database on disk. The web app is available
through an SSH tunnel for private acceptance or the
[public HTTPS link](#public-paired-study) for participant sessions. The rest of this
guide covers rebuilding and cleaning up both deployments.

The starting assumptions are a team-owned AWS account in **US East (N. Virginia)**
and an **On-Demand m7i.xlarge** running **Ubuntu Server 24.04 LTS, x86_64**,
with **40 GiB of encrypted gp3 disk**. The instance has 4 vCPUs and 16 GiB RAM.
[EC2 instance specifications](https://aws.amazon.com/ec2/instance-types/m7i/)

## Private trial results · November 18, 2026

- The deployment used the CloudFormation template and app snapshot `2d485ef`.
  The earlier `playlist-lab-trial` preview remains unexecuted.
- The 2.3 GiB bundle was staged on Babel at
  `/data/user_data/hpoonia/mlip/aws-serving-v1` and uploaded to
  `/opt/playlist-lab/artifacts`. All six serving file checksums matched.
  The app lives in `/opt/playlist-lab/app` and the fresh SQLite database in
  `/var/lib/playlist-lab/study.sqlite`.
- Bootstrap installed CPU-only PyTorch and enabled the encoder, HNSW worker,
  and web app. The app returned HTTP 200. The index loaded 1,025,994 tracks,
  and one warm synthetic request per mode returned 15 candidates
  for text only (0.04 s), text plus seeds (0.04 s), and seeds only (0.01 s).
  These are worker response times. The three services' individual peak
  memory use was about 2.3, 2.3, and 0.05 GiB respectively. During bootstrap,
  the app began listening about 21 seconds after the services were started.
  This measurement covers service startup after dependency installation.
- EC2 Instance Connect worked with a fresh Ed25519 key under the deployment
  operator's AWS profile. The web app returned HTTP 200 through the SSH tunnel.
  The guest's initial automatic stop was scheduled
  for 22:56 UTC on November 18. See the handoff below for the next start.
- Ayush will configure runtime credentials and run the remaining
  [acceptance checks](#4-install-start-and-verify-privately). This trial used
  synthetic probes and left the instance ready for private follow-up.

## 1. Confirm the account and spending limit

1. Ask which team or university AWS account to use, who owns billing and
   shutdown, and how many hours or days the first instance should be available.
   Enable MFA for the AWS account root user and use a delegated identity for
   day-to-day EC2 access. [AWS IAM security practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
2. In **Billing and Cost Management → Budgets**, create a cost alert for the
   agreed trial budget and make sure the billing owner receives it. Budget
   alerts notify the owner. The owner still needs to stop the instance.
   [AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html)
3. The November 18 list rates in `us-east-1` were `$0.2016/hour` for the
   Linux On-Demand instance, `$0.005/hour` for its public IPv4 address, and
   `$3.20/month` for the 40 GiB gp3 disk at baseline performance. Two running
   hours cost about **$0.41** for compute and IPv4. The disk keeps billing
   through stops. Continuous use is about **$154** for a 730-hour month,
   before credits, transfer, snapshots, taxes, or OpenRouter usage. Confirm
   the current regional rate for future launches.
   [EC2 On-Demand Pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
   · [AWS Pricing Calculator](https://calculator.aws/)
   · [EBS pricing](https://aws.amazon.com/ebs/pricing/)
   · [Public IPv4 pricing](https://aws.amazon.com/vpc/pricing/)

## 2. Preview and launch the CPU instance

Run the CLI from the operator's terminal. For an IAM console sign-in, use
AWS CLI v2.32 or newer. Omit `--remote` on a machine with a local browser.
An existing IAM Identity Center profile can use `aws sso login`.
[AWS CLI sign-in](https://docs.aws.amazon.com/signin/latest/userguide/command-line-sign-in.html)

```sh
aws login --remote --profile mlip --region us-east-1
aws sts get-caller-identity --profile mlip
```

The [CloudFormation template](../deploy/aws/trial.yaml) creates the network,
operator key entry, and trial instance. The SSH rule takes one public IPv4
address. Run the IP lookup from the machine that will open the SSH connection.
Use the operator's existing dedicated Ed25519 key or generate a new one with
`ssh-keygen -t ed25519 -f ~/.ssh/playlist-lab-aws`. Pass its `.pub` file only.

```sh
trial_stack=playlist-lab-trial
trial_key="$HOME/.ssh/playlist-lab-aws"
trial_ssh_cidr="$(curl -4 -fsSL https://checkip.amazonaws.com)/32"

aws --profile mlip --region us-east-1 cloudformation deploy \
  --stack-name "$trial_stack" --template-file deploy/aws/trial.yaml \
  --parameter-overrides "OperatorCidr=$trial_ssh_cidr" \
    "OperatorPublicKey=$(cat "$trial_key.pub")" TrialMinutes=120 \
  --no-execute-changeset
```

This prepares a preview. Stage the model bundle below before executing it. Use
the change-set identifier printed by `deploy` to inspect and execute that preview:

```sh
aws --profile mlip --region us-east-1 cloudformation describe-change-set \
  --change-set-name "$trial_change_set"
aws --profile mlip --region us-east-1 cloudformation execute-change-set \
  --change-set-name "$trial_change_set"
aws --profile mlip --region us-east-1 cloudformation wait stack-create-complete \
  --stack-name "$trial_stack"
aws --profile mlip --region us-east-1 cloudformation describe-stacks \
  --stack-name "$trial_stack" --query 'Stacks[0].Outputs'
```

Set `trial_change_set` to the printed ARN first. For a new deployment, take
`InitialPublicIp` from the stack output. The guest timer schedules one stop two
hours after its first boot configuration. Check it with
`systemctl list-timers playlist-lab-trial-stop.timer`. For a later restart, get
the current public IP from EC2 and schedule a new stop if needed. A stopped
instance retains its EBS disk.
[AWS change sets](https://docs.aws.amazon.com/cli/latest/reference/cloudformation/deploy.html)

### Console option

1. In the [EC2 console](https://console.aws.amazon.com/ec2/), set the region to
   **N. Virginia**, choose **Instances → Launch instances**, and name it
   `mlip-playlist-lab`. Select the official Ubuntu image, x86_64 architecture,
   `m7i.xlarge`, and On-Demand purchasing. [EC2 launch walkthrough](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/tutorial-launch-my-first-ec2-instance.html)
2. Create or select an SSH key pair and keep the private key on the operator's
   laptop. For the first private test, use a subnet with an internet route and
   an auto-assigned public IPv4 address. Add one inbound security-group rule
   for **SSH, TCP 22, My IP**. Leave application and model ports accessible
   over loopback only. Enable encryption for the 40 GiB gp3 root volume and
   verify **Delete on termination**. [EC2 launch options](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-launch-parameters.html)
3. Launch it and wait for the status checks to pass. Use the instance's
   **Public IPv4 DNS** or current public IP to connect. The Ubuntu username is
   normally `ubuntu`. [EC2 SSH connection guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-linux-inst-ssh.html)

   ```sh
   chmod 600 ~/.ssh/mlip-ec2.pem
   ssh -i ~/.ssh/mlip-ec2.pem ubuntu@EC2_HOST
   ```

## 3. Transfer what the app actually serves

| Item | Source and handling |
|---|---|
| App and pinned app dependencies | Clone `k-rt-k/mlip` and check out the reviewed branch or commit. Use normal GitHub authentication for the private repo. Recreate the Python 3.12 app environment with `uv sync --frozen`. |
| Prebuilt FAISS index | Copy the **entire** `/data/user_data/hpoonia/mlip/retrieval/mpd-v1/indexes/build-04/index/` directory from Babel. It contains `index.faiss`, `catalog.json`, and `metadata.json`. The serialized HNSW index is about 2.1 GiB. The loader verifies its file checksums. |
| Recording lookup | Copy `/data/user_data/hpoonia/mlip/retrieval/mpd-v1/evaluation-app-lookup.sqlite`. If that file is absent, prepare it once from `snapshot/tracks.sqlite` using the README command on a compute node, or transfer that source database and build the lookup on EC2. Match it to the index's track IDs. |
| YouTube seed vectors | Copy `clap.npz` and `seed-youtube-clap.npz` from `/data/user_data/ksnair/mlip/embeddings/ytm-eval/`. These are small and preserve coverage for video IDs already embedded. |
| CPU CLAP encoder | Record the checkpoint revision and package versions from the verified Babel encoder. Recreate the separate encoder environment with CPU-only PyTorch, then download the matching `laion/larger_clap_music_and_speech` weights from Hugging Face or transfer that exact cache if needed. The previous CPU probe used checkpoint `195c3a3e68faebb3e2088b9a79e79b43ddbda76b`. |
| Runtime credentials | Provision `OPENROUTER_API_KEY` and the team YouTube Music browser credential file separately. Set `MLIP_YTM_AUTH_FILE` to the latter's path. Keep both outside Git with owner-only permissions and supply them to the app process only. |
| Study feedback | Start with a fresh SQLite file on encrypted storage. Move real study data only if a prior session database needs to be carried over and the team approves the owner and retention. Export or back up the DB before removing the instance. |

Stage the serving files from an approved Babel compute or data-transfer host,
using a bundle directory on data storage. The script writes a SHA-256 manifest.
Run the upload from a host that can read the staged bundle and reach the EC2 SSH
rule. If the transfer host has a different public IP, use a preview with its
address or relay the bundle through the authorized operator.

```sh
bash deploy/aws/stage-artifacts.sh "$trial_bundle" \
  /data/user_data/hpoonia/mlip/retrieval/mpd-v1 \
  /data/user_data/ksnair/mlip/embeddings/ytm-eval
bash deploy/aws/upload-trial.sh "$trial_bundle" "ubuntu@$trial_host" "$trial_key"
```

Set `trial_bundle` to the chosen staging directory and `trial_host` to the EC2
address. The upload sends a committed snapshot of the app source and transfers
the model artifacts with resumable `rsync`. The serving bundle excludes the
full `corpus.npz`, audio, training files, evaluation data, virtual environments,
test feedback, and credentials.

## 4. Install, start, and verify privately

1. Run `sudo bash /opt/playlist-lab/app/deploy/aws/bootstrap.sh` on EC2. It
   verifies the model bundle, installs CPU dependencies, and starts the three
   systemd services with an unprivileged service account. The encoder listens
   on loopback **8062**, FAISS on **8061**, and the Waitress app on **8060**.
   The SQLite DB lives in `/var/lib/playlist-lab`.
2. Prepare `/etc/playlist-lab/app.env` on EC2 with
   `sudo touch /etc/playlist-lab/app.env` and
   `sudo chmod 0600 /etc/playlist-lab/app.env`.
   Use `sudoedit /etc/playlist-lab/app.env` to set `OPENROUTER_API_KEY`.
   For live playlist-only YouTube Music, install the team browser credential at
   `/etc/playlist-lab/browser.json` with owner `root`, group `playlist-lab`, and
   mode `0640`. The service already reads that path. Run
   `sudo systemctl restart playlist-lab-app.service` after configuring credentials.
3. For the first private smoke test, connect from a laptop and open
   `http://127.0.0.1:8060`. If an instance is stopped and restarted, look up
   its current address before reconnecting.

   ```sh
   ssh -N -i ~/.ssh/mlip-ec2.pem -L 8060:127.0.0.1:8060 ubuntu@EC2_HOST
   ```

   For a Babel operator and laptop browser, open that tunnel on Babel first.
   Then forward laptop port 8060 to the same Babel host's loopback port 8060
   in a second SSH session.

4. Complete CPU-only acceptance on EC2. Check that the CPU encoder and full
   index load, then run all supported modes and both paired assignments. Measure
   readiness from cold start, combined memory including the app, repeat-query
   latency, and responsiveness with at least two simultaneous test sessions.
   Verify that a text-plus-playlist round skips the YouTube Music baseline,
   that a playlist-only round creates and removes its temporary private copy,
   and that search, playback, Keep/Reject, ratings, and export work after a
   service restart. Pick a smaller instance only after measuring headroom.

## Hand off to a teammate

- The account owner created a named IAM console user for the teammate and
  attached `SignInLocalDevelopmentAccess` and `PowerUserAccess`. This is the
  simplified setup for the class project. `PowerUserAccess` allows changes to
  resources across the account and can incur charges. Remove it when the
  teammate no longer needs deployment access.
  [PowerUserAccess policy](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/PowerUserAccess.html)
- Share the IAM sign-in URL and username, and deliver the temporary password
  through the team's password manager. The teammate resets the password on first
  sign-in, can enroll MFA, and verifies their own CLI profile using the commands
  in section 2. Sign-in and MFA enrollment are unverified. The CLI identity
  should be the teammate's IAM user in the project account.
  [IAM user sign-in](https://docs.aws.amazon.com/signin/latest/userguide/introduction-to-iam-user-sign-in-tutorial.html)
- Ayush handles his own AWS sign-in, SSH key, and service credentials. Use the
  steps below to resume the existing deployment. For a fresh deployment, use a
  new stack name and pass the operator's own public key and IPv4 address.
- For another teammate who will operate AWS, create a separate IAM console
  user and choose **Copy permissions** from the existing operator at the
  permissions step. Each teammate uses their own AWS login and SSH key.
  People trying the public preview can use its link directly.
  [Create an IAM user](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html)
- Share the draft PR, the serving artifact paths, and the AWS region and stack
  name. Share runtime secrets through the team's private credential channel.

### Connect to the migrated instance from Babel

The SSH key at `~/.ssh/playlist-lab-aws` stays on Babel. Create it only once.
Each EC2 start can change the public IP. From a **Babel Bash shell**, copy this
block for each SSH session:

```sh
trial_instance=$(aws --no-cli-pager --profile mlip --region us-east-1 \
  cloudformation describe-stack-resource --stack-name playlist-lab-migration \
  --logical-resource-id TrialInstance \
  --query StackResourceDetail.PhysicalResourceId --output text)
trial_host=$(aws --no-cli-pager --profile mlip --region us-east-1 \
  ec2 describe-instances --instance-ids "$trial_instance" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
trial_key="$HOME/.ssh/playlist-lab-aws"
printf 'EC2 host: %s; Babel outbound IP: ' "$trial_host"
curl -4 -fsSL https://checkip.amazonaws.com
aws --no-cli-pager --profile mlip --region us-east-1 \
  ec2-instance-connect send-ssh-public-key --instance-id "$trial_instance" \
  --instance-os-user ubuntu --ssh-public-key "file://$trial_key.pub" \
  --query Success --output text
ssh -o IdentitiesOnly=yes -i "$trial_key" ubuntu@"$trial_host"
```

Start the instance first if `trial_host` prints `None`. EC2 Instance Connect
accepts the public key for about 60 seconds, so run SSH immediately after the
`True` response. In **EC2 → Instances → Security**, use the security group
*attached to this instance* and allow SSH from **Babel's outbound IPv4/32**;
"My IP" in a browser on another computer is a different address. On November
19, the attached group was `sg-049d2e302b8c18482`, Babel's address was
`128.2.155.230`, and port 22 was reachable. Recheck after changing Babel nodes
or networks. The key file is private; do not copy it to EC2 or Git.
[EC2 Instance Connect](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-connect-methods.html)

For the private app, add `-L 8060:127.0.0.1:8060` to the `ssh` line. This puts
the tunnel on Babel's loopback; a laptop browser needs a second tunnel into
Babel, as described in section 4. For a short setup session, run
`sudo shutdown -P +120` on EC2 to schedule a two-hour stop. Cancel that timer
with `sudo shutdown -c` before the one- or two-day participant collection.
The OpenRouter environment file and YouTube Music browser file remain on EC2
between stop and start. Reinstall the browser file only when its headers expire;
the SSH key stays on Babel and needs no regeneration.

## 5. Cut over or shut down

### Public paired study

The `playlist-lab-preview` CloudFormation stack in `us-east-1` publishes
the AWS-assigned `https://d262qnc2nmnhhz.cloudfront.net` address. On November
19, the same link began serving the paired study. The public app uses secure
cookies and `/var/lib/playlist-lab/live.sqlite`; private acceptance and old
preview databases remain separate. Public page and session-state checks passed
after cutover. The first two real sessions will verify the participant flow.

#### Switch the existing HTTPS link to the paired study

The public study uses the same CloudFront address and NGINX origin. Its separate
Waitress service listens on loopback port 8063 and writes to
`/var/lib/playlist-lab/live.sqlite`. The private acceptance database
(`study.sqlite`) and old preview database (`preview.sqlite`) remain separate.
The paired study requires both baseline credentials. Complete these steps before
sharing the link with participants:

1. Refresh the team account's local browser credentials with
   `uv run python youtube_music/scripts/setup_auth.py --refresh`. Use a fresh
   **Copy as fetch (Node.js)** request from `mlip.team0@gmail.com`. The command
   checks the account before replacing the local file. Do not commit or paste
   the headers into chat.
2. Start the existing EC2 instance with `bash deploy/aws/preview-instance.sh
   start mlip`. Look up its current public IP, then connect with the operator's
   SSH key as described in [the Babel connection steps](#connect-to-the-migrated-instance-from-babel).
   Upload the reviewed app revision from the repository root:

   ```sh
   git archive HEAD .python-version pyproject.toml uv.lock deploy/aws evaluation_app \
     baselines retrieval llm/src spotify/src youtube_music/src | \
     ssh -i "$trial_key" ubuntu@"$trial_host" \
       'tar -xf - -C /opt/playlist-lab/app'
   scp -i "$trial_key" data/youtube_music/browser.json \
     ubuntu@"$trial_host":/tmp/playlist-lab-browser.json
   ```

3. On EC2, put the OpenRouter key in `/etc/playlist-lab/app.env` using
   `sudoedit /etc/playlist-lab/app.env`, with one line
   `OPENROUTER_API_KEY=<your key>`. Do not place the value in a shell command or
   Git. Install the browser file for the service account:

   ```sh
   sudo chmod 0600 /etc/playlist-lab/app.env
   sudo install -o root -g playlist-lab -m 0640 \
     /tmp/playlist-lab-browser.json /etc/playlist-lab/browser.json
   rm -f /tmp/playlist-lab-browser.json
   sudo systemctl restart playlist-lab-app.service
   ```

4. Verify the team account privately with
   `sudo -u playlist-lab /opt/playlist-lab/app/.venv/bin/python -c
   'from youtube_music.src.playlists import make_client;
   assert make_client("/etc/playlist-lab/browser.json").get_account_info().get("accountName")'`
   from `/opt/playlist-lab/app`. Complete a paired test session in each
   assignment, including a playlist-only YouTube Music round. Confirm that its
   temporary private playlist was deleted and export the private test database.
5. Run `sudo bash /opt/playlist-lab/app/deploy/aws/activate-public-study.sh`.
   The script checks that both credential files exist, stops the old preview
   service, starts the paired service, and restores the preview if startup fails.
   Verify the HTTPS page and `/api/session` response before sharing it. Use the
   first two real participants, one per baseline assignment, as the supervised
   end-to-end pilot through that link; then verify both panels, playback,
   Keep/Reject, finish, and an export. The app sets a secure session cookie and
   does not store raw requests or search queries.

Spandan facilitates the first two real sessions and owns the export. Run
collection for one or two days, then export
`/var/lib/playlist-lab/live.sqlite` from `/opt/playlist-lab/app` on EC2:

```sh
sudo -u playlist-lab .venv/bin/python -m evaluation_app \
  --db /var/lib/playlist-lab/live.sqlite \
  --export /var/lib/playlist-lab/live-export-YYYYMMDD.json
```

Copy that export through the operator's private SSH connection and analyze it
with the commands in [README](../README.md#analyze-participant-results). Keep it private and
confirm its participant screening counts before stopping the instance. The
team will delete the feedback database on December 15 after reviewing the
export. The instance remains running until an operator stops it; no shutdown
was scheduled at the November 19 cutover check.

```sh
aws --profile mlip --region us-east-1 cloudformation describe-stacks \
  --stack-name playlist-lab-preview \
  --query 'Stacks[0].Outputs[?OutputKey==`Url`].OutputValue' --output text
```

CloudFront forwards requests to the instance's private address through the
`playlist-lab-preview` VPC origin. Its service-managed security group is the
source of the inbound rule on origin port 8080. NGINX applies request
limits and proxies to Waitress on loopback 8063. CloudFront forwards session
cookies and disables caching. The private connection keeps the same origin
when a stop and start changes the instance's public SSH address.
[CloudFront VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)

The CloudFront distribution uses pay-as-you-go pricing with AWS's shared free
allowance. EC2 and disk charges follow the original trial rates.
[CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/)

#### Restart or stop the public study

Use your signed-in AWS profile from any terminal with AWS CLI v2 and curl.
The script starts the existing EC2 instance, waits for the HTTPS app, and
prints the same CloudFront URL. The paired-study service starts on boot.
The EC2 console can also start the instance directly. Expect the instance
boot and model load on each start, while CloudFront and its certificate
keep serving the same hostname.

```sh
bash deploy/aws/preview-instance.sh start mlip
bash deploy/aws/preview-instance.sh stop mlip
```

Run the second command when collection and export checks are done. The first two-hour
timer only applies to the original launch. Later starts stay up until an
operator stops them or sets a new timer. While stopped, the link is offline
and the server keeps its installed files, database, and private address.
[EC2 stop and start](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html)

#### Rebuild on a replacement instance

To rebuild the public origin on a fresh EC2 instance, upload the app revision
including `deploy/aws`, run bootstrap, and install the staging preview's units:

```sh
cd /opt/playlist-lab/app
sudo apt-get update
sudo apt-get install -y nginx
sudo install -m 0644 deploy/aws/playlist-lab-preview.service /etc/systemd/system/
sudo install -m 0644 deploy/aws/playlist-lab-preview.nginx /etc/nginx/conf.d/playlist-lab-preview.conf
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now playlist-lab-preview.service nginx
sudo systemctl reload nginx
```

Install the two runtime credentials and run
`sudo bash /opt/playlist-lab/app/deploy/aws/activate-public-study.sh` before
recruiting participants.

Create an EC2 VPC origin in CloudFront using the instance ARN, IPv4, and
HTTP port 8080, with **HTTP only** for the private origin connection. When
the origin is deployed, use the origin ID and EC2 private DNS name for
`origin_id` and `trial_private_dns`. Set `trial_group` to the instance's
existing security group ID and `origin_group` to the ID of
`CloudFront-VPCOrigins-Service-SG` in that VPC.

```sh
aws --profile mlip --region us-east-1 cloudformation deploy \
  --stack-name playlist-lab-preview --template-file deploy/aws/preview.yaml \
  --parameter-overrides "InstanceSecurityGroup=$trial_group" \
    "CloudFrontSecurityGroup=$origin_group" "OriginId=$origin_id" \
    "OriginPrivateDns=$trial_private_dns"
```

Updating the existing `playlist-lab-preview` stack keeps its hostname and
requires the new origin configuration to propagate. Recreating the
distribution assigns a new hostname. Check the HTTPS URL, session cookie,
and a live recommendation before sharing.

### December 15 cleanup

December 15, 2026 is the team's export and cleanup date. The root disk is
retained on stop. Deletion requires an operator action. To bring the trial to
an end, export the feedback needed for the project and verify the export.
Delete the `playlist-lab-preview` stack first and wait for it to finish.
Then delete its VPC origin in the CloudFront console and wait for AWS to
remove its service-managed network interface. Delete
`playlist-lab-migration` only after confirming the existing instance and
its disk can be removed. The root disk is set to delete on termination.
Check for any remaining volumes or snapshots retained by the team.
[EC2 lifecycle and billing](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
