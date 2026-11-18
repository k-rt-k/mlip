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

## 2. Launch the CPU instance

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

Stage only the files above from an approved Babel compute or data-transfer
host once they are available. Generate a SHA-256 manifest there for the serving
bundle. Use resumable `rsync` over SSH, directly if the source host can reach EC2
or via the operator's laptop, and verify the manifest on EC2 before serving.
The full `corpus.npz`, source audio, training artifacts, evaluation datasets,
Python virtual environments, and local test feedback are unnecessary for serving.

## 4. Install, start, and verify privately

1. Install Git and `uv` on Ubuntu and clone the repo. Use one directory such as
   `/srv/mlip/artifacts` for read-only model files and another such as
   `/var/lib/playlist-lab` for the writable study database. Use an unprivileged
   service account. Set `MLIP_STUDY_DB` to its persistent database path.
2. Start the encoder on loopback **8062**, then the FAISS worker on **8061** with
   the copied index, lookup, and two seed files. Start the app on loopback
   **8060**. Adapt the commands in [the app setup](../README.md#live-laptop-and-babel-setup)
   to use EC2 paths. Keep encoder and FAISS in separate Python environments
   and processes because their local wheels conflict through OpenMP.
3. For the first private smoke test, connect from a laptop and open
   `http://127.0.0.1:8060`. If an instance is stopped and restarted, look up
   its current address before reconnecting.

   ```sh
   ssh -N -i ~/.ssh/mlip-ec2.pem -L 8060:127.0.0.1:8060 ubuntu@EC2_HOST
   ```

4. Before participant use, run the app under a production WSGI server and
   supervise all three processes with `systemd`. Set bounded restart behavior,
   wait for worker health before starting sessions, and record service logs
   without request bodies or credentials. [Flask deployment](https://flask.palletsprojects.com/en/stable/deploying/)
5. Complete CPU-only acceptance on EC2. Check that the CPU encoder and full
   index load, then run all supported modes and both paired assignments. Measure
   readiness from cold start, combined memory including the app, repeat-query
   latency, and responsiveness with at least two simultaneous test sessions.
   Verify that a text-plus-playlist round skips the YouTube Music baseline,
   that a playlist-only round creates and removes its temporary private copy,
   and that search, playback, Keep/Reject, ratings, and export work after a
   service restart. Pick a smaller instance only after measuring headroom.

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
