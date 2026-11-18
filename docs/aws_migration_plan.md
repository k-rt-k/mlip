# AWS migration plan for Playlist Lab

The private CPU trial is deployed in **`playlist-lab-migration`** in **`us-east-1`**.
Ayush can [resume the existing instance](#take-over-the-migrated-instance)
with its app, model files, and SQLite database on disk. The web app is available
through an SSH tunnel. The rest of this guide also covers rebuilding the stack
and preparing participant-facing hosting.

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
  memory use was about 2.3, 2.3, and 0.05 GiB respectively.
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
3. Check the live Linux On-Demand quote in the AWS Pricing Calculator. Multiply
   the instance rate by the expected running hours and add the disk and public
   IPv4 charges. For scale, at an illustrative `$0.20/hour`, eight hours of
   compute, eight hours of public IPv4, and one day of 40 GiB gp3 are about
   **$1.75** before transfer, storage snapshots, taxes, or OpenRouter usage.
   Continuous hosting at that illustrative rate is about **$151 per 30 days**
   for those three AWS items. Confirm the actual regional rate before launching.
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
- Share the draft PR, the serving artifact paths, and the AWS region and stack
  name. Share runtime secrets through the team's private credential channel.

### Take over the migrated instance

Ayush can sign in using his own AWS profile and manage the `playlist-lab-migration`
stack in `us-east-1`. Get the current instance ID and public address from AWS,
especially after stopping and starting the instance.

```sh
trial_instance=$(aws --profile mlip --region us-east-1 cloudformation \
  describe-stack-resource --stack-name playlist-lab-migration \
  --logical-resource-id TrialInstance --query StackResourceDetail.PhysicalResourceId --output text)
trial_host=$(aws --profile mlip --region us-east-1 ec2 describe-instances \
  --instance-ids "$trial_instance" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
```

If the instance is stopped, start it in the EC2 console, wait for it to run,
and look up its current IP again. In **EC2 → Instances → Security**, open
the instance's security group and add an inbound **SSH (TCP 22)** rule with
source **My IP** if the browser and SSH client are on the same machine. For
a different SSH client, run `curl -4 -fsSL https://checkip.amazonaws.com` on
that machine and use its IPv4 address with a `/32` suffix. Create the SSH key
once with `ssh-keygen -t ed25519 -f ~/.ssh/playlist-lab-aws`, or use an existing
key. EC2 Instance Connect sends his public key for the `ubuntu` account.
Connect within 60 seconds. The private key stays on his machine.
[EC2 Instance Connect](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-connect-methods.html)

```sh
trial_key="$HOME/.ssh/playlist-lab-aws"
aws --profile mlip --region us-east-1 ec2-instance-connect send-ssh-public-key \
  --instance-id "$trial_instance" --instance-os-user ubuntu --ssh-public-key "file://$trial_key.pub"
ssh -i "$trial_key" ubuntu@"$trial_host"
```

For later sessions, Ayush can repeat the Instance Connect step. To open the
app locally, use the same key and add `-L 8060:127.0.0.1:8060` to the SSH
command, then visit `http://127.0.0.1:8060`. If he connects from a compute
node, use the second tunnel described in section 4. For a resumed trial, run
`sudo shutdown -P +120` on EC2 to schedule another two-hour stop. The initial
timer only covers the original launch window. The app, model files, and
database remain on the EBS volume between starts.

## 5. Cut over or shut down

### Public retrieval preview

The `playlist-lab-preview` CloudFormation stack in `us-east-1` publishes
an AWS-assigned `cloudfront.net` HTTPS URL. Anyone with the link can try the
single live retrieval recommender, search for music, and build a playlist.
The paired study runs on port 8060 over the SSH tunnel. Public preview sessions
have secure cookies and a dedicated `/var/lib/playlist-lab/preview.sqlite`
database. Export this database individually if the demo feedback is useful.

```sh
aws --profile mlip --region us-east-1 cloudformation describe-stacks \
  --stack-name playlist-lab-preview \
  --query 'Stacks[0].Outputs[?OutputKey==`Url`].OutputValue' --output text
```

CloudFront forwards requests to the instance's private address through the
`playlist-lab-preview` VPC origin. Its service-managed security group is the
source of the only inbound rule on preview port 8080. NGINX applies request
limits and proxies to Waitress on loopback 8063. CloudFront forwards session
cookies and disables caching. The private connection keeps the same origin
when a stop and start changes the instance's public SSH address.
[CloudFront VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)

The first two-hour EC2 stop still applies. The HTTPS URL will resume serving
after the instance and its services start again. The CloudFront distribution
uses pay-as-you-go pricing with AWS's shared free allowance. EC2 and disk
charges follow the original trial rates.
[CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/)

To rebuild the preview on a fresh EC2 instance, upload the app revision
including `deploy/aws`, run bootstrap, and install the preview's units:

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

Check the HTTPS URL, session cookie, and a live recommendation before sharing.

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
