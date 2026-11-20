"""Local SQLite state for a pilot that does not retain raw prompts or searches."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from secrets import choice, token_urlsafe
import sqlite3


ARMS = ("retrieval", "llm", "playlist_search")
SETUPS = ("paired", "manual")
MAX_PLAYLIST = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
    rehearsal INTEGER NOT NULL, setup TEXT NOT NULL, arms TEXT NOT NULL,
    rating INTEGER, comments TEXT
);
CREATE TABLE IF NOT EXISTS playlist (
    session_id TEXT NOT NULL REFERENCES sessions(id), recording TEXT NOT NULL,
    track TEXT NOT NULL, PRIMARY KEY (session_id, recording)
);
CREATE UNIQUE INDEX IF NOT EXISTS playlist_video ON playlist(session_id, json_extract(track, '$.video_id'));
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    started_at TEXT NOT NULL, mode TEXT NOT NULL, seed_count INTEGER NOT NULL,
    eligible_seed_count INTEGER, status TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_round ON rounds(session_id)
    WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS panels (
    round_id INTEGER NOT NULL REFERENCES rounds(id), position INTEGER NOT NULL,
    arm TEXT NOT NULL, elapsed_ms INTEGER NOT NULL, status TEXT NOT NULL,
    PRIMARY KEY (round_id, position)
);
CREATE TABLE IF NOT EXISTS offers (
    round_id INTEGER NOT NULL, position INTEGER NOT NULL, rank INTEGER NOT NULL,
    video_id TEXT NOT NULL, recording TEXT NOT NULL, track TEXT NOT NULL,
    decision TEXT, decided_at TEXT, play_clicks INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (round_id, position, rank),
    FOREIGN KEY (round_id, position) REFERENCES panels(round_id, position)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    round_id INTEGER NOT NULL REFERENCES rounds(id), rating INTEGER NOT NULL, saved_at TEXT NOT NULL
);
"""


class StudyConflict(Exception):
    """The requested change conflicts with the current session state."""


def now():
    return datetime.now(timezone.utc).isoformat()


def recording(track):
    return track.get("recording_key") or "yt:" + track["video_id"]


