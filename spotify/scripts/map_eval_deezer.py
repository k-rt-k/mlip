"""Map YouTube Music eval songs to Deezer recordings, then optionally embed their previews with CLAP.

Run from the repo root after extracting datasets/baselines-v4.zip (see README.md):

    python spotify/scripts/map_eval_deezer.py            # map only: network, CPU, ~1 h at 2 req/s
    python spotify/scripts/map_eval_deezer.py --embed    # map, then embed matched previews (GPU)

Outputs go to --out (under /data/user_data, never in git):
    deezer_map.json   {video_id: record}; record has status matched/no_match/request_failed,
                      Deezer ID, ISRC, matched artist/title/duration, match_method, query,
                      and the YouTube metadata + eval sources it was matched from
    clap.npz          ids (video IDs) and 512-D L2-normalized CLAP vectors of 30 s previews
    clap-status.json  {video_id: embedded/no_preview/download_failed/decode_failed[, error]}
    events.jsonl      run log
Resumable: map records are kept except request_failed; every unembedded match is retried.
On Babel submit spotify/scripts/map_eval_deezer.sbatch (GPU, packaged runtime).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import numpy as np
import requests

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'spotify/src'))
sys.path.insert(0, str(REPO / 'spotify/scripts'))
from deezer import LimitedSession, RateLimiter, fresh_preview, search_candidates
from embed import load_existing, save
from eval_songs import collect_eval_songs, resolve_song
from jobs import record, require_persistent_out
from previews import download_previews

YOUTUBE_FIELDS = ('title', 'artists', 'album', 'duration_seconds', 'video_type', 'sources')
RETRY = {'request_failed'}


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + '.part')
    tmp.write_text(json.dumps(value, indent=1, sort_keys=True))
    tmp.replace(path)


def map_songs(songs, path, session, threads, log):
    records = json.loads(path.read_text()) if path.exists() else {}
    todo = [s for vid, s in songs.items() if records.get(vid, {}).get('status') in (None, *RETRY)]
    record(log, event='map_start', songs=len(songs), todo=len(todo))

    def one(song):
        try:
            rec = resolve_song(song, lambda q: search_candidates(session, q))
        except requests.RequestException as exc:
            rec = dict(video_id=song['video_id'], status='request_failed', error=str(exc)[:200])
        rec['youtube'] = {k: song.get(k) for k in YOUTUBE_FIELDS}
        return rec

    with ThreadPoolExecutor(threads) as pool:
        for i, rec in enumerate(pool.map(one, todo), 1):
            records[rec['video_id']] = rec
            if i % 100 == 0 or i == len(todo):
                write_json(path, records)
                print(f'mapped {i}/{len(todo)}', flush=True)
    write_json(path, records)
    return records


def embed_matches(records, out, scratch, session, device, log, batch=64):
    from embeddings import get_embedder
    vectors = load_existing(out / 'clap.npz')
    status_path = out / 'clap-status.json'
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    # Everything not yet embedded is retried: failures here are few and often environmental.
    todo = [r for vid, r in sorted(records.items()) if r['status'] == 'matched' and vid not in vectors]
    record(log, event='embed_start', todo=len(todo), existing=len(vectors))
    model = get_embedder('clap', device=device) if todo else None
    scratch.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(todo), batch):
        part = todo[start:start + batch]
        urls = {}
        for rec in part:  # preview URLs are signed for ~15 minutes, so fetch them just in time
            try:
                urls[rec['video_id']] = fresh_preview(session, rec['deezer_id'])
            except requests.RequestException as exc:
                status[rec['video_id']] = dict(status='download_failed', error=type(exc).__name__)
        errors = {}
        clips, _ = download_previews({vid: {'preview_url': url} for vid, url in urls.items() if url},
                                     scratch, pause=0, retries=3, backoff=5, errors=errors)
        for vid, url in urls.items():
            if not url:
                status[vid] = dict(status='no_preview')
            elif vid not in clips:
                status[vid] = dict(status='download_failed', error=errors.get(vid))
        ids = sorted(clips)
        failures = {}
        if not ids:
            write_json(status_path, status)
            continue
        matrix = model.embed_audio([clips[v] for v in ids], on_error=lambda p, e: failures.update({p.stem: str(e)[:200]}))
        ok = [v for v in ids if v not in failures]
        if matrix.shape[0] != len(ok) or (ok and not np.isfinite(matrix).all()):
            raise RuntimeError('invalid CLAP batch output')
        vectors.update(zip(ok, matrix))
        status.update({v: dict(status='embedded') for v in ok})
        status.update({v: dict(status='decode_failed', error=e) for v, e in failures.items()})
        if vectors:
            save(out / 'clap.npz', vectors)
        write_json(status_path, status)
        for path in clips.values():
            path.unlink(missing_ok=True)
        print(f'embedded {len(vectors)} ({start + len(part)}/{len(todo)} attempted)', flush=True)
    return vectors, status


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--partial', type=Path, default=REPO / 'data/youtube_music/partial_examples/v3/dataset.json')
    p.add_argument('--references', type=Path, default=REPO / 'data/youtube_music/references/v2/reference_pools.json')
    p.add_argument('--out', type=Path, default=Path('/data/user_data/ksnair/mlip/embeddings/ytm-eval'))
    p.add_argument('--scratch', type=Path, default=Path('/scratch/ksnair/mlip/ytm-eval-previews'))
    p.add_argument('--rate', type=float, default=2, help='Deezer API requests per second (shared IP limit ~10)')
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--limit', type=int, help='only the first N songs by video ID (smoke tests)')
    p.add_argument('--embed', action='store_true', help='download fresh previews and CLAP-embed matched songs')
    p.add_argument('--device', default='cuda')
    args = p.parse_args()
    if not 0 < args.rate <= 9:
        p.error('rate must be in (0, 9]')
    for path in (args.partial, args.references):
        if not path.exists():
            p.error(f'{path} missing; extract datasets/baselines-v4.zip at the repo root (README.md)')
    out = require_persistent_out(args.out, REPO)
    out.mkdir(parents=True, exist_ok=True)
    log = out / 'events.jsonl'
    session = LimitedSession(RateLimiter(args.rate))
    songs = collect_eval_songs(args.partial, args.references)
    if args.limit:
        songs = dict(sorted(songs.items())[:args.limit])
    records = map_songs(songs, out / 'deezer_map.json', session, args.threads, log)
    counts = {s: sum(r['status'] == s for r in records.values()) for s in ('matched', 'no_match', 'request_failed')}
    record(log, event='map_done', **counts)
    print(json.dumps(counts), flush=True)
    if args.embed:
        vectors, status = embed_matches(records, out, args.scratch, session, args.device, log)
        summary = {s: sum(v['status'] == s for v in status.values()) for s in {v['status'] for v in status.values()}}
        record(log, event='embed_done', vectors=len(vectors), **summary)
        print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
