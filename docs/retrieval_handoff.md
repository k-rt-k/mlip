# Text-to-music retrieval: compute-node handoff

Branch: `feat/text-music-retrieval`. Development worktree:
`/Users/harshpoonia/cmu/mlip/project/tmp/text-music-retrieval`.
Continue from the implementation on this branch; the next step is real-data
validation and measurement, rather than another index implementation.

## Completed boundary

`retrieval/` provides a small CPU FAISS wrapper over precomputed embeddings:

| Method | Implementation | Construction settings | Query setting |
| --- | --- | --- | --- |
| Exact | `IndexFlatIP` | none | none |
| IVF | `IndexIVFFlat` | `nlist`, training sample size, seed | `nprobe` |
| HNSW | `IndexHNSWFlat` | `m`, `ef_construction` | `ef_search` |

All three explicitly use inner product on L2-normalized float32 rows, equivalent
to cosine similarity within floating-point tolerance. Already-unit rows are
preserved within 1e-6 to make fingerprints stable across loading and saving.
No product ranking, playlist learning, or score fusion has been implemented.

- `retrieval/catalog.py`: single NPZ or recursively sorted NPZ chunks; preserves
  each file's row order; validates dimensions, finite/nonzero vectors and unique
  string IDs. A SHA-256 fingerprint binds normalized vectors to ordered IDs.
- `retrieval/index.py`: `IndexConfig`, `RetrievalIndex.build(catalog, config)`,
  `search(query_embeddings, k)`, `save(path)`, `load(path)`, and
  `set_search_parameters(...)`. Results have `scores`, integer `rows` and
  `song_ids`. Input queries are copied, not modified. Missing IVF neighbors are
  `-1` / `None` / `-inf`; the CLI emits JSON null for missing scores.
- Saved directories contain `index.faiss`, `catalog.json`, `metadata.json`.
  Metadata records settings, corpus fingerprint, training size/seed, clustering
  defaults, build time and thread count. Checksums detect accidentally mixed or
  corrupted index/mapping files. Saving refuses to overwrite existing directories.
- `retrieval/benchmark.py`: exact reference automatically included; ANN recall@k,
  warm single-query latency (mean/p50/p95), construction time, index file bytes,
  corpus array bytes and worker peak RSS. Each construction configuration runs
  in a fresh process; query-setting sweeps share that build. It checks identical
  corpus/query fingerprints against the exact reference.
- `python -m retrieval --help`: build/search/benchmark commands and examples.
  The benchmark writes a report, not persistent indexes; build selected artifacts
  separately with the build command. Python callers of `compare` need a normal
  script with an `if __name__ == '__main__':` guard for spawned workers.

FAISS clustering iteration count, spherical setting and point limits use the
pinned library defaults and are recorded in `build_info`. The wrapper explicitly
selects IVF training rows uniformly without replacement using `seed`, and raises
FAISS's internal sample cap when necessary to avoid a second silent subsample.
An omitted training size means all corpus rows; oversized requests are capped at
corpus size and the actual size is recorded. HNSW uses FAISS's graph/RNG defaults;
`seed` controls IVF training only. Do not claim bitwise reproducible multithreaded
HNSW construction.

## Environment and known runtime limitation

From the repository root on a compute node with the data mounted:

```sh
git fetch origin
git switch feat/text-music-retrieval
uv python install 3.12
uv sync --frozen --group dev
uv run python -m pytest retrieval/tests -q
```

`faiss-cpu==1.13.2` is pinned in `pyproject.toml`/`uv.lock`, with NumPy explicit.
It installed and ran on the Apple Silicon laptop under Python 3.12.15. Available
wheels cover macOS ARM64 >=14 and Linux x86_64 glibc >=2.27. Babel's inspected
login environment was x86_64/glibc 2.34, but its system Python was 3.9: **use the
uv-managed 3.12 interpreter**. A Linux compute-node installation/run remains to
be verified. `/data` was not mounted on the inspected login node; this does not
establish whether a file exists on a compute node.