def as_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Study:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    def create(self, rehearsal, setup, arm=None):
        session_id = token_urlsafe(24)
        with self.connect(write=True) as db:
            if setup == "paired":
                # Balance the two baselines in blocks of two. Randomize panel position separately.
                counts = dict.fromkeys(ARMS[1:], 0)
                rows = db.execute(
                    "SELECT arms FROM sessions WHERE setup = 'paired' AND rehearsal = ?",
                    (int(rehearsal),),
                )
                for row in rows:
                    for candidate in json.loads(row["arms"]):
                        if candidate in counts:
                            counts[candidate] += 1
                baseline = choice([candidate for candidate, count in counts.items()
                                   if count == min(counts.values())])
                arms = list(choice((("retrieval", baseline), (baseline, "retrieval"))))
            else:
                arms = [arm]
            db.execute(
                "INSERT INTO sessions (id, started_at, rehearsal, setup, arms) VALUES (?,?,?,?,?)",
                (session_id, now(), int(rehearsal), setup, as_json(arms)),
            )
        return session_id

    def session(self, session_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def state(self, session_id):
        with self.connect() as db:
            seeds = self._playlist(db, session_id)
            round_row = db.execute(
                """SELECT id, mode FROM rounds WHERE session_id = ? AND status = 'complete'
                   ORDER BY id DESC LIMIT 1""", (session_id,),
            ).fetchone()
            if not round_row:
                return {"playlist": seeds, "round": None}
            round_id = round_row["id"]
            round_number = db.execute("SELECT count(*) FROM rounds WHERE session_id = ? AND status = 'complete'",
                                      (session_id,)).fetchone()[0]
            checkpoint = db.execute("SELECT rating FROM checkpoints WHERE session_id = ?", (session_id,)).fetchone()
            panels = []
            for panel in db.execute(
                "SELECT position, status FROM panels WHERE round_id = ? ORDER BY position", (round_id,),
            ):
                offers = list(db.execute(
                    """SELECT track, decision FROM offers
                       WHERE round_id = ? AND position = ? ORDER BY rank""",
                    (round_id, panel["position"]),
                ))
                panels.append({
                    **dict(panel),
                    "offers": [{**json.loads(row["track"]), "decision": row["decision"]}
                               for row in offers],
                })
        return {"playlist": seeds, "round": {**dict(round_row), "number": round_number, "panels": panels},
                "round_five_rating": checkpoint["rating"] if checkpoint else None}

    @staticmethod
    def _playlist(db, session_id):
        return [json.loads(row["track"]) for row in db.execute(
            "SELECT track FROM playlist WHERE session_id = ? ORDER BY rowid", (session_id,),
        )]

    @staticmethod
    def _modifiable(db, session_id):
        row = db.execute("SELECT finished_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None or row["finished_at"] is not None:
            raise StudyConflict("Start a new session to continue.")
        db.execute(
            """UPDATE rounds SET status = 'abandoned' WHERE session_id = ? AND status = 'pending'
               AND julianday(started_at) < julianday('now', '-10 minutes')""", (session_id,),
        )
        if db.execute("SELECT 1 FROM rounds WHERE session_id = ? AND status = 'pending'",
                      (session_id,)).fetchone():
            raise StudyConflict("Wait for the current recommendations to finish.")

    @staticmethod
    def _add(db, session_id, track):
        key = recording(track)
        if db.execute("""SELECT 1 FROM playlist WHERE session_id = ?
                         AND (recording = ? OR json_extract(track, '$.video_id') = ?)""",
                      (session_id, key, track["video_id"])).fetchone():
            return
        if db.execute("SELECT count(*) FROM playlist WHERE session_id = ?", (session_id,)).fetchone()[0] >= MAX_PLAYLIST:
            raise StudyConflict(f"The playlist can hold up to {MAX_PLAYLIST} songs.")
        db.execute("INSERT INTO playlist VALUES (?,?,?)", (session_id, key, as_json(track)))

    def edit_playlist(self, session_id, action, track):
        with self.connect(write=True) as db:
            self._modifiable(db, session_id)
            if action == "add":
                self._add(db, session_id, track)
            else:
                db.execute("DELETE FROM playlist WHERE session_id = ? AND recording = ?",
                           (session_id, recording(track)))

    def start_round(self, session_id, has_text):
        with self.connect(write=True) as db:
            self._modifiable(db, session_id)
            seeds = self._playlist(db, session_id)
            if not (has_text or seeds):
                raise StudyConflict("Enter a request or add a song first.")
            mode = "text_and_playlist" if has_text and seeds else "text_only" if has_text else "playlist_only"
            excluded_songs = db.execute(
                """SELECT DISTINCT offers.video_id, offers.recording FROM offers
                   JOIN rounds ON rounds.id = offers.round_id
                   WHERE rounds.session_id = ? AND offers.decision = 'reject'""", (session_id,),
            )
            exclusions = {(row["video_id"], row["recording"]) for row in excluded_songs}
            exclusions.update((track["video_id"], recording(track)) for track in seeds)
            round_id = db.execute(
                """INSERT INTO rounds (session_id, started_at, mode, seed_count, status)
                   VALUES (?,?,?,?,'pending')""", (session_id, now(), mode, len(seeds)),
            ).lastrowid
        return round_id, seeds, exclusions

    def finalize_round(self, round_id, eligible_seeds, panels):
        known_recordings = {track["video_id"]: recording(track) for panel in panels for track in panel["tracks"]
                            if not recording(track).startswith("yt:")}
        with self.connect(write=True) as db:
            updated = db.execute(
                """UPDATE rounds SET status = 'complete', eligible_seed_count = ?
                   WHERE id = ? AND status = 'pending'""", (eligible_seeds, round_id),
            )
            if not updated.rowcount:
                raise StudyConflict("That recommendation round has expired.")
            for position, panel in enumerate(panels):
                db.execute("INSERT INTO panels VALUES (?,?,?,?,?)",
                           (round_id, position, panel["arm"], panel["elapsed_ms"], panel["status"]))
                db.executemany(
                    """INSERT INTO offers (round_id, position, rank, video_id, recording, track)
                       VALUES (?,?,?,?,?,?)""",
                    [(round_id, position, rank, track["video_id"],
                      known_recordings.get(track["video_id"], recording(track)), as_json(track))
                     for rank, track in enumerate(panel["tracks"], 1)],
                )

    def action(self, session_id, round_id, position, video_id, action):
        with self.connect(write=True) as db:
            self._modifiable(db, session_id)
            row = db.execute(
                """SELECT offers.* FROM offers JOIN rounds ON rounds.id = offers.round_id
                   WHERE rounds.session_id = ? AND offers.round_id = ?
                     AND position = ? AND video_id = ?""",
                (session_id, round_id, position, video_id),
            ).fetchone()
            if row is None:
                raise StudyConflict("That recommendation is no longer available.")
            if action == "play":
                db.execute("UPDATE offers SET play_clicks = play_clicks + 1 WHERE round_id = ? AND position = ? AND rank = ?",
                           (round_id, position, row["rank"]))
                return
            if row["decision"] == action:
                return
            if row["decision"] is not None:
                raise StudyConflict("This song already has a decision.")
            if action == "keep":
                self._add(db, session_id, {**json.loads(row["track"]), "recording_key": row["recording"]})
            # A shared recording receives the same decision in both columns.
            db.execute("UPDATE offers SET decision = ?, decided_at = ? WHERE round_id = ? AND recording = ?",
                       (action, now(), round_id, row["recording"]))

    def finish(self, session_id, rating, comments):
        with self.connect(write=True) as db:
            self._modifiable(db, session_id)
            db.execute("UPDATE sessions SET finished_at = ?, rating = ?, comments = ? WHERE id = ?",
                       (now(), rating, comments or None, session_id))

    def save_checkpoint(self, session_id, round_id, rating):
        with self.connect(write=True) as db:
            self._modifiable(db, session_id)
            current = db.execute("""SELECT count(*) AS number, max(id) AS id FROM rounds
                                    WHERE session_id = ? AND status = 'complete'""", (session_id,)).fetchone()
            if current["number"] != 5 or current["id"] != round_id:
                raise StudyConflict("This optional rating is only available after the fifth round.")
            db.execute("INSERT INTO checkpoints VALUES (?,?,?,?) ON CONFLICT(session_id) DO NOTHING",
                       (session_id, round_id, rating, now()))
