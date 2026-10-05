"""Build paired 5/20-song inputs from the existing twenty five-song examples.

Run from the repository root (extract the shared dataset first):

    uv run python youtube_music/scripts/prepare_nested_partials.py --create --auth data/youtube_music/browser.json

Without --create, prepare local files only. Browser credentials must come from
mlip.team0@gmail.com; setup_auth.py documents copying and testing fresh headers.
All existing private copies must be owned by that session before any writes.
Existing five-song copies and the v2 dataset are preserved. Twenty new private
copies have neutral titles, empty descriptions, and exactly twenty seed songs.
Returned IDs are checkpointed, including after a failed verification; creation
is never retried automatically. Resolve any failure before resuming.
Requests are paced (0.5 seconds by default). HTTP errors, malformed responses,
and failures are recorded without headers/bodies in errors.jsonl. A 429 stops
the run; respect its recorded Retry-After or wait before resuming with saved IDs.
Missing contents on HTTP 200 is recorded as an uncertain response-shape issue,
not treated as proof of rate limiting. errors.jsonl is local diagnostic data.

For each source, keep its five original seeds and sample fifteen more from its
hidden songs using random seed 42. The twenty-song input contains the five-song
input. All other eligible source songs are hidden for each size: those fifteen
extra seeds remain hidden in the five-song case. Hidden counts vary; no songs
are discarded, no fixed hidden-set size is imposed, and no scoring is performed.

Outputs: data/youtube_music/partial_examples/v3/{dataset.json,model_inputs.json,
example-NN-seeds-SS.json,review.html}. dataset.json has forty records: example_id
1–20 are five-song inputs; 21–40 are twenty-song inputs. source_example_id pairs
the same source across sizes; seed_count identifies the size. model_inputs.json
contains only these IDs, seed counts, seed tracks, and private seed_playlist_id;
source titles and hidden answers are evaluator-only. v2 remains usable unchanged.
"""

import argparse
from html import escape
import json
from pathlib import Path
import random
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playlists import create_seed_playlist, make_client, save_json, timestamp, verify_seed_playlist  # noqa: E402

ERROR_PATH = None


def record_error(event, **fields):
    if ERROR_PATH is not None:
        ERROR_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_PATH.open("a") as stream:
            stream.write(json.dumps({"at": timestamp(), "event": event, **fields}) + "\n")


def observe_response(response, delay):
    """Log response shape/status only; never retain cookies, headers, or bodies."""
    endpoint = urlsplit(response.request.url).path.rsplit("/", 1)[-1]
    if response.status_code >= 400:
        retry_after = response.headers.get("Retry-After", "")
        record_error("http_error", endpoint=endpoint, status=response.status_code,
                     retry_after_seconds=int(retry_after) if retry_after.isdigit() else None)
    elif endpoint == "browse":
        try:
            request = json.loads(response.request.body or "{}")
            body = response.json()
            if str(request.get("browseId", "")).startswith("VL") and "contents" not in body:
                record_error("missing_playlist_contents", status=response.status_code,
                             possible_rate_limit="unconfirmed")
        except (ValueError, TypeError):
            record_error("malformed_response", endpoint=endpoint, status=response.status_code)
    time.sleep(delay)


def check_copy(client, example):
    for attempt in range(4):
        try:
            raw = client.get_playlist(example["created_playlist_id"], limit=None)
            break
        except KeyError as exc:
            if "contents" not in str(exc) or attempt == 3:
                raise RuntimeError("❌ Saved copy could not be read; check access before resuming.") from None
            time.sleep(2 ** attempt)
    if raw.get("owned") is not True or raw.get("privacy") != "PRIVATE":
        raise RuntimeError("❌ Copy must be private and owned by the authenticated team account.")
    verify_seed_playlist(client, example)


