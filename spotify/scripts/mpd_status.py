"""Summarize durable MPD embedding checkpoints, including coverage gaps."""
import argparse
from collections import Counter
import json
from pathlib import Path

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    counts = Counter()
    chunks = complete = 0
    for path in args.output.glob('*/shard-*/chunk-*.json'):
        payload = json.loads(path.read_text())
        counts.update(r['status'] for r in payload['results'])
        chunks += 1
        complete += bool(payload['complete'])
    print(json.dumps({'chunks': chunks, 'complete_chunks': complete,
                      'tracks_checkpointed': sum(counts.values()),
                      'outcomes': dict(counts)}, indent=2))
