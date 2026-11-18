# AWS migration plan for Playlist Lab

Start with one private CPU-only EC2 pilot. Run the web app, SQLite feedback
database, CLAP encoder, and FAISS index on that instance. The facilitator can
open the app over an SSH tunnel. This removes the live dependency on Babel
once the model artifacts have been transferred. Turn on participant-facing
HTTPS after the private deployment passes the checks below.

The starting assumptions are a team-owned AWS account in **US East (N. Virginia)**
and an **On-Demand m7i.xlarge** running **Ubuntu Server 24.04 LTS, x86_64**,
with **40 GiB of encrypted gp3 disk**. The instance has 4 vCPUs and 16 GiB RAM.
The earlier synthetic Babel probe on a GPU-masked allocation measured about
2.32 GiB RSS for the index and 0.77 GiB for the encoder. This gives us a starting
size, with EC2 cold-start, memory, latency, and concurrency still to measure.
[EC2 instance specifications](https://aws.amazon.com/ec2/instance-types/m7i/)

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
2. Configure `OPENROUTER_API_KEY` in an owner-only
   `/etc/playlist-lab/app.env` on EC2. For live playlist-only YouTube Music,
   install the team browser credential at `/etc/playlist-lab/browser.json`
   with owner `root`, group `playlist-lab`, and mode `0640`. Restart
   `playlist-lab-app.service` after configuring it.
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

- Give the teammate a named AWS identity with MFA and short-lived CLI sign-in.
  In a standalone account, an individual IAM console user can use `aws login`
  with `SignInLocalDevelopmentAccess`. Grant project-only stack and instance
  management through a scoped deployment permission set or role. CloudFormation
  also needs a scoped execution role or the underlying EC2, VPC, and public AMI
  parameter permissions. Keep account-owner and billing access separate.
  [Creating IAM users](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html)
  · [CloudFormation permissions](https://docs.aws.amazon.com/prescriptive-guidance/latest/least-privilege-cloudformation/permissions-use-cloudformation.html)
- Have the teammate generate an Ed25519 key on their SSH machine. Create a new
  change-set preview using their public key and public IPv4 address. The private
  key stays with them. For later shared shell access, create separate Linux users
  with individual keys and grant administrator access to operators who need it.
  [EC2 Linux users](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/managing-users.html)
- Share the draft PR, the serving artifact paths, and the AWS region and stack
  name. Share runtime secrets through the team's private credential channel.
  Confirm that the new operator can see the stack and reach the serving files
  before beginning the timed test.

## 5. Cut over or shut down

- For an in-person pilot, keep the SSH tunnel setup. For remote participants,
  agree on the audience and feedback retention, attach a team-controlled DNS
  name, and serve HTTPS through a reverse proxy. Open only web ports on the
  public side, scope admin SSH to the operator, and keep app and model ports on
  loopback. Verify the secure session cookie and playback from a separate
  device before sharing the URL.
- Use a fresh study database for this recommender policy. Verify a feedback
  export or encrypted backup before shutdown. Stop the instance between use
  periods if the team wants to retain the disk. Terminate it when the trial is
  over and check for remaining volumes, snapshots, or reserved public IPs.
  Stopping the instance pauses compute charges while retained storage still
  incurs charges. [EC2 lifecycle and billing](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)

**Open before provisioning.** Confirm who owns the AWS account and its budget,
who can stage and verify the artifacts from Babel, who can provide the team
YouTube Music browser credential, and whether the first trial is facilitator-only
or needs a participant-facing URL.
