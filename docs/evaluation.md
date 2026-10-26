Existing partial-playlist evaluation uses
`data/youtube_music/partial_examples/v3/dataset.json` (40 inputs, 5/20 seeds).
Extract the v4 dataset ZIP first as described in the root README.

Score the committed predictions without credentials or fresh API calls:

```sh
uv run python evaluation/evaluate.py --predictions predictions/ytm_native.json
uv run python evaluation/evaluate.py --predictions predictions/cooccurrence.json
```

These commands report metrics at K = 1 and 5, plus R-precision, grouped by seed
count. Current result tables are `ytm_baseline_result2.txt` and
`cooccurrence_baseline_result2.txt`.

To collect fresh YouTube Music predictions, use browser credentials from
`mlip.team0@gmail.com` (see `youtube_music/scripts/setup_auth.py`):

```sh
uv run python youtube_music/scripts/run_ytm_baseline.py \
    --auth data/youtube_music/browser.json \
    --output data/youtube_music/predictions/ytm_native.json
```

The runner reads the dataset's real `created_playlist_id` values. Its local
output can be scored by passing that path to `evaluation/evaluate.py`.
Saved LLM outputs need conversion to `{example_id: [video_ids]}` before scoring;
handling short/empty outputs remains pending, as recorded in STATUS.md.

## Radio Pool

Radio Pool is a separate continuation baseline. Unlike native YouTube Music,
which requests suggestions for one private playlist containing all seeds, it
queries public song radio separately for each seed (`get_watch_playlist`,
`radio=True`, limit 50), then applies our aggregation rule. No login is needed.

The generator reuses the shared track filter (ID/title/artists required,
unavailable tracks excluded, known durations above 15 minutes excluded, unknown
durations retained). It merges cleaned radios with seed co-occurrence candidates
from the reference corpus, without the co-occurrence baseline's popularity
fallback. Seeds and duplicates are excluded. Candidates sort by the number of
distinct seed radios containing them, descending; ties use first encounter in
seed order and radio position, then video ID. The first 60 form the pool; the
first five are the Radio Pool recommendations. Co-occurrence-only candidates
have zero radio support and follow radio candidates. Hidden answers are used
only afterward for ceiling and evaluation.

All 40 inputs have 60 candidates. The collection caches 399 unique seed radios,
shared across paired five/twenty-seed inputs, with no errors. The supplemental
`datasets/radio-pool-v1.zip` contains normalized radio tracks, pools with settings,
and the full score artifact; its manifest records file, input and prediction
hashes. It requires the existing v4 dataset. Extract both as described in README.
The cache contains normalized tracks, not full raw platform responses.

Score the saved predictions without API calls:

```sh
uv run python evaluation/evaluate.py --predictions predictions/radio_pool.json
```

Reproduce the predictions from the saved pool order, also offline:

```sh
uv run python -m baselines.run_radio_pool \
    --output data/youtube_music/candidates/v1/radio_pool_rebuilt.json
```

For a new live collection, use a fresh output directory. These commands make
public platform requests and may return different radios than the saved run:

```sh
uv run python -m baselines.build_candidate_pools --examples 1,21 \
    --output data/youtube_music/candidates/pilot/pools.json
uv run python -m baselines.build_candidate_pools \
    --output data/youtube_music/candidates/fresh/pools.json
```

Collection checkpoints each seed radio in the output directory; rerunning an
interrupted collection reuses cached radios. Existing pool and prediction files
are protected from overwrite. Errors are recorded per seed. The runner prints
pool ceiling (fraction of examples containing any hidden song) and median pool
size per seed count. Saved ceilings are 0.85 / 1.00 for five/twenty seeds; these
are candidate-coverage bounds, not top-five recommendation hit rates.

### Comparison at five recommendations

Each row averages all 20 examples of that seed size, using the same hidden
answers and exact video-ID matching:

| Baseline | Seeds | Precision@5 | Recall@5 | Hit rate@5 | MAP@5 | NDCG@5 |
|---|---:|---:|---:|---:|---:|---:|
| YouTube Music native | 5 | 0.1300 | 0.0092 | 0.4000 | 0.0912 | 0.1472 |
| Co-occurrence | 5 | 0.0600 | 0.0043 | 0.1500 | 0.0520 | 0.0670 |
| Radio Pool | 5 | 0.2300 | 0.0195 | 0.4500 | 0.1655 | 0.2250 |
| YouTube Music native | 20 | 0.0800 | 0.0093 | 0.3000 | 0.0410 | 0.0796 |
| Co-occurrence | 20 | 0.0800 | 0.0070 | 0.2000 | 0.0625 | 0.0842 |
| Radio Pool | 20 | 0.2000 | 0.0275 | 0.6000 | 0.1182 | 0.1921 |

Full Radio Pool scores are in the extracted
`data/youtube_music/candidates/v1/radio_pool_evaluation.json`. Radio Pool
contains only five predictions, so its R-precision is not directly comparable
to the deeper native/co-occurrence lists. Both new and native methods depend on
YouTube Music's recommendation algorithms; this is not evidence of a trained
project model outperforming the platform. LLM Rerank remains a separate,
deferred experiment.
