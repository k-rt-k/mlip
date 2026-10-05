import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('pipeline', SCRIPTS / 'mpd_pipeline.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def test_migration_preserves_vectors_and_skips_resolved_tracks(tmp_path):
    out = tmp_path / 'out'; out.mkdir()
    target = out / 'shard-0-of-2'; target.mkdir()
    old = np.arange(512, dtype=np.float32)
    old /= np.linalg.norm(old)
    pipeline.save(target / 'chunk-000000.npz', {'a': old})
    prior = {'ids': ['a', 'b', 'c'], 'results': [
        {'id': 'a', 'status': 'embedded', 'isrc': 'OLD'},
        {'id': 'b', 'status': 'no_strict_match'},
        {'id': 'c', 'status': 'request_failed'}], 'complete': False}
    pipeline.atomic_json(target / 'chunk-000000.json', prior)
    clips = tmp_path / 'clips'; clips.mkdir()
    (clips / 'c.mp3').write_bytes(b'ID3test')
    calls = []
    def fetch(track):
        calls.append(track['id'])
        return {'id': track['id'], 'status': 'ready', 'isrc': 'NEW'}
    payload = pipeline.prepare([{'id': t} for t in 'abc'], prior, fetch)
    assert calls == ['c']
    queue = tmp_path / 'queue'; queue.mkdir()
    bundle = pipeline.publish(queue, 0, 0, payload, clips)
    class Model:
        def embed_audio(self, paths, on_error):
            assert [p.stem for p in paths] == ['c']
            return np.ones((1, 512), dtype=np.float32)/np.sqrt(512)
    pipeline.consume(bundle, out, tmp_path / 'decode', Model())
    result = pipeline.load_existing(target / 'chunk-000000.npz')
    np.testing.assert_array_equal(result['a'], old)
    assert set(result) == {'a', 'c'}
    info = json.loads((target / 'chunk-000000.json').read_text())
    assert info['complete']
    assert info['results'][0]['isrc'] == 'OLD'
    assert not list(queue.iterdir())


def test_batch_failure_alignment_and_retry(tmp_path):
    queue = tmp_path / 'queue'; queue.mkdir()
    clips = tmp_path / 'clips'; clips.mkdir()
    for tid in 'abc': (clips / f'{tid}.mp3').write_bytes(b'ID3test')
    payload = {'ids': list('abc'), 'results': [{'id': t, 'status': 'ready'} for t in 'abc']}
    bundle = pipeline.publish(queue, 1, 2, payload, clips)
    class Model:
        def embed_audio(self, paths, on_error):
            assert len(paths) == 3
            on_error(paths[1], 'bad audio')
            rows = np.zeros((2,512),dtype=np.float32); rows[0,0]=1; rows[1,1]=1
            return rows
    out = tmp_path / 'out'
    pipeline.consume(bundle, out, tmp_path / 'decode', Model())
    target = out / 'shard-1-of-2/chunk-000002.npz'
    assert set(pipeline.load_existing(target)) == {'a','c'}
    meta = json.loads(target.with_suffix('.json').read_text())
    assert not meta['complete']
    assert meta['results'][1]['status'] == 'decode_failed'


def test_rate_limiter_spaces_requests():
    import time
    limiter = pipeline.RateLimiter(100)
    start = time.monotonic()
    for _ in range(4): limiter.wait()
    assert time.monotonic() - start >= .025


def test_interrupted_checkpoint_retries_missing_vectors(tmp_path):
    target = tmp_path / 'chunk-000000.json'
    prior = {'ids': ['a', 'b'], 'results': [
        {'id': 'a', 'status': 'embedded'}, {'id': 'b', 'status': 'embedded'}], 'complete': True}
    pipeline.atomic_json(target, prior)
    vector = np.ones(512, dtype=np.float32) / np.sqrt(512)
    pipeline.save(target.with_suffix('.npz'), {'a': vector})
    restored = pipeline.read_checkpoint(target, ['a', 'b'])
    assert not restored['complete']
    calls = []
    payload = pipeline.prepare([{'id': t} for t in 'ab'], restored,
        lambda t: (calls.append(t['id']) or {'id': t['id'], 'status': 'ready'}))
    assert calls == ['b']
    assert payload['results'][0]['status'] == 'embedded'


def test_consumer_rejects_missing_embedded_vector(tmp_path):
    import pytest
    queue = tmp_path / 'queue'; queue.mkdir()
    clips = tmp_path / 'clips'; clips.mkdir()
    bundle = pipeline.publish(queue, 0, 0,
        {'ids': ['a'], 'results': [{'id': 'a', 'status': 'embedded'}]}, clips)
    with pytest.raises(RuntimeError, match='missing vector'):
        pipeline.consume(bundle, tmp_path / 'out', tmp_path / 'decode', None)
    assert bundle.exists()


def test_live_consumer_is_not_replaced_for_stale_heartbeat(tmp_path, monkeypatch):
    from types import SimpleNamespace
    pipeline.atomic_json(tmp_path / 'consumer-state.json',
                         {'job_id': '123', 'phase': 'active', 'time': 0})
    monkeypatch.setattr(pipeline.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout='RUNNING\n', stderr=''))
    assert pipeline.consumer_active({'job_id': '123'})
    monkeypatch.setattr(pipeline.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout='REQUEUED\n', stderr=''))
    assert pipeline.consumer_active({'job_id': '123'})


def test_submit_consumer_passes_custom_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace
    args = SimpleNamespace(catalog=tmp_path / 'catalog', output=tmp_path / 'out',
                           queue=tmp_path / 'queue')
    captured = {}
    def submit(command, **kwargs):
        captured.update(kwargs)
        return '123;cluster\n'
    monkeypatch.setattr(pipeline.subprocess, 'check_output', submit)
    assert pipeline.submit_consumer(args) == '123'
    assert captured['env']['PIPELINE_CATALOG'] == str(args.catalog)
    assert captured['env']['PIPELINE_OUTPUT'] == str(args.output)
    assert captured['env']['PIPELINE_QUEUE'] == str(args.queue)
