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
