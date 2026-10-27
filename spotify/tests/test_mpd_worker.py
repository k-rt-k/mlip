import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('mpd_worker', SCRIPTS / 'embed_mpd.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_checkpoint_provenance_resume_and_cleanup(tmp_path, monkeypatch):
    catalog = tmp_path / 'tracks.sqlite'
    with sqlite3.connect(catalog) as db:
        db.execute('CREATE TABLE tracks (id TEXT, artist TEXT, title TEXT, duration_ms INTEGER)')
        db.executemany('INSERT INTO tracks VALUES (?,"Artist","Song",200000)', [('a',), ('b',)])
    monkeypatch.setattr(sys, 'argv', ['embed_mpd.py', '--catalog', str(catalog),
        '--out-dir', str(tmp_path / 'out'), '--preview-dir', str(tmp_path / 'clips')])
    monkeypatch.setattr(worker, 'require_persistent_out', lambda path, repo: path)
    def resolve(track, *args):
        return dict(id=1, isrc='X', artist={'name': 'Artist'}, title='Song', duration=200, preview='https://cdn/preview')
    monkeypatch.setattr(worker, 'resolve', resolve)
    def download(tracks, folder, **kwargs):
        tid = next(iter(tracks))
        p = folder / f'{tid}.mp3'; p.write_bytes(b'ID3test')
        return {tid: p}, []
    monkeypatch.setattr(worker, 'download_previews', download)
    class Model:
        def embed_audio(self, *args, **kwargs):
            return np.array([[1., 0.]])
    monkeypatch.setattr(worker, 'get_embedder', lambda *a, **k: Model())
    worker.main()
    output = tmp_path / 'out/clap/shard-0-of-1'
    assert np.load(output / 'chunk-000000.npz')['ids'].tolist() == ['a', 'b']
    provenance = json.loads((output / 'chunk-000000.json').read_text())
    assert provenance['complete']
    assert all(x['match_method'].startswith('metadata') for x in provenance['results'])
    assert not list((tmp_path / 'clips').iterdir())
    monkeypatch.setattr(worker, 'resolve', lambda *args: (_ for _ in ()).throw(AssertionError('unexpected retry')))
    worker.main()


def test_api_errors_are_retried_not_saved_as_no_match(monkeypatch):
    from unittest.mock import MagicMock
    import pytest
    session = MagicMock()
    session.get.return_value.json.return_value = {'error': {'code': 4}}
    monkeypatch.setattr(worker.time, 'sleep', lambda delay: None)
    with pytest.raises(worker.requests.RequestException):
        worker.resolve({'artist': 'Artist', 'title': 'Song'}, session, 0)
    assert session.get.call_count == 3
