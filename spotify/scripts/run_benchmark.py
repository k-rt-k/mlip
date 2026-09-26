"""Score our playlist recommenders against Spotify's own suggestions.

In the Spotify app, for each playlist you want to test:
  1. copy it into your library as "seed: <name>"
     (desktop: Ctrl/Cmd+A -> Add to Playlist -> New Playlist)
  2. add the songs Spotify recommends under that copy to "recs: <name>"
     (optional; without it we still produce recommendations, just no score)
Then:
    python spotify/scripts/run_benchmark.py --user kartik [--top-n 50]

Writes data/spotify/<user>/benchmark.json (the captured playlists) and
benchmark_results.json. Last.fm lookups are cached in
data/spotify/lastfm_similar.json, shared across users and runs.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auth import get_spotify  # noqa: E402
from benchmark import CachedSimilar, evaluate, pair_playlists, recommend_similar  # noqa: E402
from client import SpotifyClient, unwrap_item  # noqa: E402
from enrich import LastFM  # noqa: E402
from users import DATA_ROOT, data_dir, user_arg  # noqa: E402

SIMILAR_CACHE = DATA_ROOT / "lastfm_similar.json"

# name -> exclude_seed_artists. Spotify's own list often repeats seed artists,
# so the variant that keeps them is the fair comparison; the other is closer
# to what a "discover something new" feature would want.
VARIANTS = {"lastfm": False, "lastfm-new-artists": True}


def read_tracks(client, playlist_id):
    """[(artist, title, spotify_id)] for a playlist the user can read."""
    tracks = []
    for entry in client.playlist_tracks(playlist_id):
        t = unwrap_item(entry)
        if t and t.get("id") and t.get("artists"):
            tracks.append((t["artists"][0]["name"], t["name"], t["id"]))
    return tracks


def main():
    parser = user_arg(__doc__)
    parser.add_argument("--top-n", type=int, default=50,
                        help="recommendations to generate per playlist")
    args = parser.parse_args()

    client = SpotifyClient(get_spotify(args.user))
    me = client.profile()["id"]
    readable = [p for p in client.playlists()
                if p["owner"]["id"] == me or p.get("collaborative")]
    pairs = pair_playlists(readable)
    if not pairs:
        sys.exit('no "seed: <name>" playlists found - see this script\'s '
                 "docstring for how to capture them")

    bench = {name: {"seed": read_tracks(client, ids["seed"]),
                    "recs": read_tracks(client, ids["recs"]) if ids["recs"] else []}
             for name, ids in pairs.items()}
    out_dir = data_dir(args.user)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.json").write_text(json.dumps(bench, indent=1))

    similar = CachedSimilar(LastFM().similar_tracks, SIMILAR_CACHE)
    results = {}
    for name, captured in bench.items():
        seeds = [(a, t) for a, t, _ in captured["seed"]]
        reference = [(a, t) for a, t, _ in captured["recs"]]
        results[name] = {}
        for variant, exclude in VARIANTS.items():
            recommended = recommend_similar(seeds, similar, top_n=args.top_n,
                                            exclude_seed_artists=exclude)
            row = {"recommended": recommended}
            if reference:
                row["metrics"] = evaluate(recommended, reference)
            results[name][variant] = row
        similar.save()  # checkpoint after each playlist
    (out_dir / "benchmark_results.json").write_text(json.dumps(results, indent=1))

    print(f"{'playlist':24} {'seed':>4} {'spotify':>7}  "
          + "  ".join(f"{v:>26}" for v in VARIANTS))
    scored = {v: [] for v in VARIANTS}
    for name, rows in results.items():
        cells = []
        for variant in VARIANTS:
            m = rows[variant].get("metrics")
            if m:
                scored[variant].append(m)
                cells.append(f"hits {m['hits']:>2}  recall {m['recall']:.0%}  "
                             f"artists {m['artist_recall']:.0%}")
            else:
                cells.append(f"{'(no recs: playlist)':>26}")
        print(f"{name[:24]:24} {len(bench[name]['seed']):>4} "
              f"{len(bench[name]['recs']):>7}  " + "  ".join(f"{c:>26}" for c in cells))
    for variant, ms in scored.items():
        if ms:
            mean = lambda k: sum(m[k] for m in ms) / len(ms)  # noqa: E731
            print(f"mean over {len(ms)} scored ({variant}): recall {mean('recall'):.1%}, "
                  f"artist recall {mean('artist_recall'):.1%}")
    print(f"\nsaved {out_dir / 'benchmark.json'} and benchmark_results.json")


if __name__ == "__main__":
    main()
