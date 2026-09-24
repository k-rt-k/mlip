# Running the embedding pipeline on Babel

Sharded preview -> embedding runs, one GPU job per shard. Code:
`spotify/scripts/babel_embed.sbatch` (job), `spotify/scripts/embed.py`
(chunked, resumable worker), `spotify/src/jobs.py` (sharding + node log),
`spotify/scripts/where_shards.py` (which node holds which shard).

## Storage layout

| what | where | why |
|------|-------|-----|
| preview MP3s | `/scratch/$USER/mlip/previews` on the job's node | 1.4 TB free on the node checked; **node-local and expunged after 28 days past 65% full** — a cache, not storage |
| embeddings | `/data/user_data/$USER/mlip/embeddings/<model>/shard-i-of-N.npz` | persistent; one file per shard, so jobs never write the same file |
| node log | `/data/user_data/$USER/mlip/embeddings/manifest/<model>-shard-i-of-N.jsonl` | records the node, job id and restart count of every attempt |

**Enforced, not just defaulted:** `embed.py` refuses to start unless the
output directory resolves (symlinks and `..` included) under `/data/user_data`
and outside the git repo — the clone itself may live in `/data/user_data`, so
"under /data/user_data" alone would not keep output out of git. The check is
`jobs.require_persistent_out`, a raise rather than an `assert` (which
`python -O` would strip). As a consequence real runs happen only where
`/data/user_data` is mounted: Babel compute nodes with an active job.

For a laptop test, `--local-test` lifts only the `/data/user_data` rule:

    python spotify/scripts/embed.py --user kartik --model clap --local-test --limit 5

It defaults to the repo's git-ignored `data/spotify/embeddings-local/`, prints a
warning, and tags the run `local_test: true` in the shard's manifest. The git
rule still holds: a path inside the repo is accepted only if `git check-ignore`
confirms git ignores it.
Verified 2026-09-24 that the real path resolves to itself on `babel-t9-20`.

`/data/user_data` was 92% full (43 GB free) on 2026-09-23. Embeddings are
small (2.26M x 512 float32 ~ 4.6 GB) but clear space before large runs.

## Why the node is logged

Cross-node scratch (`/compute/<node>`) is **disabled** on Babel (checked
2026-09-23: map present, not loaded, no NFS server on nodes). A shard's audio
can only be read by a job on the node that holds it. So every attempt logs its
node, and reuse means pinning a job there:

    NODE=$(python spotify/scripts/where_shards.py \
             --out-dir /data/user_data/$USER/mlip/embeddings --node clap-shard-0-of-4)
    sbatch --nodelist=$NODE --export=ALL,SHARD=0,NSHARDS=4,MODEL=clap,SPOTIFY_USER=kartik \
           spotify/scripts/babel_embed.sbatch

To pull audio from another node instead, you need a running job on that node
(ssh to a node is only allowed while you hold a job there).

## Submitting

    mkdir -p logs
    for i in 0 1 2 3; do
      sbatch --export=ALL,SHARD=$i,NSHARDS=4,MODEL=clap,SPOTIFY_USER=kartik \
             spotify/scripts/babel_embed.sbatch
    done

Optional env: `PYTHON` (interpreter with the deps), `PREVIEW_DIR`, `OUT_DIR`.
The track list comes from `data/spotify/<user>/` in the repo clone — copy the
inventory JSON there first (it is gitignored).

## Constraints this design works around

- **One Deezer budget for all jobs.** Compute nodes exit through a small NAT
  pool (128.2.155.x), and Deezer limits per IP (50 req / 5 s). Each shard paces
  at 1/N of 5 req/s, so N jobs never exceed half the ceiling together. Adding
  jobs does *not* speed up downloading.
- **Few jobs are enough.** Downloading caps the feed at ~5-10 clips/s; one GPU
  job should embed faster than that (estimate from Mac profiling, not measured
  on Babel). Use 2-4 shards, not dozens.
- **Preemption kills without warning** (`GraceTime=0`), and evicts the youngest
  jobs first. The worker saves after every chunk (atomic write), so an
  eviction loses at most one chunk; `--requeue` restarts it and it resumes.
  Long-lived jobs are the least likely to be evicted.
- **A requeue can land on a different node.** The shard's earlier audio stays
  on the old node; the new attempt re-downloads what it has not embedded yet
  (already-embedded tracks are skipped). The node log shows each attempt.
