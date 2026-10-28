"""Run the zero-shot LLM baseline and resolve its suggestions to YouTube Music tracks.

uv run python llm/scripts/run_llm_baseline.py --mode prompt_only --run-id gemma4-31b-v1
uv run python llm/scripts/run_llm_baseline.py --mode seeds_only --run-id gemma4-31b-v1

Local endpoint (Claude router with model loading):
uv run python llm/scripts/run_llm_baseline.py --backend local --model local-deepseek --mode seeds_only --run-id local-deepseek-v1

Add --limit N to run only N examples (this makes live calls, not a dry run).
OpenRouter is the default and needs OPENROUTER_API_KEY in llm/.env.
Local requires --model, uses LOCAL_LLM_BASE_URL (default http://127.0.0.1:18088/v1),
and optionally LOCAL_LLM_API_KEY. On the Claude router use local-deepseek,
local-qwen, local-gemma, or local-gemma-bf16. Other OpenAI-compatible base URLs
can be configured explicitly with their served model name. See llm/.env.example.
--provider pins an OpenRouter host and is not available with --backend local.
Use a separate --run-id per backend/endpoint/model/provider; mismatched directories are rejected.
prompt_only reads only prompt text from reference_pools.json; seeds_only reads only
model_inputs.json, never hidden answers. The model is asked for --count songs
(2K by default); every resolved, de-duplicated suggestion gets a rank and the
first --keep form the top-K list. Outputs (gitignored): data/llm/runs/<run-id>/<mode>.json,
raw responses in raw/ cached by request hash (identical requests reuse saved responses), and a
shared search cache in data/llm/resolve_cache.json. Scoring is left to evaluation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "llm" / "src"))
sys.path.insert(0, str(ROOT / "youtube_music" / "src"))
import openrouter  # noqa: E402
import local_llm  # noqa: E402
from parse import parse_songs, track_keys  # noqa: E402
from playlists import make_client, save_json, timestamp  # noqa: E402
from prompts import PROMPT_VERSION, SYSTEM, prompt_only, seeds_only, song_schema  # noqa: E402
from resolve import matches, resolve_song  # noqa: E402

DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
INPUTS = {"prompt_only": "data/youtube_music/references/v2/reference_pools.json",
          "seeds_only": "data/youtube_music/partial_examples/v2/model_inputs.json"}
BUDGET = {"prompt_only": (20, 10), "seeds_only": (10, 5)}  # (requested, top-K kept)


def load_examples(mode, path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if mode == "prompt_only":
        return [{"id": p["prompt_id"], "request": p["prompt"]} for p in data["prompts"]]
    return [{"id": e["example_id"], "seed_tracks": e["seed_tracks"],
             "seed_playlist_id": e.get("seed_playlist_id")} for e in data["examples"]]


def build_messages(mode, example, n):
    return prompt_only(example["request"], n) if mode == "prompt_only" else seeds_only(example["seed_tracks"], n)


def cached_complete(path, request, call):
    """Reuse a saved response for an identical request; otherwise call and save it."""
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("request_hash") == digest:
            return saved["response"], True
    response = call()
    save_json(path, {"request_hash": digest, "saved_at": timestamp(), "request": request, "response": response})
    return response, False


def validate_run_directory(run_dir, backend, endpoint, model, provider=None):
    """Reject mixing backends/models/pinned hosts, including legacy outputs and partial raw runs."""
    expected = (backend, endpoint, model, provider)
    paths = [run_dir / f"{mode}.json" for mode in INPUTS]
    paths.extend((run_dir / "raw").glob("*.json"))
    for path in paths:
        if not path.is_file():
            continue
        saved = json.loads(path.read_text(encoding="utf-8"))
        run, request = saved.get("run"), saved.get("request")
        record = run or request
        if not record:
            raise ValueError("Saved run identity is missing; choose a different --run-id")
        pinned = run.get("provider_pinned") if run else request.get("provider")
        identity = (record.get("backend", "openrouter"), record.get("endpoint", openrouter.URL),
                    record.get("model_requested", record.get("model")), pinned)
        if identity != expected:
            raise ValueError("Run directory contains a different backend, endpoint, model or provider; "
                             "choose a different --run-id")


def rank_suggestions(songs, seed_tracks, keep, resolve):
    """Resolve in model order; rank unique, non-seed tracks; first `keep` ranks are the top K.

    Seed repeats use the resolver's fuzzy title + artist match, since a repeated
    seed can resolve to a different upload than the seed's own video ID.
    """
    seed_ids = {t["video_id"] for t in seed_tracks}
    rows, used, rank = [], set(seed_ids), 0
    for llm_rank, song in enumerate(songs, 1):
        track = resolve(song["title"], song["artist"])
        row = {"llm_rank": llm_rank, **song, "resolved": track is not None, "rank": None,
               "in_top_k": False, "drop_reason": None, "track": track}
        if any(matches(seed, song["title"], song["artist"]) for seed in seed_tracks) or (
                track and track["video_id"] in seed_ids):
            row["drop_reason"] = "seed_repeat"
        elif track is None:
            row["drop_reason"] = "unresolved"
        elif track["video_id"] in used:
            row["drop_reason"] = "duplicate_video"
        else:
            used.add(track["video_id"])
            rank += 1
            row.update(rank=rank, in_top_k=rank <= keep)
        rows.append(row)
    return rows


def summarize(examples, keep, backend="openrouter"):
    done = [e for e in examples if e["status"] == "ok"]
    suggested = sum(len(e["recommendations"]) for e in done)
    resolved = sum(r["resolved"] for e in done for r in e["recommendations"])
    calls = [e["call"] for e in examples if e.get("call")]
    return {"examples": len(examples), "ok": len(done),
            "failed": {s: sum(e["status"] == s for e in examples) for s in ("call_failed", "parse_failed")},
            "suggestions_parsed": suggested, "resolution_rate": round(resolved / suggested, 3) if suggested else None,
            "examples_short_of_k": sum(sum(r["in_top_k"] for r in e["recommendations"]) < keep for e in done),
            "total_tokens": sum((c.get("usage") or {}).get("total_tokens", 0) for c in calls),
            "mean_latency_s": round(sum(c["latency_s"] for c in calls) / len(calls), 2) if calls else None,
            "cost_usd": (round(sum((c.get("usage") or {}).get("cost") or 0 for c in calls), 4)
                         if backend == "openrouter" else None)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", required=True, choices=sorted(INPUTS))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=("openrouter", "local"), default="openrouter",
                        help="chat endpoint (default openrouter)")
    parser.add_argument("--model", help="OpenRouter model ID (default %s) or local model name" % DEFAULT_MODEL)
    parser.add_argument("--count", type=int, help="songs requested (default 2K)")
    parser.add_argument("--keep", type=int, help="top-K budget (default 10 prompt_only, 5 seeds_only)")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, help="first N examples only (makes live calls)")
    parser.add_argument("--ids", help="example ids to run, e.g. 21-40 or 1,3,5")
    parser.add_argument("--provider", help="pin one OpenRouter host with no fallback, e.g. ModelRun")
    parser.add_argument("--min-interval", type=float, help="seconds between live calls (default 4 OpenRouter, 0 local)")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out-root", type=Path, default=ROOT / "data" / "llm")
    args = parser.parse_args()

    if args.backend == "local" and not args.model:
        parser.error("--model is required for --backend local")
    if args.backend == "local" and args.provider:
        parser.error("--provider applies only to --backend openrouter")
    args.model = args.model or DEFAULT_MODEL
    adapter = openrouter if args.backend == "openrouter" else local_llm
    endpoint = openrouter.URL if args.backend == "openrouter" else local_llm.endpoint()
    if args.backend == "local":
        local_llm.validate_model(args.model, endpoint)
    interval = args.min_interval if args.min_interval is not None else (4.0 if args.backend == "openrouter" else 0.0)
    if interval < 0:
        parser.error("--min-interval must be nonnegative")

    count, keep = args.count or BUDGET[args.mode][0], args.keep or BUDGET[args.mode][1]
    input_path = args.input or ROOT / INPUTS[args.mode]
    run_dir = args.out_root / "runs" / args.run_id
    validate_run_directory(run_dir, args.backend, endpoint, args.model, args.provider)
    cache_path = args.out_root / "resolve_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    client = make_client()
    examples = load_examples(args.mode, input_path)
    if args.ids:
        wanted = set()
        for part in args.ids.split(","):
            lo, _, hi = part.partition("-")
            wanted.update(range(int(lo), int(hi or lo) + 1))
        examples = [e for e in examples if e["id"] in wanted]
    examples = examples[:args.limit]
    key = adapter.api_key()
    results, last_call = [], 0.0

    for example in examples:
        messages = build_messages(args.mode, example, count)
        request = {"model": args.model, "messages": messages, "temperature": args.temperature,
                   "seed": args.seed, "response_format": song_schema()}
        if args.provider:  # only when set, so cache hashes of earlier runs stay valid
            request["provider"] = args.provider
        if args.backend == "local":  # likewise, OpenRouter request hashes stay unchanged
            request.update(backend=args.backend, endpoint=endpoint)
        result = {k: v for k, v in example.items() if k != "seed_tracks"}
        result.update(status="ok", parse_stats=None, call=None, recommendations=[])

        def call():
            nonlocal last_call
            time.sleep(max(0.0, interval - (time.monotonic() - last_call)))
            last_call = time.monotonic()
            options = {"url": endpoint} if args.backend == "local" else {"provider": args.provider}
            return adapter.complete(messages, args.model, args.temperature, args.seed, song_schema(),
                                    key=key, **options)

        try:
            response, cached = cached_complete(run_dir / "raw" / f"{args.mode}-{example['id']:02d}.json", request, call)
        except Exception as error:  # record and continue; failures are reported, not silently retried
            result.update(status="call_failed", error=str(error))
            results.append(result)
            print(f"{args.mode} {example['id']}: call failed: {error}", flush=True)
            continue
        result["call"] = {k: v for k, v in response.items() if k != "text"} | {"cached": cached}
        seeds = example.get("seed_tracks", [])
        try:
            songs, result["parse_stats"] = parse_songs(response["text"], exclude=track_keys(seeds))
        except ValueError as error:
            result.update(status="parse_failed", error=str(error))
            results.append(result)
            continue
        result["recommendations"] = rank_suggestions(
            songs, seeds, keep,
            lambda title, artist: resolve_song(client, title, artist, cache))
        save_json(cache_path, cache)
        results.append(result)
        top = sum(r["in_top_k"] for r in result["recommendations"])
        print(f"{args.mode} {example['id']}: {len(songs)} parsed, {top}/{keep} in top-K"
              f"{' (cached)' if cached else ''}", flush=True)

    calls = [r["call"] for r in results if r["call"]]
    run = {"schema_version": 1, "run_id": args.run_id, "mode": args.mode, "collected_at": timestamp(),
           "backend": args.backend, "endpoint": endpoint, "model_requested": args.model,
           "models_returned": sorted({c.get("model") for c in calls if c.get("model")}),
           "providers": sorted({c.get("provider") for c in calls if c.get("provider")}),
           "provider_pinned": args.provider, "ids": args.ids,
           "temperature": args.temperature, "seed": args.seed, "requested_count": count, "top_k": keep,
           "prompt_version": PROMPT_VERSION, "system_prompt": SYSTEM,
           "example_user_prompt": build_messages(args.mode, examples[0], count)[1]["content"] if examples else None,
           "input_file": str(input_path.relative_to(ROOT)) if input_path.is_relative_to(ROOT) else str(input_path),
           "limit": args.limit, "identity_note": "video_id from public search; alt_video_ids lists other matching uploads"}
    output = {"run": run, "summary": summarize(results, keep, args.backend), "examples": results}
    save_json(run_dir / f"{args.mode}.json", output)
    print(json.dumps(output["summary"], indent=2))


if __name__ == "__main__":
    main()
