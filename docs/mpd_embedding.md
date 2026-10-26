# MPD preview embeddings on Babel

Implementation worktree: `/home/ksnair/worktrees/mlip-mpd`, branch
`feat/mpd-embeddings`, based on `6292316`.

## Data and storage

The complete MPD ZIP was downloaded on 2026-09-29 from
https://www.kaggle.com/datasets/himanshuwagh/spotify-million (5,585,657,586 bytes,
1,000 slices). It retains the original README, license, and MD5 manifest.
Download provenance and verification status are recorded alongside the archive
in `/data/user_data/ksnair/mlip/data/mpd/archive.source.json`.

`spotify/scripts/build_mpd_catalog.py` reads the ZIP without extracting all JSON,
using `spotify/src/mpd.py`. SQLite ingestion is transactional per slice and
resumes without double-counting. Build on scratch for speed, then publish the
finished catalog and summary to persistent storage. Final validation requires
1,000,000 playlists, 66,346,428 entries, and 2,262,292 unique Spotify track IDs.
The original ZIP preserves playlist membership and ordering for later evaluation.

## Preview resolution

MPD has no ISRCs. `spotify/scripts/embed_mpd.py` searches Deezer with artist and
full track title, inspecting up to 25 candidates. A candidate must have matching
Unicode-normalized artist and full title, duration within two seconds, an ISRC,
a preview, and readable status. Conflicting ISRCs are rejected as ambiguous.
This is **metadata matching**, not a verified Spotify-ID/ISRC join. Coverage
will be lower than the personal-inventory ISRC pipeline. Remixes, live versions,
and other version suffixes are intentionally preserved. Match evidence is saved
for auditing; no-match does not prove the track is absent from Deezer.

### v2 matching policy (`feat/mpd-match-fix`, not yet run)

A 250-track sample of v1 `no_strict_match` outcomes (2026-10-05) showed v1 rejects
format differences, not different recordings: 44% no search results, 32% title
mismatch, 13% artist, 9% duration. Spotify writes `X - Original Mix`; Deezer writes
`X (Original Mix)`, and Deezer's free-text search returns nothing for the dashed
form. `spotify/src/mpd.py` adds, alongside the unchanged v1 `choose_candidate`:

- `canonical()` — dash suffix → parenthetical, `feat.` credits and punctuation
  dropped; version markers (`Live`, `Remix`, `Remastered`) still distinguish.
- `choose_canonical()` — canonical artist/title, duration ≤ 3 s (Deezer reports
  whole seconds), conflicting ISRCs still ambiguous.
- `search_queries()` — adds an artist + core-title fallback query.
- `MATCH_POLICIES` — policy name → matcher, recorded with each match.

On the sample, v2 recovered 48/250 (19%) at ~1.25 requests/track, i.e. roughly
+230k tracks. It will run as a second pass over v1 `no_strict_match` IDs into a
separate output directory after the v1 run finishes.

The fresh candidate preview URL is passed directly to the downloader, avoiding
a second ISRC lookup that could select another catalog entry. The decoupled
producer retries each preview download 3 times (5/10/20 s backoff) and records
the failure reason (`http <code>`, `not mp3`, exception name) as the track's
`error`. The full run (finished 2026-10-09) left 42,537 `download_failed`
tracks that downloaded fine when retried slowly; a low-rate producer pass
retries them.

The downloader and CLAP embedder are reused from `previews.py` and
`embeddings.py`. The first run uses CLAP's deterministic multi-window 512-D
normalized audio features. MuQ/CLaMP 3 require separate validation and setup;
they are not implicitly run by this job.

## Running and resuming

`spotify/scripts/mpd_embed.sbatch` stages the environment from
`/data/user_data/ksnair/mlip/runtime.tar` to each allocated node. Exact installed
versions are saved in `runtime-requirements.txt` beside it. Model weights and
outputs use persistent storage; audio, runtime copies, and temporary caches
use `/scratch/ksnair/mlip`. No large assets are placed in home.

Submit from any directory:

```sh
sbatch --chdir=/home/ksnair/worktrees/mlip-mpd \
  --output=/data/user_data/ksnair/mlip/logs/%x-%j.out \
  --export=ALL,RUN_NAME=full,SHARD=0,NSHARDS=4 \
  /home/ksnair/worktrees/mlip-mpd/spotify/scripts/mpd_embed.sbatch
```

Use shards 0 through 3 with the same shard count. Each has its own output and
lock. All share a conservative API budget: each search and preview download is
paced at `0.25 * NSHARDS` seconds. Do not overlap independent campaigns without
adjusting their combined rate. A single shard owns its preview cache.

Outputs: `/data/user_data/ksnair/mlip/embeddings/mpd-<RUN_NAME>/clap/shard-i-of-N/`.
Each 128-input chunk has an NPZ (`ids`, `vectors`) and JSON containing input IDs,
matching evidence and outcome for **every** selected track. Chunks with transient
failures are retried on restart; completed chunks are skipped after checking IDs.
No-strict-match outcomes are retained; a new search policy needs a new run name.
Preview files are removed after checkpointing, bounding audio storage to a chunk.
Requeue can move a shard to any node because outputs are durable.

The pilot uses `pilot.sqlite` (51 tracks from MPD playlist 0), `RUN_NAME=pilot`,
and `NSHARDS=1`. It is an operational smoke test, not a coverage benchmark.
Never extend a partial final chunk with a different limit in the same run;
use a new run name. Model, shard count, chunk size, and catalog path must remain
fixed for resume. Input catalogs must be immutable once jobs start.

## Validation and pilot (2026-09-29)

