import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mpd import (MATCH_POLICIES, build_catalog, canonical, choose_candidate,
                 choose_canonical, search_queries)


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


# v2 policy: Spotify and Deezer format the same versions differently. Cases are
# real MPD tracks the v1 policy rejected (see docs/mpd_embedding.md).

def song(artist='Artist', title='Song', duration_ms=200000):
    return dict(artist=artist, title=title, duration_ms=duration_ms)


@pytest.mark.parametrize('spotify, deezer', [
    ('Oblivion - Original Mix', 'Oblivion (Original Mix)'),
    ("De t'avoir aimée - Remastered 2014", "De t'avoir aimée (Remastered 2014)"),
    ('Te Amo Jesús', 'Te Amo, Jesús'),
    ('I Shot Mr Lee', 'I Shot Mr. Lee'),
    ('Plastic Hearts', 'Plastic Hearts (feat. Akeem Jahat)'),
    ('Heartstrings - Aashton & Swift Remix', 'Heartstrings (feat. Jeremy Glenn) (Aashton & Swift Remix)'),
    ("Rollin' & Tumblin/You Need Love", "Rollin' & Tumblin' - You Need Love"),
])
def test_canonical_equates_formatting_variants(spotify, deezer):
    assert canonical(spotify) == canonical(deezer)


@pytest.mark.parametrize('spotify, deezer', [
    ('Song', 'Song (Live)'),
    ('Song - Live', 'Song (Remastered)'),
    ('Song - Radio Edit', 'Song (Extended Mix)'),
    ('Song - Acoustic', 'Song'),
])
def test_canonical_keeps_version_markers(spotify, deezer):
    assert canonical(spotify) != canonical(deezer)


def test_canonical_does_not_split_hyphenated_words():
    assert canonical('Re-Up') == canonical('Re Up') != canonical('Re')


def test_canonical_match_accepts_v1_rejects():
    track = song(artist='Digital Punk', title='Oblivion - Original Mix', duration_ms=286000)
    match = {**candidate(), 'artist': {'name': 'Digital Punk'}, 'title': 'Oblivion (Original Mix)', 'duration': 286}
    assert choose_candidate(track, [match]) is None
    assert choose_canonical(track, [match])['id'] == 1


def test_canonical_match_tolerates_whole_second_rounding():
    assert choose_canonical(song(duration_ms=200000), [{**candidate(), 'duration': 203}])['id'] == 1
    assert choose_canonical(song(duration_ms=200000), [{**candidate(), 'duration': 204}]) is None


def test_canonical_match_still_rejects_other_artists_and_versions():
    track = song(artist='Lee Fields & The Expressions', title='I Still Got It')
    assert choose_canonical(track, [{**candidate(), 'artist': {'name': 'Lee Fields'}, 'title': 'I Still Got It'}]) is None
    assert choose_canonical(song(), [{**candidate(), 'title': 'Song (Live)'}]) is None
    for changes in ({'preview': ''}, {'readable': False}, {'isrc': None}):
        assert choose_canonical(song(), [{**candidate(), **changes}]) is None


def test_canonical_match_artist_punctuation_and_case():
    track = song(artist='T Bone Burnett')
    assert choose_canonical(track, [{**candidate(), 'artist': {'name': 'T-Bone Burnett'}}])['id'] == 1


def test_canonical_conflicting_recordings_are_ambiguous():
    assert choose_canonical(song(), [candidate(), {**candidate(), 'id': 2, 'isrc': 'OTHER'}]) is None


def test_canonical_prefers_closest_duration():
    near = {**candidate(), 'id': 2, 'duration': 200}
    assert choose_canonical(song(), [{**candidate(), 'duration': 202}, near])['id'] == 2


def test_search_queries_add_core_title_fallback():
    # Deezer free-text search returns nothing for 'Sid Le Rock Naked - DJ Koze Remix'.
    assert search_queries(song(artist='Sid Le Rock', title='Naked - DJ Koze Remix')) == [
        'Sid Le Rock Naked - DJ Koze Remix', 'Sid Le Rock Naked']
    assert search_queries(song(title='Graveyard (feat. YungGungHo)')) == [
        'Artist Graveyard (feat. YungGungHo)', 'Artist Graveyard']


def test_search_queries_single_query_when_no_suffix():
    assert search_queries(song()) == ['Artist Song']
    assert search_queries(song(title='(Untitled)')) == ['Artist (Untitled)']


def test_match_policies_are_named():
    assert MATCH_POLICIES['full-title-artist-duration2s-v1'] is choose_candidate
    assert MATCH_POLICIES['canonical-title-artist-duration3s-v2'] is choose_canonical
