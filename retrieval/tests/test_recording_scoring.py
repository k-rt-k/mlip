"""Recording joins must not turn missing metadata or duplicate uploads into hits."""

import pytest

from evaluation.recordings import recording_key, score_recordings


def test_recording_identity_uses_isrc_and_isolates_unknown_ids():
    assert recording_key({'isrc': 'us-abc-12-12345'}, 'yt:a') == 'isrc:USABC1212345'
    assert recording_key({'isrc': 'bad'}, 'yt:a') == 'yt:a'
    assert recording_key({}, 'yt:a') != recording_key({}, 'mpd:a')


def test_duplicate_recordings_cannot_earn_multiple_hits():
    result = score_recordings(['a', 'a', 'b', 'c', 'd', 'e'], ['a', 'a', 'z'])
    assert result['precision@5'] == pytest.approx(.2)
    assert result['recall@5'] == pytest.approx(.5)
    assert result['ndcg@5'] <= 1
    assert 'r_precision' not in result  # truncated retrieval does not establish R-precision


def test_short_outputs_keep_missing_places_as_misses():
    result = score_recordings(['a'], ['a'], k=(1, 5))
    assert result['precision@1'] == 1
    assert result['precision@5'] == pytest.approx(.2)
    assert score_recordings([], ['a'])['hit_rate@5'] == 0
