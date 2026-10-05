"""Resolve MPD tracks conservatively, then checkpoint preview embeddings by chunk.

One worker owns a shard. Results preserve Spotify IDs and Deezer match evidence.
Preview files are deleted after a successful checkpoint to bound scratch usage.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import requests

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'spotify/src'))
from embeddings import get_embedder
from jobs import record, require_persistent_out, shard_of, parse_shard
from mpd import choose_candidate
from previews import download_previews
from embed import save, load_existing


def resolve(track, session, pause):
    for attempt in range(3):
        try:
            try:
                response = session.get('https://api.deezer.com/search',
                    params={'q': f'{track["artist"]} {track["title"]}', 'limit': 25}, timeout=30)
            finally:
                time.sleep(pause)
            response.raise_for_status()
            body = response.json()
            if 'error' in body:
                raise requests.RequestException(f'Deezer error: {body["error"]}')
            return choose_candidate(track, body.get('data', []))
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5 * 2 ** attempt)



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog', type=Path, required=True)
    p.add_argument('--out-dir', type=Path, required=True)
    p.add_argument('--preview-dir', type=Path, required=True)
    p.add_argument('--model', choices=['clap', 'muq', 'clamp3'], default='clap')
    p.add_argument('--shard', default='0/1')
    p.add_argument('--limit', type=int)
    p.add_argument('--chunk', type=int, default=128)
    p.add_argument('--device', default='cuda')
    args = p.parse_args()
    if args.chunk < 1 or (args.limit is not None and args.limit < 1):
        p.error('chunk and limit must be positive')
    index, total = parse_shard(args.shard)
    out = require_persistent_out(args.out_dir, REPO) / args.model / f'shard-{index}-of-{total}'
    out.mkdir(parents=True, exist_ok=True)
    settings = {'catalog': str(args.catalog.resolve()), 'chunk': args.chunk,
                'model': args.model, 'shard': args.shard, 'match_policy': 'full-title-artist-duration2s-v1'}
    config = out / 'config.json'
    if config.exists() and json.loads(config.read_text()) != settings:
        raise RuntimeError('run settings changed; use a new output directory')
    config.write_text(json.dumps(settings, indent=2))
    log = out / 'events.jsonl'
    record(log, event='start', settings=settings, limit=args.limit)
    # Read-only SQLite works on persistent storage; each worker has its own outputs.
    db = sqlite3.connect(f'file:{args.catalog}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    cursor = db.execute('SELECT * FROM tracks ORDER BY id')
    session = requests.Session()
    model = None
    chunk = []
    selected = 0
    chunk_index = 0

    def process(tracks, number):
        nonlocal model
        target = out / f'chunk-{number:06d}.npz'
        evidence = out / f'chunk-{number:06d}.json'
        if evidence.exists():
            previous = json.loads(evidence.read_text())
            if previous['ids'] != [t['id'] for t in tracks]:
                raise RuntimeError('chunk input changed; use a new output directory')
            if previous.get('complete'):
                expected = {r['id'] for r in previous['results'] if r['status'] == 'embedded'}
                if expected != set(load_existing(target)):
                    raise RuntimeError('checkpoint IDs do not match provenance')
                return
        vectors = load_existing(target)
        statuses = []
        for t in tracks:
            tid = t['id']
            if tid in vectors:
                # Keep provenance when retrying other tracks in this chunk.
                old = next((r for r in previous['results'] if r['id'] == tid), None) if evidence.exists() else None
                if old is None:
                    raise RuntimeError('vectors lack provenance; inspect interrupted checkpoint')
                statuses.append(old)
                continue
            try:
                match = resolve(t, session, 0.25 * total)
                status = {'id': tid, 'status': 'no_strict_match'}
                if match:
                    status.update(status='matched', deezer_id=match['id'], isrc=match['isrc'],
                                  artist=match['artist']['name'], title=match['title'], duration=match['duration'],
                                  match_method='metadata_full_title_artist_duration_2s')
                    clips, missing = download_previews({tid: {'preview_url': match['preview']}},
                                                       args.preview_dir, pause=0.25 * total)
                    if missing:
                        status['status'] = 'download_failed'
                    else:
                        if model is None:
                            model = get_embedder(args.model, device=args.device)
                            config = getattr(getattr(model, '_model', None), 'config', None)
                            record(log, event='model_loaded', model=args.model,
                                   revision=getattr(config, '_commit_hash', None), device=args.device)
                        failures = []
                        result = model.embed_audio([clips[tid]], on_error=lambda path, error: failures.append(error))
                        if failures:
                            status.update(status='decode_failed', error=failures[0])
                        elif result.shape[0] != 1 or not np.isfinite(result).all():
                            raise RuntimeError('invalid embedding output')
                        else:
                            vectors[tid] = result[0]
                            status['status'] = 'embedded'
                statuses.append(status)
            except requests.RequestException as exc:
                statuses.append({'id': tid, 'status': 'request_failed', 'error': str(exc)})
            print(f'{tid}: {statuses[-1]["status"]}', flush=True)
        # Publish evidence first (incomplete), then vectors, then completion.
        # Resume may recompute a missing vector, but never loses provenance.
        payload = {'ids': [t['id'] for t in tracks], 'results': statuses, 'complete': False}
        tmp = evidence.with_suffix('.json.part')
        tmp.write_text(json.dumps(payload, indent=2)); tmp.replace(evidence)
        if vectors:
            save(target, vectors)
        payload['complete'] = all(s['status'] in ('embedded', 'no_strict_match') for s in statuses)
        tmp.write_text(json.dumps(payload, indent=2)); tmp.replace(evidence)
        for tid in payload["ids"]:
            (args.preview_dir / f'{tid}.mp3').unlink(missing_ok=True)
        record(log, event='chunk', chunk=number, tracks=len(tracks), embedded=len(vectors), complete=payload['complete'])
        if shutil.disk_usage(args.preview_dir).free < 5 * 1024**3:
            raise RuntimeError('less than 5 GiB scratch free')

    args.preview_dir.mkdir(parents=True, exist_ok=True)
    for row in cursor:
        if shard_of(row['id'], total) != index:
            continue
        chunk.append(dict(row)); selected += 1
        if len(chunk) == args.chunk:
            process(chunk, chunk_index); chunk = []; chunk_index += 1
        if args.limit and selected >= args.limit:
            break
    if chunk:
        process(chunk, chunk_index)
    record(log, event='done', selected=selected)

if __name__ == '__main__':
    main()
