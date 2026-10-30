from baselines.playlist_search import rank_songs, select_playlists


def test_reference_exclusion_and_deduplication_precede_playlist_limit():
    results = [
        {"browseId": "VLreference"},
        {"browseId": "VLfirst"},
        {"playlistId": "first"},
        {"playlistId": "second"},
        {"playlistId": "third"},
    ]
    assert select_playlists(results, {"reference"}, 2) == ["first", "second"]


def test_song_support_counts_playlists_once_and_breaks_ties_by_video_id():
    playlists = [
        [{"video_id": "b"}, {"video_id": "a"}, {"video_id": "a"}],
        [{"video_id": "c"}, {"video_id": "a"}],
    ]
    assert rank_songs(playlists, 3) == [("a", 2), ("b", 1), ("c", 1)]
    assert rank_songs(list(reversed(playlists)), 2) == [("a", 2), ("b", 1)]
    assert rank_songs([], 5) == []
