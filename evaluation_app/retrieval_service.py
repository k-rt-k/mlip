"""CPU FAISS worker. Run the CLAP encoder in a separate environment."""

import argparse
from contextlib import closing
from functools import lru_cache
import os
from pathlib import Path
import re
import sqlite3
import unicodedata

import faiss
from flask import Flask, abort, request
import numpy as np
import requests

from retrieval import RetrievalIndex
from retrieval.catalog import normalized_vectors


def match_key(value):
    """Normalize spelling and punctuation while preserving recording qualifiers."""
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[^\W_]+", value))


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def build_lookup(source, output):
    """Index title and artist keys from the audited MPD metadata snapshot."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with closing(readonly(source)) as source_db, closing(sqlite3.connect(temporary)) as db, db:
            db.execute("""CREATE TABLE tracks (
                id TEXT PRIMARY KEY, title TEXT, artist TEXT, duration INTEGER, isrc TEXT,
                title_key TEXT, artist_key TEXT)""")
            rows = source_db.execute("SELECT id, title, artist, duration, isrc FROM tracks")
            db.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?)",
                           ((*row, match_key(row["title"]), match_key(row["artist"])) for row in rows))
            db.execute("CREATE INDEX track_keys ON tracks(title_key, artist_key)")
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


class Catalog:
    def __init__(self, index, lookup, seed_files=()):
        self.index = index
        self.rows = {song_id: row for row, song_id in enumerate(index.ids)}
        self.lookup = lookup
        self.direct_seeds = {}
        for path in seed_files:
            with np.load(path, allow_pickle=False) as data:
                vectors = normalized_vectors(data["vectors"], dimension=index.index.d)
                for track_id, vector in zip(data["ids"], vectors, strict=True):
                    self.direct_seeds[str(track_id)] = vector
        with closing(readonly(lookup)) as db:
            if db.execute("SELECT count(*) FROM tracks").fetchone()[0] != len(self.rows):
                raise ValueError("Track lookup and index have different row counts.")
            if any(row[0] not in self.rows for row in db.execute("SELECT id FROM tracks")):
                raise ValueError("Track lookup and index have different track IDs.")

    @lru_cache(maxsize=16384)
    def match(self, title, artists, duration):
        title = match_key(title)
        if not title:
            return None
        matches = {}
        with closing(readonly(self.lookup)) as db:
            for artist in map(match_key, artists):
                if not artist:
                    continue
                for row in db.execute("SELECT id, duration, isrc FROM tracks WHERE title_key = ? AND artist_key = ?",
                                      (title, artist)):
                    if duration and row["duration"] and abs(duration - row["duration"]) > 3:
                        continue
                    key = "isrc:" + row["isrc"] if row["isrc"] else "mpd:" + row["id"]
                    matches.setdefault(key, row["id"])
                    if len(matches) > 1:
                        return None
        return next(iter(matches.items()), None)

    def coverage(self, tracks):
        result = {}
        for track in tracks:
            video_id = track["video_id"]
            match = self.match(track["title"], tuple(track["artists"]), track.get("duration_seconds"))
            result[video_id] = {
                "seed_eligible": video_id in self.direct_seeds or match is not None,
                "recording_key": match[0] if match else "yt:" + video_id,
                "catalog_id": match[1] if match else None,
            }
        return result

    def shortlist(self, query, seeds, exclusions, candidate_k, output_k):
        coverage = self.coverage(seeds)
        vectors = []
        for video_id, match in coverage.items():
            if video_id in self.direct_seeds:
                vectors.append(self.direct_seeds[video_id])
            elif match["catalog_id"]:
                vectors.append(self.index.index.reconstruct(self.rows[match["catalog_id"]]))
        centroid = None
        if vectors:
            mean = np.mean(vectors, axis=0)
            if np.linalg.norm(mean) > 0:
                centroid = normalized_vectors(mean.reshape(1, -1))[0]
        if query is None and centroid is None:
            return []

        if query is not None:
            query = normalized_vectors(np.asarray(query).reshape(1, -1), dimension=self.index.index.d)[0]
        result = self.index.search(np.asarray([query if query is not None else centroid]),
                                   min(candidate_k, len(self.rows)))
        rows = [int(row) for row in result.rows[0] if row >= 0]
        if not rows:
            return []
        candidate_vectors = np.stack([self.index.index.reconstruct(row) for row in rows])
        if query is not None and centroid is not None:
            scores = 0.8 * (candidate_vectors @ query) + 0.2 * (candidate_vectors @ centroid)
        else:
            scores = candidate_vectors @ (query if query is not None else centroid)
        order = np.lexsort((rows, -scores))
        ids = [self.index.ids[rows[i]] for i in order]
        with closing(readonly(self.lookup)) as db:
            placeholders = ",".join("?" for _ in ids)
            metadata = {row["id"]: row for row in db.execute(
                f"SELECT id, title, artist, duration, isrc FROM tracks WHERE id IN ({placeholders})", ids)}
        tracks = []
        excluded = set(exclusions) | {match["recording_key"] for match in coverage.values()}
        for song_id in ids:
            row = metadata[song_id]
            key = "isrc:" + row["isrc"] if row["isrc"] else "mpd:" + song_id
            if key in excluded or not row["title"] or not row["artist"]:
                continue
            tracks.append({"title": row["title"], "artist": row["artist"], "duration_seconds": row["duration"],
                           "recording_key": key})
            excluded.add(key)
            if len(tracks) == output_k:
                break
        return tracks


def make_worker(catalog, encoder_url, threads, candidate_k=100, output_k=15):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 128 * 1024

    @app.get("/health")
    def health():
        try:
            response = requests.get(encoder_url + "/health", timeout=2)
            response.raise_for_status()
        except requests.RequestException:
            return {"ready": False}, 503
        return {"ready": True, "tracks": len(catalog.rows), "method": catalog.index.config.method}

    @app.post("/coverage")
    def coverage():
        return catalog.coverage(request.get_json()["tracks"])

    @app.post("/recommend")
    def recommend():
        data = request.get_json()
        query = None
        if data["prompt"]:
            try:
                response = requests.post(encoder_url + "/embed", json={"text": data["prompt"]}, timeout=30)
                response.raise_for_status()
                query = response.json()["vector"]
            except (requests.RequestException, KeyError, ValueError):
                abort(503)
        faiss.omp_set_num_threads(threads)
        return {"tracks": catalog.shortlist(query, data["seeds"], data["exclusions"], candidate_k, output_k)}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-lookup", type=Path, metavar="TRACKS_SQLITE")
    parser.add_argument("--lookup", type=Path, required=True)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--seed-embeddings", type=Path, action="append", default=[])
    parser.add_argument("--encoder-url", default="http://127.0.0.1:8062")
    parser.add_argument("--port", type=int, default=8061)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.build_lookup:
        build_lookup(args.build_lookup, args.lookup)
        return
    if args.index is None or args.threads < 1:
        parser.error("Serving requires an index and a positive thread count.")
    index = RetrievalIndex.load(args.index)
    if index.config.method == "hnsw":
        index.set_search_parameters(ef_search=512)
    elif index.config.method != "exact":
        parser.error("Serving requires an exact or HNSWFlat index.")
    catalog = Catalog(index, args.lookup, args.seed_embeddings)
    make_worker(catalog, args.encoder_url.rstrip("/"), args.threads).run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
