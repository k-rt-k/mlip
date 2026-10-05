"""Verify every pre-migration vector against the saved checkpoint archive."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import tarfile
import numpy as np

root = Path('/data/user_data/ksnair/mlip')
audit = json.loads((root / 'migration-v2/audit-before.json').read_text())
output = root / 'embeddings/mpd-full/clap'
records = {r['file'].replace('.json', '.npz'): r for r in audit['records']}
def checksum(item):
    key, record = item
    return key, hashlib.sha256((output / key).read_bytes()).hexdigest() != record['npz_sha256']

with ThreadPoolExecutor(max_workers=8) as pool:
    modified = dict(pool.map(checksum, ((key, record) for key, record in records.items() if record['embedded'])))
print(f'Hashed {len(modified)} checkpoint files; comparing modified files against backup', flush=True)
checked = changed = preserved = 0
with tarfile.open(root / 'migration-v2/checkpoints-before.tar', mode='r|', bufsize=1024*1024) as archive:
    for member in archive:
        if not member.isfile() or not member.name.endswith('.npz'):
            continue
        key = '/'.join(member.name.split('/')[-2:])
        record = records[key]
        current = output / key
        if modified[key]:
            blob = current.read_bytes()
            changed += 1
            with np.load(io.BytesIO(archive.extractfile(member).read())) as old, np.load(io.BytesIO(blob)) as new:
                rows = dict(zip(new['ids'].tolist(), new['vectors']))
                for tid, vector in zip(old['ids'].tolist(), old['vectors']):
                    np.testing.assert_array_equal(vector, rows[tid])
        preserved += record['embedded']
        checked += 1
if checked != sum(r['embedded'] > 0 for r in records.values()):
    raise RuntimeError(f'backup checkpoint count differs: {checked}')
if preserved != audit['outcomes']['embedded']:
    raise RuntimeError(f'preserved embedding count differs: {preserved}')
result = {'checked_npz': checked, 'modified_npz': changed, 'preserved_embeddings': preserved}
(root / 'migration-v2/audit-after.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
