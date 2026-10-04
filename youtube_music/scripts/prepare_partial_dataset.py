"""Prepare a manifest of partial examples; optionally create private seed-only copies.

uv run python youtube_music/scripts/prepare_partial_dataset.py --manifest data/youtube_music/partial_examples/selection.json --output-dir data/youtube_music/partial_examples/v1 --create --auth data/youtube_music/browser.json

Manifest examples specify example_id, playlist_id, snapshot, and optionally
existing_example (reuse an earlier copy). Existing per-example checkpoints are
verified, never recreated. model_inputs.json contains only seeds and copy IDs;
examples and dataset.json contain evaluator-only hidden answers/source metadata.
Five random seeds and random state 42 default to the existing pilot convention.
"""

import argparse
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playlists import create_seed_playlist, make_client, prepare_partial, save_json, timestamp, verify_seed_playlist  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--auth", type=Path)
    args = parser.parse_args()
    if args.create and not args.auth:
        parser.error("--create requires --auth")
    manifest = json.loads(args.manifest.read_text())
    ids = [row["example_id"] for row in manifest["examples"]]
    if len(set(ids)) != len(ids) or any(not isinstance(i, int) or i < 1 for i in ids):
        parser.error("example_id must be unique positive integers")
    client = make_client(args.auth) if args.create else None
    examples = []
    for row in manifest["examples"]:
        path = args.output_dir / f'example-{row["example_id"]:02d}.json'
        source = json.loads(Path(row["snapshot"]).read_text())["playlists"][row["playlist_id"]]["raw"]
        prepared = prepare_partial({**source, "id": row["playlist_id"]}, args.seed_count, args.random_seed)
        if path.exists() or row.get("existing_example"):
            existing = path if path.exists() else Path(row["existing_example"])
            example = json.loads(existing.read_text())
            if any(example[key] != prepared[key] for key in ["source_playlist_id", "selection", "seed_tracks", "held_out_tracks", "track_filter"]):
                raise ValueError(f"Saved example {row['example_id']} has different source or split settings")
        else:
            example = {**prepared, "prepared_at": timestamp(), "source_snapshot": row["snapshot"]}
        example["example_id"] = row["example_id"]
        save_json(path, example)
        if client:
            try:
                if example.get("created_playlist_id"):
                    verify_seed_playlist(client, example)
                else:
                    create_seed_playlist(client, example, f'MLIP baseline sample {row["example_id"]:02d}')
            finally:
                # Preserve returned IDs even when verification fails; never retry writes.
                save_json(path, example)
        examples.append(example)
        print(f'Example {row["example_id"]}: {len(example["seed_tracks"])} seeds, {len(example["held_out_tracks"])} hidden; copy verified={example.get("creation_verified", False)}', flush=True)
    save_json(args.output_dir / "dataset.json", {"schema_version": 1, "prepared_at": timestamp(), "manifest": str(args.manifest), "examples": examples})
    save_json(args.output_dir / "model_inputs.json", {"schema_version": 1, "mode": "partial_only", "examples": [{"example_id": e["example_id"], "seed_tracks": e["seed_tracks"], "seed_playlist_id": e.get("created_playlist_id")} for e in examples]})
    rows = []
    for e in examples:
        link = f'https://music.youtube.com/playlist?list={e["created_playlist_id"]}' if e.get("created_playlist_id") else ""
        rows.append(f'<tr><td>{e["example_id"]}</td><td>{escape(e["source_title"] or "")}</td><td>{len(e["seed_tracks"])}</td><td>{len(e["held_out_tracks"])}</td><td><a href="{escape(link, quote=True)}">Private seed copy</a></td></tr>')
    (args.output_dir / "review.html").write_text('<!doctype html><meta charset="utf-8"><title>Partial playlists v1</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto}td,th{padding:12px;text-align:left}table{border-collapse:collapse}tr{border-bottom:1px solid #ccc}</style><h1>Partial playlist dataset v1</h1><p>Five random seeds per source; all other eligible songs hidden. Original titles shown here are evaluator metadata: never send them to the partial-only model. Private copies have neutral titles and empty descriptions.</p><table><tr><th>Example</th><th>Original playlist</th><th>Seeds</th><th>Hidden</th><th>Copy</th></tr>' + ''.join(rows) + '</table>')


if __name__ == "__main__":
    main()
