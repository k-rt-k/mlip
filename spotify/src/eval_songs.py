"""Map YouTube Music eval songs (video IDs) to Deezer recordings with ISRCs and previews.

YouTube exposes no ISRC, so matching is metadata-only: the v2 canonical policy from
`mpd.py` on a cleaned video title. Official audio (ATV) durations are exact; music
videos carry intros/outros, so other video types get a looser duration bound.
"""
import json
import math
import re

from mpd import choose_canonical, search_queries

SOURCES = (('partial-seed', 'seed_tracks'), ('partial-heldout', 'held_out_tracks'))
# Upload decoration, never part of the recording's title. Version markers (Remaster, Live) are kept.
_DECOR = re.compile(r'\s*[\(\[][^\)\]]*\b(official|lyrics?|visuali[sz]er|hd|hq|4k|m/?v)\b[^\)\]]*[\)\]]', re.I)


def collect_eval_songs(partial_path, references_path):
    """{video_id: song} over partial seeds/hidden tracks and prompt reference pools.

    Each song keeps its first-seen metadata plus the sorted `sources` it appears in.
    """
    songs = {}

    def add(track, source):
        song = songs.setdefault(track['video_id'], {**track, 'sources': []})
        if source not in song['sources']:
            song['sources'] = sorted(song['sources'] + [source])

    for example in json.loads(partial_path.read_text())['examples']:
        for source, key in SOURCES:
            for track in example[key]:
                add(track, source)
    for prompt in json.loads(references_path.read_text())['prompts']:
        for playlist in prompt['playlists']:
            for track in playlist['tracks']:
                add(track, 'prompt-reference')
    return songs


def clean_youtube_title(title, artists):
    """Drop '(Official Video)'-style decoration and a leading 'Artist - ' prefix."""
    cleaned = _DECOR.sub('', title).strip()
    for artist in artists:
        prefix = re.match(rf'\s*{re.escape(artist)}\s*[-–:|]\s*(.+)$', cleaned, re.I)
        if prefix:
            return prefix.group(1).strip()
    return cleaned


def tolerance_seconds(song):
    if not song.get('duration_seconds'):
        return math.inf  # unknown length: rely on artist/title/ISRC agreement
    return 3 if song.get('video_type') == 'MUSIC_VIDEO_TYPE_ATV' else 10


def resolve_song(song, search):
    """Return a match record for one song; `search(query) -> Deezer candidates`.

    Tries the first two credited artists, each with `search_queries` fallbacks.
    Network errors propagate so callers can record a retryable failure.
    """
    artists = song.get('artists') or ['']
    tolerance = tolerance_seconds(song)
    method = 'youtube-canonical-v2-duration' + ('NA' if math.isinf(tolerance) else f'{tolerance}s')
    title = clean_youtube_title(song['title'], artists)
    for artist in artists[:2]:
        track = dict(artist=artist, title=title, duration_ms=(song.get('duration_seconds') or 0) * 1000)
        for query in search_queries(track):
            match = choose_canonical(track, search(query), tolerance_ms=tolerance * 1000)
            if match:
                return dict(video_id=song['video_id'], status='matched', deezer_id=match['id'],
                            isrc=match['isrc'], artist=match['artist']['name'], title=match['title'],
                            duration=match['duration'], preview=match['preview'],
                            match_method=method, query=query)
    return dict(video_id=song['video_id'], status='no_match', match_method=method)
