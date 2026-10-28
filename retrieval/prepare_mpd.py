"""Pack audited MPD chunks and recording provenance for repeatable experiments.

  uv run python -m retrieval.prepare_mpd --audit data/retrieval/real-run/mpd-audit.json --output /data/user_data/hpoonia/mlip/retrieval/mpd-v1/snapshot

Only reads Kartik's files. NPZ hashes must match the prior audit, and every
embedded ID must have provenance. Preserves sorted-chunk/within-chunk ordering.
Keep the output on data storage: corpus.npz alone is over 2 GB.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np

from .catalog import EmbeddingCatalog, load_embeddings
from .index import checksum


def read_chunk(record):
    """Validate frozen vectors and return their matching recording evidence."""
    path = Path(record['file'])
    before = path.stat()
    if checksum(path) != record['sha256']:
        raise ValueError(f"embedding changed since audit: {path}")
    corpus = load_embeddings(path)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError(f"embedding changed during packing: {path}")
    if len(corpus.ids) != record['rows']:
        raise ValueError(f"row count changed: {path}")
    raw = path.with_suffix('.json').read_bytes()
    evidence = json.loads(raw)
    results = {r['id']: r for r in evidence['results'] if r['status'] == 'embedded'}
    if set(results) != set(corpus.ids):
        raise ValueError(f"embedding/provenance ID mismatch: {path}")
    rows = [(tid, results[tid].get('deezer_id'), results[tid].get('isrc'),
             results[tid].get('artist'), results[tid].get('title'),
             results[tid].get('duration'), results[tid].get('match_method'))
            for tid in corpus.ids]
    return corpus, rows, dict(file=str(path.with_suffix('.json')),
                             sha256=hashlib.sha256(raw).hexdigest(),
                             complete=evidence.get('complete'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error('workers must be positive')
    args.output.mkdir(parents=True, exist_ok=False)
    audit = json.loads(args.audit.read_text())
    ids, blocks, provenance = [], [], []
    db = sqlite3.connect(args.output / 'tracks.sqlite')
    db.execute('CREATE TABLE tracks (id TEXT PRIMARY KEY, deezer_id INTEGER, isrc TEXT, artist TEXT, title TEXT, duration INTEGER, match_method TEXT)')
    with db, ThreadPoolExecutor(max_workers=args.workers) as pool:
        for catalog, rows, evidence in pool.map(read_chunk, audit['files']):
            ids.extend(catalog.ids)
            blocks.append(catalog.vectors)
            provenance.append(evidence)
            db.executemany('INSERT INTO tracks VALUES (?,?,?,?,?,?,?)', rows)
            if len(provenance) % 1000 == 0:
                print(f"Packed {len(provenance)}/{len(audit['files'])} chunks, {len(ids)} vectors", flush=True)
    db.execute('CREATE INDEX track_isrc ON tracks(isrc)')
    db.execute('CREATE INDEX track_deezer ON tracks(deezer_id)')
    db.commit()
    db.close()
    matrix = np.concatenate(blocks)
    blocks.clear()
    catalog = EmbeddingCatalog(ids, matrix)
    if len(catalog.ids) != audit['rows'] or catalog.vectors.shape[1] != audit['dimension']:
        raise ValueError('packed corpus differs from audit')
    np.savez(args.output / 'corpus.npz', ids=catalog.ids, vectors=catalog.vectors)
    manifest = dict(
        rows=len(catalog.ids), dimension=catalog.vectors.shape[1],
        corpus_fingerprint=catalog.fingerprint,
        source_audit=audit, provenance=provenance,
        checksums={name: checksum(args.output / name)
                   for name in ['corpus.npz', 'tracks.sqlite']},
    )
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: manifest[k] for k in ['rows', 'dimension', 'corpus_fingerprint']}), flush=True)
