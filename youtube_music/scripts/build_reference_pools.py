"""Assemble reviewed reference IDs from cached public snapshots, never search during scoring.

uv run python youtube_music/scripts/build_reference_pools.py --selection data/youtube_music/references/selection.json --snapshots data/youtube_music/prompts-pilot-refined.json data/youtube_music/references/candidates-primary.json data/youtube_music/references/candidates-supplement.json --output-dir data/youtube_music/references/v1 --fetch-popularity

Selection JSON has prompts containing prompt_id, prompt, and selections with
playlist_id/review_note. Outputs include track membership, provenance, and a
human-readable HTML review. Popularity uses public Music header labels because
ytmusicapi 1.12.3 loses K/M suffixes. Counts from abbreviated labels are estimates.
No login or account writes; no final metric or development/test split implied.
Use --existing-pools to retain cached popularity when expanding a dataset. For
an entirely offline rebuild, supply the completed reference_pools.json as that
cache and omit --fetch-popularity. Optional excluded_video_ids in a selection
record remove manually reviewed entries while preserving the source snapshot.
"""

import argparse
import csv
from html import escape
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playlists import make_client, save_json, timestamp  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fetch-popularity", action="store_true")
    parser.add_argument("--existing-pools", type=Path, help="Reuse saved popularity labels for previously selected playlists")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Choose a new output directory; frozen references are not overwritten")
    selection = json.loads(args.selection.read_text())
    snapshots = {str(p): json.loads(p.read_text()) for p in args.snapshots}
    catalog = {}
    for path, snapshot in snapshots.items():
        for pid, item in snapshot["playlists"].items():
            catalog[pid] = (path, item)
    client = make_client() if args.fetch_popularity else None
    cached_popularity = {}
    if args.existing_pools:
        previous = json.loads(args.existing_pools.read_text())
        cached_popularity = {r["playlist_id"]: r["popularity"] for p in previous["prompts"] for r in p["playlists"]}
    result = {"schema_version": 1, "assembled_at": timestamp(), "status": selection["status"],
              "selection_file": str(args.selection), "snapshot_files": list(snapshots),
              "matching": "Exact video IDs; canonical recording matching remains pending",
              "popularity_note": "Displayed Music view labels; abbreviated counts approximate. Likes/saves unavailable. Not used in selection or weighting.",
              "prompts": []}
    rows, membership, html = [], [], []
    for prompt in selection["prompts"]:
        pool = {"prompt_id": prompt["prompt_id"], "prompt": prompt["prompt"], "playlists": [], "song_support": {}}
        html.append(f'<h2>{pool["prompt_id"]}. {escape(pool["prompt"])}</h2><ul>')
        for chosen in prompt["selections"]:
            pid = chosen["playlist_id"]
            path, item = catalog[pid]
            raw, tracks = item["raw"], item["tracks"]
            excluded = set(chosen.get("excluded_video_ids", []))
            if not excluded.issubset(t["video_id"] for t in tracks):
                raise ValueError(f"Excluded IDs missing from source snapshot: {pid}")
            tracks = [t for t in tracks if t["video_id"] not in excluded]
            assert tracks, f"Empty reference: {pid}"
            popularity = {"views_display": None, "views_approximate": None, "likes": None, "saves": None}
            if pid in cached_popularity:
                popularity = cached_popularity[pid]
            elif client:
                try:
                    response = client._send_request("browse", {"browseId": "VL" + pid})
                    labels = []
                    stack = [response]
                    while stack:
                        node = stack.pop()
                        if isinstance(node, dict):
                            if "secondSubtitle" in node:
                                labels.extend(r.get("text", "") for r in node["secondSubtitle"].get("runs", []))
                            stack.extend(node.values())
                        elif isinstance(node, list):
                            stack.extend(node)
                    view_labels = [label for label in labels if re.search(r"\bviews?\b", label, re.I)]
                    if view_labels:
                        popularity["views_display"] = view_labels[0]
                        match = re.fullmatch(r"([\d,.]+)\s*([KMB]?)\s+views?", view_labels[0], re.I)
                        if match:
                            popularity["views_approximate"] = round(float(match[1].replace(",", "")) * {"": 1, "K": 1000, "M": 1000000, "B": 1000000000}[match[2].upper()])
                    popularity["fetched_at"] = timestamp()
                except Exception as exc:
                    popularity["error_type"] = type(exc).__name__
            record = {**chosen, "title": raw.get("title"), "description": raw.get("description"),
                      "author": raw.get("author"), "url": "https://music.youtube.com/playlist?list=" + pid,
                      "source_snapshot": path, "collected_at": item["collected_at"],
                      "track_filter": snapshots[path]["track_filter"], "eligible_track_count": len(tracks),
                      "raw_returned_track_count": len(raw.get("tracks", [])), "popularity": popularity, "tracks": tracks}
            pool["playlists"].append(record)
            for track in tracks:
                support = pool["song_support"].setdefault(track["video_id"], {"track": track, "playlist_ids": []})
                support["playlist_ids"].append(pid)
                membership.append({"prompt_id": pool["prompt_id"], "playlist_id": pid, "video_id": track["video_id"], "title": track["title"], "artists": "; ".join(track["artists"])})
            rows.append({"prompt_id": pool["prompt_id"], "prompt": pool["prompt"], "playlist_id": pid, "title": record["title"], "author": (record["author"] or {}).get("name"), "eligible_tracks": len(tracks), **popularity, "url": record["url"], "review_note": chosen["review_note"]})
            label = popularity["views_display"] or "views unavailable"
            html.append(f'<li><a href="{escape(record["url"], quote=True)}">{escape(record["title"] or pid)}</a> — {len(tracks)} eligible tracks; {escape(label)}<br>{escape(chosen["review_note"])}<details><summary>Tracks</summary><ol>' + "".join(f'<li>{escape(t["title"])} — {escape(", ".join(t["artists"]))}</li>' for t in tracks) + '</ol></details></li>')
            print(f'{pool["prompt_id"]}: {record["title"]} — {len(tracks)} tracks; {label}', flush=True)
        pool["unique_video_ids"] = len(pool["song_support"])
        for support in pool["song_support"].values():
            support["playlist_count"] = len(support["playlist_ids"])
            support["playlist_fraction"] = len(support["playlist_ids"]) / len(pool["playlists"])
        html.append(f'</ul><p>{pool["unique_video_ids"]} unique video IDs in this pool.</p>')
        result["prompts"].append(pool)
    args.output_dir.mkdir(parents=True)
    save_json(args.output_dir / "reference_pools.json", result)
    for filename, records in [("playlists.csv", rows), ("track_membership.csv", membership)]:
        with (args.output_dir / filename).open("w", newline="") as handle:
            fields = list(dict.fromkeys(key for row in records for key in row))
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
    (args.output_dir / "review.html").write_text('<!doctype html><meta charset="utf-8"><title>Prompt reference pools</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;line-height:1.5}li{margin:10px 0}details{margin:10px}h2{margin-top:40px}</style><h1>Prompt reference pools</h1><p>' + escape(selection["status"]) + '</p><p>These are not exhaustive gold songs. Keep these playlists out of retrieval-based generation. Track identities are exact video IDs; version matching is pending. Views are displayed, rounded platform counts; likes/saves unavailable. Popularity is metadata only.</p>' + "".join(html))


if __name__ == "__main__":
    main()