Keep text encoding in its own process/environment using Kartik's existing ML
runtime, then write query vectors to NPZ for the retrieval commands. Retrieval
itself needs neither PyTorch nor Transformers nor model downloads. The optional
PyTorch wheel and FAISS wheel loaded together caused an OpenMP abort locally;
co-resident model encoding and indexing is not a validated setup. Separate
processes avoid that observed conflict without disabling runtime checks.

For all local tests, run these as **separate processes**:

```sh
uv run python -m pytest --ignore=spotify/tests/test_embeddings.py -q
uv run --with torch python -m pytest spotify/tests/test_embeddings.py -q
```

## Expected data contract: verify before a full build

These paths/counts come from Kartik's checked-in handoff and pipeline source;
the local implementation has not read the real files:

- `/data/user_data/ksnair/mlip/embeddings/mpd-full/clap/`: recursively find
  `shard-*/chunk-*.npz`; **1,025,994 x 512**, keyed by Spotify track ID.
  Matching JSON files contain per-track preview/match provenance.
- `/data/user_data/ksnair/mlip/embeddings/ytm-eval/clap.npz`:
  **2,391 x 512**, keyed by YouTube video ID; adjacent `deezer_map.json` records
  Deezer ID, ISRC and metadata evidence.
- Encoder: `laion/larger_clap_music_and_speech`; 30-second previews split into
  10-second windows, window embeddings averaged and L2-normalized. The existing
  `spotify.src.embeddings.get_embedder('clap').embed_text(texts)` is the text
  encoder. Confirm checkpoint revision and actual dimension with Kartik.
- MPD archive: `/data/user_data/ksnair/mlip/data/mpd/archive.zip`; playlist
  association learning is subsequent work, not an indexing dependency.

Each NPZ must have `ids`: one-dimensional Unicode/bytes strings and `vectors`:
a numeric `(n, d)` array. Query NPZs use the same schema, with stable query IDs.
Do not point a corpus-directory loader at unrelated NPZs or put query NPZs inside
that directory. It loads every `.npz` underneath. Duplicate song IDs fail clearly;
audit/resume-clean the source artifacts rather than silently keeping a last row.
Repeated recordings with distinct IDs remain separate candidates.

First audit counts, dimensions, norms, duplicate IDs, available RAM, and whether
all shards are complete. Freeze a source manifest/checksums before benchmarking:
all workers must read the same immutable snapshot. Use `--limit 10000` on a build
for an initial smoke test. A prefix is only a plumbing check; use a reproducible
random subset if measuring a smaller representative corpus.

The full MPD float32 matrix alone is about 2.10 GB (1.96 GiB). Loading can briefly
hold about two corpus arrays plus a chunk; FAISS stores its own vector copy,
with IVF training samples or the HNSW graph adding more. Allow headroom for IDs,
Python, temporary arrays and OS memory. Benchmark groups run sequentially.
`TMPDIR` controls temporary index/reference files, so choose node scratch with a
few GB free. Nothing requires bringing the full corpus or audio to the laptop.

## Query preparation and first real-data run

Freeze the query input IDs/text, encoder checkpoint/revision, code revision,
encoding environment and normalized vectors in a local manifest. The existing
`prompts.txt` contains team-approved synthetic prompts and can supply a first
20-query end-to-end check; that small set is not enough to claim broad latency
or quality performance. Avoid hidden playlist answers as query context.

In Kartik's encoder environment, from the repo root, a separate Python process
can prepare the NPZ using the existing function (no new encoder needed):

```python
from pathlib import Path
import numpy as np
from spotify.src.embeddings import get_embedder

texts = [line.strip() for line in Path('prompts.txt').read_text().splitlines()
         if line.strip()]
vectors = get_embedder('clap').embed_text(texts)
out = Path('data/retrieval/text-queries.npz')
out.parent.mkdir(parents=True, exist_ok=True)
np.savez(out, ids=[f'prompt-{i+1}' for i in range(len(texts))], vectors=vectors)
```

Exit that process, then use the CPU retrieval environment. Start with eval-song
vectors to check end-to-end IDs and shapes, then repeat on the full MPD corpus.
For example, save the following as gitignored `data/retrieval/configs.json`:

