"""Streaming MPD catalog construction and conservative preview matching."""
import json
import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path


def build_catalog(archive, database, expected_slices=1000):
    """Read one ZIP slice at a time; transactions make ingestion resumable."""
    with zipfile.ZipFile(archive) as z:
        names = sorted(n for n in z.namelist() if re.search(r'mpd\.slice\.\d+-\d+\.json$', n))
        if len(names) != expected_slices:
            raise ValueError(f'expected {expected_slices} slices, found {len(names)}')
        if expected_slices == 1000:
            expected = {f'mpd.slice.{i}-{i+999}.json' for i in range(0, 1000000, 1000)}
            if {Path(n).name for n in names} != expected:
                raise ValueError('archive has incorrect slice ranges')
        with sqlite3.connect(database) as db:
            db.execute("PRAGMA cache_size=-1048576")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tracks (
                    id TEXT PRIMARY KEY, artist TEXT, title TEXT, album TEXT,
                    duration_ms INTEGER, occurrences INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS slices (
                    name TEXT PRIMARY KEY, crc INTEGER, playlists INTEGER, entries INTEGER);
            ''')
            done = dict(db.execute('SELECT name, crc FROM slices'))
            for name in names:
                crc = z.getinfo(name).CRC
                if name in done:
                    if done[name] != crc:
                        raise ValueError(f'archive changed: {name}')
                    continue
                with z.open(name) as f:
                    playlists = json.load(f)['playlists']
                unique = {}
                entries = 0
                for p in playlists:
                    for t in p['tracks']:
                        tid = t['track_uri'].removeprefix('spotify:track:')
                        entries += 1
                        if tid in unique:
                            unique[tid][-1] += 1
                        else:
                            unique[tid] = [tid, t['artist_name'], t['track_name'],
                                           t['album_name'], t['duration_ms'], 1]
                rows = [unique[tid] for tid in sorted(unique)]
                with db:
                    db.executemany('''INSERT INTO tracks VALUES (?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET occurrences=occurrences+excluded.occurrences''', rows)
                    db.execute('INSERT INTO slices VALUES (?,?,?,?)',
                               (name, crc, len(playlists), entries))
                print(f'ingested {name}', flush=True)
            summary = dict(zip(('slices', 'playlists', 'entries'), db.execute(
                'SELECT count(*), sum(playlists), sum(entries) FROM slices').fetchone()))
            summary['tracks'] = db.execute('SELECT count(*) FROM tracks').fetchone()[0]
            return summary


def normalise(text):
    """Keep version markers; only normalize Unicode, casing and whitespace."""
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def choose_candidate(track, candidates):
    """Accept matching full artist/title and duration within two seconds.

    This is metadata matching, not a verified Spotify-to-ISRC join. Conflicting
    ISRCs are ambiguous; do not silently choose a recording.
    """
    matches = [c for c in candidates if c.get('readable') and c.get('preview')
               and c.get('isrc')
               and normalise(c.get('artist', {}).get('name', '')) == normalise(track['artist'])
               and normalise(c.get('title', '')) == normalise(track['title'])
               and abs(c.get('duration', 0) * 1000 - track['duration_ms']) <= 2000]
    if not matches or len({c['isrc'] for c in matches}) != 1:
        return None
    return min(matches, key=lambda c: (abs(c['duration']*1000-track['duration_ms']), c['id']))


_FEAT = r'(?:feat|ft|featuring)\.?'


def canonical(text):
    """Equate Spotify/Deezer formatting while keeping version markers.

    'X - Remastered 2014' == 'X (Remastered 2014)'; feat. credits and
    punctuation are ignored; 'X (Live)' still differs from 'X'.
    """
    s = normalise(text)
    s = re.sub(r'\s+-\s+(.+)$', r' (\1)', s)
    s = re.sub(rf'[\(\[]\s*{_FEAT}\s[^\)\]]*[\)\]]', ' ', s)
    s = re.sub(rf'\s{_FEAT}\s[^\(\[]*', ' ', s)
    return ' '.join(re.sub(r'[^\w\s]|_', ' ', s).split())


def choose_canonical(track, candidates, tolerance_ms=3000):
    """v2 policy: canonical artist/title, duration within Deezer's whole-second rounding.

    Conflicting ISRCs remain ambiguous; the closest duration wins otherwise.
    """
    artist, title = canonical(track['artist']), canonical(track['title'])
    matches = [c for c in candidates if c.get('readable') and c.get('preview') and c.get('isrc')
               and canonical(c.get('artist', {}).get('name', '')) == artist
               and canonical(c.get('title', '')) == title
               and abs(c.get('duration', 0) * 1000 - track['duration_ms']) <= tolerance_ms]
    if not matches or len({c['isrc'] for c in matches}) != 1:
        return None
    return min(matches, key=lambda c: (abs(c['duration']*1000-track['duration_ms']), c['id']))


def search_queries(track):
    """Deezer free-text search fails on version suffixes; add a core-title fallback."""
    title = track['title']
    core = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', re.sub(r'\s+-\s+.*$', '', title)).strip()
    queries = [f'{track["artist"]} {title}']
    if core and core != title:
        queries.append(f'{track["artist"]} {core}')
    return queries


MATCH_POLICIES = {
    'full-title-artist-duration2s-v1': choose_candidate,
    'canonical-title-artist-duration3s-v2': choose_canonical,
}
