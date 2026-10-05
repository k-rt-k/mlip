import json
import argparse
from pathlib import Path
import sys

# Import core helpers from playlists.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playlists import get_suggestions, make_client, save_json

def run_ytm_baseline(dataset_path: Path, auth_path: Path, output_path: Path, suggestions: int):
    """Reads dataset.json, queries YTM for suggestions for each seed playlist,

    and saves standardized predictions for evaluation.
    """
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    client = make_client(auth_path)
    
    predictions = {}
    
    # Handle either top-level list or dict with "examples"
    examples = dataset if isinstance(dataset, list) else dataset.get("examples", [])

    for example in examples:
        eid = str(example.get("example_id") or example.get("source_playlist_id"))
        pl_id = example.get("created_playlist_id")
        
        if not pl_id:
            print(f"Skipping {eid}: No 'created_playlist_id' found.")
            continue

        print(f"Fetching YTM suggestions for {eid} (Playlist ID: {pl_id})...")
        
        # Call get_suggestions directly from playlists.py
        result = get_suggestions(client, pl_id, count=suggestions)
        
        # Collect top 5 suggested video IDs
        suggested_ids = [t["video_id"] for t in result.get("suggested_tracks", [])]
        predictions[eid] = suggested_ids

    save_json(output_path, predictions)
    print(f"\nDone! Baseline predictions saved to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate YTM baseline predictions for dataset")
    parser.add_argument("--dataset", type=Path, default="data/youtube_music/partial_examples/v1/dataset.json")
    parser.add_argument("--auth", type=Path, default="data/youtube_music/browser.json")
    parser.add_argument("--output", type=Path, default="data/youtube_music/predictions/ytm_native.json")
    parser.add_argument("--suggestions", type=int, default=30)
    args = parser.parse_args()

    run_ytm_baseline(args.dataset, args.auth, args.output, args.suggestions)