```json
[
  {"method": "ivf", "nlist": 1024, "nprobe": 8, "training_sample_size": 200000, "seed": 0},
  {"method": "ivf", "nlist": 1024, "nprobe": 32, "training_sample_size": 200000, "seed": 0},
  {"method": "ivf", "nlist": 1024, "nprobe": 128, "training_sample_size": 200000, "seed": 0},
  {"method": "hnsw", "m": 32, "ef_construction": 200, "ef_search": 64},
  {"method": "hnsw", "m": 32, "ef_construction": 200, "ef_search": 128}
]
```

These are illustrative starting configurations, **not a finalized tuning grid**.
Use smaller `nlist`/training sizes for a tiny smoke corpus.

```sh
uv run python -m retrieval benchmark \
  --corpus /data/user_data/ksnair/mlip/embeddings/mpd-full/clap \
  --queries data/retrieval/text-queries.npz \
  --configs data/retrieval/configs.json --threads 1 --k 5 \
  --warmups 1 --repeats 5 --output data/retrieval/mpd-benchmark-k5.json
```

Repeat at larger k (e.g. 100) if later candidate filtering/reranking needs it.
Use the same corpus/queries/thread count/hardware for every method. Record node
CPU/RAM/allocation and avoid shared-node interference. Run more representative
queries and independent repeated benchmarks before choosing a method. Increasing
`nprobe` or `ef_search` needs no rebuild; `nlist`, training settings, `m` and
`ef_construction` do. Potential later comparisons include IVF nlist 1024/4096
and HNSW m 16/32, after construction cost and resource limits are known. Agree an
ANN recall/latency/memory target and tuning/held-out queries before selecting a
winner; keep every trial, including failures and unfinished runs.

Latency here measures wrapper calls including normalization/ID mapping, excluding
encoding, loading and IO. Peak RSS includes loader/training/corpus/index and is a
process high-water mark: sweeps share that history. Index file bytes are a
separate size measurement, not isolated resident FAISS memory. Reports include
strict row-ID ANN recall, so duplicate/equal-score boundary ties can reduce recall
even with equivalent scores. Inspect such cases before interpreting a deficit.

Persist any desired configuration with `python -m retrieval build` (see its
module docstring), then use `search --index ... --queries ... --output ...`.
The search CLI permits query-setting overrides and records both fingerprints.
Never concurrently mutate query settings while serving searches.

## Remaining algorithm/evaluation work

1. Run the real-artifact audit and CPU benchmark; report completed/failed trials,
   defaults, accuracy/speed/memory and limitations. No real-data winner is chosen.
2. Resolve MPD Spotify candidates to recording identities and YouTube video IDs
   using match provenance, not string equality across namespaces. Compute catalog
   overlap/coverage and audit ambiguous versions. Direct evaluation against our
   YouTube dataset works only after this join; the tiny eval-song catalog alone
   is a coverage-conditioned diagnostic, not a fair full-catalog comparison.
3. Keep ANN recall against exact neighbors separate from downstream playlist
   metrics (including NDCG@5). The former validates approximation; it cannot prove
   better recommendations. Preserve the baseline evaluation suite/splits, or
   explicitly justify changes and re-run baselines under the same conditions.
4. Discuss seed-song associations from MPD, seed exclusion/recording deduplication,
   text/seed score combination and model selection with Harsh. Those methods and
   their validation split remain to be finalized; do not infer them from an ANN
   benchmark or tune against hidden evaluation answers.

Local validation on 2026-10-27: 21 retrieval tests; 242 existing tests passed with
one pre-existing conditional skip when run separately with the optional PyTorch
runtime. A separate CLI smoke run used 5,000 synthetic 512-D vectors, 40 synthetic
queries, exact + 3 IVF settings + 2 HNSW settings at k=5. All six completed; IVF
with nprobe=nlist recovered exact neighbors (ANN recall 1.0). Synthetic artifacts
are gitignored under `data/retrieval/synthetic-smoke/`. These are correctness and
plumbing checks, not evidence of real-corpus performance or recommendation quality.