def main():
    global ERROR_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=Path("data/youtube_music/partial_examples/v2/dataset.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/youtube_music/partial_examples/v3"))
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--auth", type=Path)
    parser.add_argument("--request-delay", type=float, default=0.5, help="Pause after each API response")
    args = parser.parse_args()
    if args.create and not args.auth:
        parser.error("--create requires --auth")
    if args.request_delay < 0:
        parser.error("--request-delay must be nonnegative")
    ERROR_PATH = args.output_dir / "errors.jsonl"
    base = json.loads(args.base.read_text())["examples"]
    if len(base) != 20 or [e["example_id"] for e in base] != list(range(1, 21)):
        raise ValueError("Expected the twenty original examples, ordered 1–20.")
    variants = []
    for count in (5, 20):
        for old in base:
            if len(old["seed_tracks"]) != 5 or not old.get("created_playlist_id"):
                raise ValueError("Every base example needs five seeds and an existing private copy ID.")
            if len(old["held_out_tracks"]) < 16:
                raise ValueError("Source needs fifteen extra seeds and at least one hidden song.")
            e = {**old, "schema_version": 2, "source_example_id": old["example_id"], "seed_count": count}
            if count == 20:
                chosen = set(random.Random(42).sample(range(len(old["held_out_tracks"])), 15))
                e["seed_tracks"] = old["seed_tracks"] + [t for i, t in enumerate(old["held_out_tracks"]) if i in chosen]
                e["held_out_tracks"] = [t for i, t in enumerate(old["held_out_tracks"]) if i not in chosen]
                e["example_id"] += 20
                e["selection"] = {"method": "extend_existing_seeds", "seed_count": 20, "base_seed_count": 5, "random_seed": 42}
                e.pop("created_playlist_id")
                e["creation_verified"] = False
            path = args.output_dir / f'example-{old["example_id"]:02d}-seeds-{count:02d}.json'
            if path.exists():
                saved = json.loads(path.read_text())
                keys = ["example_id", "source_example_id", "seed_count", "source_playlist_id", "seed_tracks", "held_out_tracks", "selection", "track_filter"]
                if any(saved[k] != e[k] for k in keys):
                    raise ValueError(f"Saved split differs from the requested setup: {path}")
                if count == 5 and saved.get("created_playlist_id") != old["created_playlist_id"]:
                    raise ValueError("Five-song copy ID must match the original dataset.")
                e = saved
            variants.append((path, e))

    client = make_client(args.auth) if args.create else None
    if client:
        client._session.hooks["response"].append(lambda response, **_: observe_response(response, args.request_delay))
        print(f"✅ Connected as {client.get_account_info()['accountName']}; checking existing copies.", flush=True)
        for _, e in variants:
            if e.get("created_playlist_id"):
                check_copy(client, e)
        print("✅ Existing copies verified; creating only missing twenty-song copies.", flush=True)
    for path, e in variants:
        try:
            if client and not e.get("created_playlist_id"):
                create_seed_playlist(client, e, f'MLIP baseline sample {e["source_example_id"]:02d} seeds 20')
            if client:
                check_copy(client, e)
        except Exception as exc:
            record_error("copy_operation_failed", source_example_id=e["source_example_id"],
                         seed_count=e["seed_count"], exception_type=type(exc).__name__,
                         copy_id_saved=bool(e.get("created_playlist_id")))
            raise
        finally:
            save_json(path, e)
        print(f'Example {e["source_example_id"]}, {e["seed_count"]} seeds, {len(e["held_out_tracks"])} hidden; verified={e.get("creation_verified", False)}', flush=True)

    examples = [e for _, e in variants]
    save_json(args.output_dir / "dataset.json", {"schema_version": 2, "prepared_at": timestamp(), "base_dataset": str(args.base), "seed_sizes": [5, 20], "hidden_policy": "all_remaining_source_songs_per_size", "examples": examples})
    inputs = [{k: e[k] for k in ["example_id", "source_example_id", "seed_count", "seed_tracks"]} | {"seed_playlist_id": e.get("created_playlist_id")} for e in examples]
    save_json(args.output_dir / "model_inputs.json", {"schema_version": 2, "mode": "partial_only", "examples": inputs})
    rows = []
    for e in examples:
        link = f'https://music.youtube.com/playlist?list={e["created_playlist_id"]}' if e.get("created_playlist_id") else ""
        cell = f'<a href="{escape(link, quote=True)}">Private copy</a>' if link else "Not created"
        rows.append(f'<tr><td>{e["source_example_id"]}</td><td>{e["seed_count"]}</td><td>{len(e["held_out_tracks"])}</td><td>{escape(e["source_title"] or "")}</td><td>{cell}</td></tr>')
    (args.output_dir / "review.html").write_text('<!doctype html><meta charset="utf-8"><title>Paired partial playlists</title><style>body{font:16px system-ui;margin:40px}td,th{padding:10px;text-align:left}</style><h1>Twenty sources, two input sizes: 5 and 20 songs</h1><p>The twenty-song input includes the five-song input. Every remaining source song is hidden for each size; hidden counts vary. Source titles and hidden songs are evaluator-only.</p><table><tr><th>Source example</th><th>Seeds</th><th>Hidden</th><th>Source title</th><th>Copy</th></tr>' + ''.join(rows) + '</table>')


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        record_error("run_stopped", exception_type=type(exc).__name__)
        print(f"❌ Stopped ({type(exc).__name__}); inspect {ERROR_PATH}. "
              "If rate-limited, wait before resuming. Saved IDs are preserved; "
              "no automatic creation retry.", file=sys.stderr)
        raise SystemExit(1)
