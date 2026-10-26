"""Decoupled MPD fetching and batched inference, preserving v1 checkpoints."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import threading
import time

import numpy as np
import requests

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'spotify/src'))
from embeddings import get_embedder
from jobs import record, shard_of, require_persistent_out
from previews import download_previews
from embed import load_existing, save
from embed_mpd import resolve
from deezer import LimitedSession, RateLimiter  # noqa: F401  (re-exported for tests)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.part')
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(path)


def read_checkpoint(path, ids):
    """Reconcile evidence published before an interrupted vector save."""
    if not path.exists():
        return {}
    previous = json.loads(path.read_text())
    if previous['ids'] != ids:
        raise RuntimeError('catalog/shard/chunk mapping changed')
    vectors = load_existing(path.with_suffix('.npz'))
    expected = {r['id'] for r in previous['results'] if r['status'] == 'embedded'}
    if not set(vectors).issubset(expected):
        raise RuntimeError('existing vectors lack matching provenance')
    for result in previous['results']:
        if result['status'] == 'embedded' and result['id'] not in vectors:
            result['status'] = 'request_failed'
    previous['complete'] = all(r['status'] in ('embedded', 'no_strict_match')
                               for r in previous['results'])
    return previous


def prepare(tracks, previous, fetch, executor=None):
    old = {r['id']: r for r in previous.get('results', [])}
    pending = [t for t in tracks if old.get(t['id'], {}).get('status')
               not in ('embedded', 'no_strict_match')]
    results = (executor.map(fetch, pending) if executor else map(fetch, pending))
    old.update((r['id'], r) for r in results)
    return {'ids': [t['id'] for t in tracks], 'results': [old[t['id']] for t in tracks]}


def publish(queue, shard, number, payload, clips):
    stem = f'shard-{shard}-chunk-{number:06d}'
    archive = queue / f'{stem}.tar'
    partial = archive.with_suffix('.tar.part')
    ready = [r['id'] for r in payload['results'] if r['status'] == 'ready']
    with tarfile.open(partial, 'w') as tar:
        for tid in ready:
            tar.add(clips / f'{tid}.mp3', arcname=f'{tid}.mp3')
    partial.replace(archive)
    bundle = queue / f'{stem}.json'
    atomic_json(bundle, {**payload, 'shard': shard, 'chunk': number})
    for tid in ready:
        (clips / f'{tid}.mp3').unlink(missing_ok=True)
    return bundle


def consume(bundle, output, scratch, model):
    payload = json.loads(bundle.read_text())
    target = output / f'shard-{payload["shard"]}-of-2' / f'chunk-{payload["chunk"]:06d}.npz'
    evidence = target.with_suffix('.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    vectors = load_existing(target)
    previous = json.loads(evidence.read_text()) if evidence.exists() else {}
    if previous and previous['ids'] != payload['ids']:
        raise RuntimeError('checkpoint input IDs changed')
    expected = {r['id'] for r in previous.get('results', []) if r['status'] == 'embedded'}
    if not set(vectors).issubset(expected):
        raise RuntimeError('existing vectors lack matching provenance')
    statuses = {r['id']: r for r in payload['results']}
    for old in previous.get('results', []):
        if old['id'] in vectors:
            statuses[old['id']] = old
    if any(r['status'] == 'embedded' and r['id'] not in vectors for r in statuses.values()):
        raise RuntimeError('queued embedded track has a missing vector; rebuild the bundle')
    pending = [tid for tid in payload['ids'] if statuses[tid]['status'] == 'ready' and tid not in vectors]
    scratch.mkdir(parents=True, exist_ok=True)
    paths = []
    try:
        with tarfile.open(bundle.with_suffix('.tar')) as tar:
            for tid in pending:
                if not tid.isalnum():
                    raise RuntimeError('invalid track ID')
                member = tar.getmember(f'{tid}.mp3')
                if not member.isfile():
                    raise RuntimeError('invalid preview archive member')
                dest = scratch / f'{tid}.mp3'
                with tar.extractfile(member) as src, dest.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                paths.append(dest)
        if paths:
            failures = {}
            matrix = model.embed_audio(paths, on_error=lambda path, error: failures.update({path.stem: error}))
            successful = [tid for tid in pending if tid not in failures]
            if matrix.shape != (len(successful), 512) or not np.isfinite(matrix).all():
                if successful or matrix.shape != (0, 0):
                    raise RuntimeError('invalid CLAP batch output')
            if successful and not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-5):
                raise RuntimeError('CLAP output is not normalized')
            vectors.update(zip(successful, matrix))
            for tid in successful:
                statuses[tid]['status'] = 'embedded'
            for tid, error in failures.items():
                statuses[tid].update(status='decode_failed', error=error)
        final = {'ids': payload['ids'], 'results': [statuses[t] for t in payload['ids']], 'complete': False}
        # Same publication order as v1; a kill can only cause recomputation.
        atomic_json(evidence, final)
        if vectors:
            save(target, vectors)
        final['complete'] = all(r['status'] in ('embedded', 'no_strict_match') for r in final['results'])
        atomic_json(evidence, final)
        record(output / 'pipeline-events.jsonl', event='batch', shard=payload['shard'],
               chunk=payload['chunk'], embedded=len(vectors), new_embeddings=len(pending)-len(failures) if paths else 0,
               complete=final['complete'])
        # JSON is the ready marker. Remove it before its archive.
        bundle.unlink()
        bundle.with_suffix('.tar').unlink(missing_ok=True)
        return len(vectors)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def producer(args):
    limiter = RateLimiter(args.rate)
    local = threading.local()
    log = args.queue / 'producer-events.jsonl'
    (args.queue / 'producer-done.json').unlink(missing_ok=True)
    def fetch(track):
        if not hasattr(local, 'session'):
            local.session = LimitedSession(limiter)
        tid = track['id']
        try:
            match = resolve(track, local.session, 0)
            if match is None:
                return {'id': tid, 'status': 'no_strict_match'}
            status = dict(id=tid, status='ready', deezer_id=match['id'], isrc=match['isrc'],
                          artist=match['artist']['name'], title=match['title'], duration=match['duration'],
                          match_method='metadata_full_title_artist_duration_2s')
            errors = {}
            _, missing = download_previews({tid: {'preview_url': match['preview']}}, args.scratch, pause=0,
                                           retries=3, backoff=5, errors=errors)
            if missing:
                status.update(status='download_failed', error=errors.get(tid))
            return status
        except requests.RequestException as exc:
            return {'id': tid, 'status': 'request_failed', 'error': str(exc)}

    # SQLite's ID index causes random reads; keep the immutable catalog local.
    local_catalog = args.scratch / 'catalog.sqlite'
    partial = local_catalog.with_suffix('.sqlite.part')
    shutil.copyfile(args.catalog, partial)
    partial.replace(local_catalog)
    print('catalog staged on scratch', flush=True)
    db = sqlite3.connect(f'file:{local_catalog}?mode=ro', uri=True)
    db.execute('PRAGMA cache_size=-524288')
    db.row_factory = sqlite3.Row
    groups = [[], []]; numbers = [0, 0]; submitted = 0
    record(log, event='start', rate=args.rate, threads=args.threads)
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        def process(shard):
            nonlocal submitted
            tracks = groups[shard]; number = numbers[shard]
            groups[shard] = []; numbers[shard] += 1
            path = args.output / f'shard-{shard}-of-2' / f'chunk-{number:06d}.json'
            previous = read_checkpoint(path, [t['id'] for t in tracks])
            if previous.get('complete'):
                return
            queued = args.queue / f'shard-{shard}-chunk-{number:06d}.json'
            if queued.exists():
                return
            while len(list(args.queue.glob('shard-*-chunk-*.json'))) >= args.max_queue:
                time.sleep(5)
            if min(shutil.disk_usage(args.scratch).free, shutil.disk_usage(args.queue).free) < 5*1024**3:
                raise RuntimeError('less than 5 GiB storage free')
            start = time.monotonic()
            payload = prepare(tracks, previous, fetch, executor)
            publish(args.queue, shard, number, payload, args.scratch)
            submitted += 1
            record(log, event='queued', shard=shard, chunk=number, tracks=len(tracks),
                   ready=sum(r['status']=='ready' for r in payload['results']), seconds=time.monotonic()-start)
            print(f'queued shard={shard} chunk={number} in {time.monotonic()-start:.1f}s', flush=True)

        for row in db.execute('SELECT * FROM tracks ORDER BY id'):
            shard = shard_of(row['id'], 2)
            groups[shard].append(dict(row))
            if len(groups[shard]) == 128:
                process(shard)
                if args.max_chunks and submitted >= args.max_chunks:
                    record(log, event='pilot_done', chunks=submitted)
                    return
        for shard in range(2):
            if groups[shard]: process(shard)
    atomic_json(args.queue / 'producer-done.json', {'chunks': submitted, 'time': time.time()})
    record(log, event='done', chunks=submitted)


def consumer(args):
    model = None
    processed = 0
    while True:
        if (args.queue / 'pipeline-error.json').exists():
            raise RuntimeError('CPU supervisor failed; see pipeline-error.json')
        atomic_json(args.queue / 'consumer-state.json',
                    {'phase': 'active', 'time': time.time(), 'job_id': os.environ.get('SLURM_JOB_ID')})
        bundles = sorted(args.queue.glob('shard-*-chunk-*.json'), key=lambda p: p.stat().st_mtime)
        if not bundles:
            if (args.queue / 'producer-done.json').exists() or args.drain:
                return
            time.sleep(2)
            continue
        for bundle in bundles:
            if model is None and any(r['status']=='ready' for r in json.loads(bundle.read_text())['results']):
                model = get_embedder('clap', device=args.device)
            start = time.monotonic()
            embedded = consume(bundle, args.output, args.scratch, model)
            print(f'{bundle.stem}: {embedded} embeddings, {time.monotonic()-start:.1f}s', flush=True)
            processed += 1
            if args.max_chunks and processed >= args.max_chunks:
                return



def consumer_active(job):
    """SLURM owns liveness; stale heartbeats must not duplicate live jobs."""
    if not job.get('job_id'):
        return False
    result = subprocess.run(['squeue', '-h', '-j', str(job['job_id']), '-o', '%T'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        if 'Invalid job id' in result.stderr:  # finished long ago and purged by SLURM
            return False
        raise RuntimeError(f'cannot check GPU job: {result.stderr}')
    return bool(result.stdout.strip())


def submit_consumer(args):
    command = ['sbatch', '--parsable', '--job-name=mpd-batch', '--gres=gpu:1',
               '--qos=preempt_qos', '--mem=24G', f'--chdir={REPO}',
               '--output=/data/user_data/ksnair/mlip/logs/%x-%j.out',
               '--export=ALL,ROLE=consume,MAX_CHUNKS=',
               str(REPO / 'spotify/scripts/mpd_pipeline.sbatch')]
    environment = dict(os.environ, PIPELINE_CATALOG=str(args.catalog),
                       PIPELINE_OUTPUT=str(args.output), PIPELINE_QUEUE=str(args.queue))
    return subprocess.check_output(command, text=True, env=environment).strip().split(';')[0]


def supervise(args):
    """Keep the CPU producer and one GPU consumer alive across preemptions."""
    command = [sys.executable, str(Path(__file__).resolve()), 'produce',
               '--catalog', str(args.catalog), '--output', str(args.output),
               '--queue', str(args.queue), '--scratch', str(args.scratch),
               '--rate', str(args.rate), '--threads', str(args.threads),
               '--max-queue', str(args.max_queue)]
    (args.queue / 'pipeline-error.json').unlink(missing_ok=True)
    producer_process = subprocess.Popen(command)
    job_file = args.queue / 'consumer-job.json'
    log = args.queue / 'supervisor-events.jsonl'
    try:
        while True:
            status = producer_process.poll()
            if status not in (None, 0):
                raise RuntimeError(f'producer exited with status {status}')
            bundles = list(args.queue.glob('shard-*-chunk-*.json'))
            if status == 0 and not bundles and (args.queue / 'producer-done.json').exists():
                record(log, event='done')
                return
            if bundles:
                job = json.loads(job_file.read_text()) if job_file.exists() else {}
                if not consumer_active(job):
                    job_id = submit_consumer(args)
                    atomic_json(job_file, {'job_id': job_id, 'submitted': time.time()})
                    record(log, event='gpu_submitted', job=job_id)
            time.sleep(30)
    except BaseException as exc:
        atomic_json(args.queue / 'pipeline-error.json', {'error': str(exc), 'time': time.time()})
        raise
    finally:
        if producer_process.poll() is None:
            producer_process.terminate()
            producer_process.wait()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('role', choices=['produce', 'consume', 'supervise'])
    p.add_argument('--catalog', type=Path, default=Path('/data/user_data/ksnair/mlip/data/mpd/catalog.sqlite'))
    p.add_argument('--output', type=Path, default=Path('/data/user_data/ksnair/mlip/embeddings/mpd-full/clap'))
    p.add_argument('--queue', type=Path, default=Path('/data/user_data/ksnair/mlip/queue-v2'))
    p.add_argument('--scratch', type=Path, required=True)
    p.add_argument('--rate', type=float, default=4)
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--max-queue', type=int, default=32)
    p.add_argument('--max-chunks', type=int)
    p.add_argument('--device', default='cuda')
    p.add_argument('--drain', action='store_true')
    args = p.parse_args()
    # Deezer allows 50 requests / 5 s per IP; Babel shares egress IPs, so stay below it.
    if args.rate <= 0 or args.rate > 9 or args.threads < 1 or args.max_queue < 1:
        p.error('rate must be in (0,9], threads and max-queue must be positive')
    args.output = require_persistent_out(args.output, REPO)
    args.queue = require_persistent_out(args.queue, REPO)
    args.queue.mkdir(parents=True, exist_ok=True); args.scratch.mkdir(parents=True, exist_ok=True)
    # One producer owns the global API budget; one consumer owns final checkpoints.
    with (args.queue / f'{args.role}.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            {'produce': producer, 'consume': consumer, 'supervise': supervise}[args.role](args)
            if args.role == 'consume':
                atomic_json(args.queue / 'consumer-state.json',
                            {'phase': 'done', 'time': time.time(), 'job_id': os.environ.get('SLURM_JOB_ID')})
        except BaseException:
            if args.role == 'consume':
                atomic_json(args.queue / 'consumer-state.json',
                            {'phase': 'error', 'time': time.time(), 'job_id': os.environ.get('SLURM_JOB_ID')})
            raise

if __name__ == '__main__':
    main()
