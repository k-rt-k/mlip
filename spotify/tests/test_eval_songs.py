import json
import sys
from pathlib import Path

import pytest
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from eval_songs import clean_youtube_title, collect_eval_songs, resolve_song


def yt(video_id='v1', title='Song', artists=('Artist',), seconds=200, kind='ATV'):
    return dict(video_id=video_id, title=title, artists=list(artists), duration_seconds=seconds,
                video_type=f'MUSIC_VIDEO_TYPE_{kind}')


def deezer(**kw):
    base = dict(id=7, artist={'name': 'Artist'}, title='Song', duration=200, readable=True,
                preview='https://cdn/p.mp3', isrc='ISRC1')
    return {**base, **kw}


def test_collect_merges_sources_and_dedupes(tmp_path):
    partial = tmp_path / 'dataset.json'
    partial.write_text(json.dumps({'examples': [
        {'seed_tracks': [yt('a')], 'held_out_tracks': [yt('b')]},
        {'seed_tracks': [yt('b')], 'held_out_tracks': []}]}))
    refs = tmp_path / 'reference_pools.json'
    refs.write_text(json.dumps({'prompts': [{'playlists': [{'tracks': [yt('a'), yt('c')]}]}]}))
    songs = collect_eval_songs(partial, refs)
    assert sorted(songs) == ['a', 'b', 'c']
    assert songs['a']['sources'] == ['partial-seed', 'prompt-reference']
    assert songs['b']['sources'] == ['partial-heldout', 'partial-seed']


@pytest.mark.parametrize('title, artists, expected', [
    ('Gives You Hell (Official Music Video)', ['The All-American Rejects'], 'Gives You Hell'),
    ('Lord Huron - She Lit a Fire (Official Music Video)', ['Lord Huron'], 'She Lit a Fire'),
    ('Kids (Official HD Video)', ['MGMT'], 'Kids'),
    ("Why Can't You (Lyric Video)", ['Bryant Barnes'], "Why Can't You"),
    ('The Chain (2004 Remaster)', ['Fleetwood Mac'], 'The Chain (2004 Remaster)'),  # versions kept
    ('Into You (feat. Tamia)', ['Fabolous'], 'Into You (feat. Tamia)'),
    ('Songs About You', ['Artist'], 'Songs About You'),  # artist prefix needs a separator
])
def test_clean_youtube_title(title, artists, expected):
    assert clean_youtube_title(title, artists) == expected


def test_resolve_matches_cleaned_title_and_records_evidence():
    queries = []
    def search(q):
        queries.append(q)
        return [deezer(title='She Lit a Fire', artist={'name': 'Lord Huron'}, duration=300)]
    rec = resolve_song(yt(title='Lord Huron - She Lit a Fire (Official Music Video)', artists=['Lord Huron'],
                          seconds=307, kind='OMV'), search)
    assert rec['status'] == 'matched' and rec['isrc'] == 'ISRC1' and rec['deezer_id'] == 7
    assert rec['preview'] == 'https://cdn/p.mp3' and rec['query'] == queries[-1]
    assert rec['match_method'] == 'youtube-canonical-v2-duration10s'


def test_official_audio_uses_tight_duration():
    far = lambda q: [deezer(duration=206)]
    assert resolve_song(yt(seconds=200, kind='ATV'), far)['status'] == 'no_match'
    assert resolve_song(yt(seconds=200, kind='OMV'), far)['status'] == 'matched'


def test_resolve_tries_second_artist_and_core_title():
    seen = []
    def search(q):
        seen.append(q)
        return [deezer(artist={'name': 'Udit Narayan'}, title='Yun Hi Chala Chal')] if q == 'Udit Narayan Yun Hi Chala Chal' else []
    rec = resolve_song(yt(title='Yun Hi Chala Chal', artists=['Hariharan', 'Udit Narayan']), search)
    assert rec['status'] == 'matched' and seen == ['Hariharan Yun Hi Chala Chal', 'Udit Narayan Yun Hi Chala Chal']


def test_no_match_and_errors():
    assert resolve_song(yt(), lambda q: [])['status'] == 'no_match'
    assert resolve_song(yt(), lambda q: [deezer(), deezer(id=8, isrc='OTHER')])['status'] == 'no_match'
    def boom(q):
        raise requests.ConnectionError('down')
    with pytest.raises(requests.RequestException):
        resolve_song(yt(), boom)