- All 1,000 source slice MD5 hashes match the bundled manifest.
- Spotify test suite: **151 passed, 2 skipped** (GPU device unit tests skipped
  on the CPU test node). Shell syntax and diff whitespace checks pass.
- Live CLAP GPU pilot: job **10605875**, L40S on `babel-m5-32`, then resume
  job **10605972**. Both completed successfully. Resume preserved 21 vectors
  and recovered the one failed download using the candidate's direct preview.
- Final pilot: **22 embedded / 51 input tracks**, 29 without a strict match;
  no remaining download failures. The saved `(22, 512)` matrix has finite
  values, unit row norms, and IDs matching the provenance records.
- This is one playlist, not a representative dataset coverage estimate.

Monitor durable progress:

```sh
python3 /home/ksnair/worktrees/mlip-mpd/spotify/scripts/mpd_status.py \
  /data/user_data/ksnair/mlip/embeddings/mpd-full
squeue -u ksnair
```

Progress counts checkpointed tracks, not in-flight work. A completed SLURM job
can still have recorded coverage gaps or transient failures; inspect outcomes
and incomplete chunks before declaring a dataset complete.

## Full run submitted (2026-09-29)

The persistent catalog passed SQLite `quick_check` and contains exactly
1,000,000 playlists, 66,346,428 entries, and 2,262,292 unique tracks. Summed
track occurrence counts also equal 66,346,428. The catalog is 305 MiB.

Two full-dataset CLAP shards were submitted:

| Shard | SLURM job |
|---|---|
| 0/2 | 10605985 |
| 1/2 | 10605986 |

At handoff both were running: 10605985 on `babel-w5-16`, 10605986 on
`babel-w9-28`. This is an active run, not a completed feature dataset. Each job requests one GPU, 4 CPUs, 24 GiB RAM,
a 28-day time limit, and requeue support. Exact submission commands and the
catalog SHA-256 are saved in `/data/user_data/ksnair/mlip/full-run.json`.
Logs are `/data/user_data/ksnair/mlip/logs/mpd-clap-<job-id>.out`.
Full outputs are under `/data/user_data/ksnair/mlip/embeddings/mpd-full`.

## Migration to the decoupled pipeline (2026-10-05)

The September shard jobs `10605985` and `10605986` were stopped at checkpoints
on October 4. Their outputs were backed up to
`/data/user_data/ksnair/mlip/migration-v2/checkpoints-before.tar`; the accompanying
`audit-before.json` records 4,842 chunks and 281,210 embedded tracks.

`spotify/scripts/mpd_pipeline.py` now separates fetching from CLAP inference:

- One CPU producer searches with eight threads under one shared API budget
  (`--rate`, default 4 requests/sec, capped at 9 below Deezer's 10/sec per IP;
  set via `RATE=` in the sbatch export) and publishes audio TARs plus JSON ready markers to durable
  `/data/user_data/ksnair/mlip/queue-v2`. The queue is bounded to 32 bundles.
- One GPU consumer batches inference and updates the original two-shard,
  128-track checkpoint layout. Existing vectors and match provenance are kept;
  complete chunks are skipped. A changed catalog/chunk mapping raises an error.
- A CPU supervisor runs the producer and submits replacement GPU consumers
  when needed. File locks prevent concurrent producers or checkpoint writers.

GPU validation job `10660640` completed all four fetch-pilot bundles, recovering
four new embeddings. Three bundles became complete; one remained incomplete
and eligible for retry. Runtime tests passed in job `10660666`: **154 passed, 2 skipped**. The full
preservation audit is job `10660760`, using
`scripts/validation/audit_migration.py` (parallel checksum reads and a streaming
backup scan). It replaces the slower audit job `10660649`. Supervisor job
`10660689` has `afterok` dependencies on the runtime tests and replacement audit,
so it starts only when both succeed. Both checks passed. The audit verified all
4,842 NPZ files and preserved all 281,210 original embeddings exactly; three
files changed only by adding newly recovered vectors. The result is saved as
`migration-v2/audit-after.json`. Supervisor `10660689` is running on
`babel-u5-32`, initially staging its runtime before starting the producer and
submitting the GPU consumer.

Submit the continuous supervisor with:

```sh
sbatch --job-name=mpd-supervisor \
  --chdir=/home/ksnair/worktrees/mlip-mpd \
  --output=/data/user_data/ksnair/mlip/logs/%x-%j.out \
  --export=ALL,ROLE=supervise,MAX_CHUNKS=,RATE=8 \
  /home/ksnair/worktrees/mlip-mpd/spotify/scripts/mpd_pipeline.sbatch
```

On 2026-10-05 supervisor `10660689` (rate 4, ~33 s per 128-track chunk, i.e.
one search per track at the rate limit) was cancelled at ~38% of chunks and
replaced by `10670203` at `RATE=8`. The GPU consumer `10660844` kept running.

Monitor `queue-v2/supervisor-events.jsonl`, `queue-v2/consumer-job.json`,
`queue-v2/consumer-state.json`, and `embeddings/mpd-full/clap/pipeline-events.jsonl`.
The original September submission instructions above describe the superseded
combined worker; use the supervisor for the migrated run.

## Code review (2026-10-05)

Restart handling reconciles checkpoint evidence with saved vectors: a track
marked embedded without a saved vector is fetched again, and queued metadata
cannot silently complete such a track. Supervisor liveness uses SLURM state,
so a stale heartbeat cannot submit duplicate consumers while a job is live.
GPU submissions preserve custom catalog, output, and queue paths through
`PIPELINE_CATALOG`, `PIPELINE_OUTPUT`, and `PIPELINE_QUEUE`. Regression tests
cover all three cases. Already-running Python processes retain their loaded
code; these changes apply on their next start, without interrupting this run.
