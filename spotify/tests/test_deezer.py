import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import deezer


class FakeSession:
    def __init__(self, *bodies):
        self.bodies, self.calls = list(bodies), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        body = self.bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return SimpleNamespace(json=lambda: body, raise_for_status=lambda: None)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(deezer.time, 'sleep', lambda s: None)


def test_search_candidates_returns_data():
    session = FakeSession({'data': [{'id': 1}]})
    assert deezer.search_candidates(session, 'q') == [{'id': 1}]
    assert session.calls == [('https://api.deezer.com/search', {'q': 'q', 'limit': 25})]


def test_search_candidates_retries_errors_then_raises():
    session = FakeSession(requests.Timeout('t'), {'error': {'code': 4}}, {'data': []})
    assert deezer.search_candidates(session, 'q') == []
    session = FakeSession(*[{'error': {'code': 4}}] * 3)
    with pytest.raises(requests.RequestException, match='Deezer error'):
        deezer.search_candidates(session, 'q')


def test_fresh_preview_reads_track_endpoint():
    session = FakeSession({'id': 7, 'preview': 'https://cdn/new.mp3'}, {'id': 8, 'preview': ''})
    assert deezer.fresh_preview(session, 7) == 'https://cdn/new.mp3'
    assert deezer.fresh_preview(session, 8) is None
    assert session.calls[0][0] == 'https://api.deezer.com/track/7'
