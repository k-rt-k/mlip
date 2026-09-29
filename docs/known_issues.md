# Known issues

No open issues remain from the seven-item self-review of commits
`9f85670`..`e5aa864`. All seven were fixed and regression-tested on 2026-09-29.
This records the reviewed scope, not a guarantee that the project has no bugs.

## Resolved

1. **Invalid preview downloads cached forever:** `spotify/src/previews.py`
   requires HTTP 200 and an ID3/MPEG header, rechecks existing cache headers,
   and publishes downloads by renaming `.mp3.part`. Failed requests are
   reported as unavailable; interrupted writes never publish a partial file.
2. **Undecodable clips stop shards:** `spotify/src/embeddings.py` supports a
   per-clip error callback for CLAP/MuQ decode failures and missing CLaMP 3
   outputs. `spotify/scripts/embed.py` logs `clip_failed` events, aligns only
   successful IDs with vectors, and checkpoints valid results. All-failed
   chunks are safe. Failed clips are retried on later runs; model-level errors
   still surface rather than being silently discarded.
3. **MuQ text embeddings crash on GPUs:** output moves to CPU before NumPy
   conversion. Tests execute a tiny Torch model on each available device and
   separately enforce CPU transfer even when accelerator tests are skipped.
4. **MuQ batch composition changes input audio:** equal-length clips are
   grouped for inference without truncation or padding. Tests compare mixed
   batches, different batch sizes, and individual embeddings in input order.
5. **Duplicate playlist names overwrite entries:** `pair_playlists` raises
   a descriptive error for duplicate normalized seed or recs names.
6. **Missing Git produces an obscure local-test failure:** the output guard
   raises an actionable error explaining why Git is required.
7. **SLURM logs depend on the submit directory:** use
   `spotify/scripts/submit_babel_embed.sh`. It creates the log directory before
   submission and passes absolute log and working-directory paths to `sbatch`.
   The Babel guide and job comments now use this wrapper.

## Validation

- Full suite: **230 passed, 2 skipped** (`spotify/tests` and `peer/tests`).
- CUDA and MPS tests skipped because those devices are unavailable to the test
  process. CPU inference with a tiny model and the CPU-transfer regression pass.
- Worker tests verify manifest failures, ID/vector alignment, all-failed chunks,
  and resume. Submission tests use a fake `sbatch` from another directory,
  including a checkout path containing spaces.
- Shell syntax and `git diff --check` pass.
- Production model weights and a live Babel/SLURM run were not exercised.
