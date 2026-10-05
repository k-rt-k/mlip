import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mpd import build_catalog, choose_candidate


def test_catalog_deduplicates_and_resumes(tmp_path):
    archive = tmp_path / 'mpd.zip'
    track = dict(track_uri='spotify:track:abc', artist_name='Artist', track_name='Song',
                 album_name='Album', duration_ms=200000)
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('data/mpd.slice.0-999.json', json.dumps({'playlists': [
            {'pid': 0, 'tracks': [track, track]}, {'pid': 1, 'tracks': [track]}]}))
    db = tmp_path / 'catalog.sqlite'
    build_catalog(archive, db, expected_slices=1)
    build_catalog(archive, db, expected_slices=1)
    with sqlite3.connect(db) as con:
        assert con.execute('select count(*), sum(occurrences) from tracks').fetchone() == (1, 3)
        assert con.execute('select sum(playlists), sum(entries) from slices').fetchone() == (2, 3)


def test_incomplete_archive_rejected(tmp_path):
    archive = tmp_path / 'mpd.zip'
    with zipfile.ZipFile(archive, 'w'):
        pass
    with pytest.raises(ValueError, match='slices'):
        build_catalog(archive, tmp_path / 'out.sqlite')


def candidate(**kw):
    return dict(id=1, artist={'name': 'Artist'}, title='Song', duration=200,
                readable=True, preview='https://cdn/preview', isrc='ISRC1', **kw)


def test_match_requires_artist_full_title_and_duration():
    track = dict(artist='Artist', title='Song', duration_ms=200000)
    assert choose_candidate(track, [candidate()])['id'] == 1
    for changes in ({'artist': {'name': 'Cover Artist'}}, {'title': 'Song (Live)'},
                    {'duration': 210}, {'preview': ''}, {'readable': False}):
        assert choose_candidate(track, [{**candidate(), **changes}]) is None


def test_conflicting_recordings_are_ambiguous():
    track = dict(artist='Artist', title='Song', duration_ms=200000)
    assert choose_candidate(track, [candidate(), {**candidate(), 'id': 2, 'isrc': 'OTHER'}]) is None
