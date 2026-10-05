Run the following files:

1. Get predictions for youtube music  
```bash
python youtube_music/scripts/suggest_songs.py \
    --playlist-id 1 \
    --auth youtube_music/browser.json \
    --output ./test.json
```