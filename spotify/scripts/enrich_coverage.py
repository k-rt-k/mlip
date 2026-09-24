"""EDA step 4b: live-API hit-rate over a sample of our pulled tracks.

Samples tracks from a user's inventory cache (seeded, reproducible), enriches
each via GetSongBPM + Last.fm, and reports per-field coverage. Results go to
the GLOBAL cache data/spotify/enrich_sample.json — features are per-track, not
per-user, so overlapping tracks across users are fetched once.

    ~/mamba/envs/claude/bin/python spotify/scripts/enrich_coverage.py --user <slug> [n|all]

Pass "all" to enrich the user's entire pulled history (multi-hour;
checkpoints every 25 tracks, so it is safe to kill and resume).
"""

import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "spotify" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import unwrap_item  # noqa: E402
from enrich import GetSongBPM, LastFM, enrich_track  # noqa: E402
from inventory import TIME_RANGES  # noqa: E402
from users import DATA_ROOT, data_dir, user_arg  # noqa: E402

SAMPLE_FILE = DATA_ROOT / "enrich_sample.json"


def all_tracks(user):
    """id -> (primary artist, title) across every cached collection of `user`."""
    src = data_dir(user)
    collections = [f"top_tracks_{tr}" for tr in TIME_RANGES]
    collections += ["saved_tracks", "recently_played"]
    entries = []
    for name in collections:
        entries += json.loads((src / f"{name}.json").read_text())
    entries += [e for v in json.loads((src / "playlist_tracks.json").read_text()).values()
                for e in v]
    tracks = {}
    for entry in entries:
        t = unwrap_item(entry)
        if t and t.get("id") and t.get("artists"):
            tracks[t["id"]] = (t["artists"][0]["name"], t["name"])
    return tracks


def needs_work(done, tid):
    """full: not enriched yet; info: enriched before listeners/playcount existed."""
    if tid not in done:
        return "full"
    return "info" if "listeners" not in done[tid] else None


def main():
    parser = user_arg(__doc__)
    parser.add_argument("n", nargs="?", default="100", help="sample size, or 'all'")
    args = parser.parse_args()
    tracks = all_tracks(args.user)
    done = json.loads(SAMPLE_FILE.read_text()) if SAMPLE_FILE.exists() else {}
    if args.n == "all":
        sample = sorted(tracks)
    else:
        sample = random.Random(718).sample(sorted(tracks), min(int(args.n), len(tracks)))

    gsb, lfm = GetSongBPM(), LastFM()
    consecutive_errors = 0
    for i, tid in enumerate(sample):
        work = needs_work(done, tid)
        if not work:
            continue
        artist, title = tracks[tid]
        try:
            if work == "full":
                done[tid] = enrich_track(artist, title, gsb=gsb, lastfm=lfm)
            else:  # cheap Last.fm-only patch for pre-existing rows
                info = lfm.track_info(artist, title)
                done[tid]["listeners"] = int(info["listeners"]) if info else None
                done[tid]["playcount"] = int(info.get("playcount", 0)) if info else None
            consecutive_errors = 0
        except Exception as e:  # skip flaky tracks; bail if API looks down
            print(f"error on {artist} - {title}: {e}", file=sys.stderr)
            consecutive_errors += 1
            if consecutive_errors >= 5:
                print("5 consecutive errors — aborting run", file=sys.stderr)
                break
        if (i + 1) % 25 == 0:
            SAMPLE_FILE.write_text(json.dumps(done, indent=1))
            print(f"...{i + 1}/{len(sample)}", flush=True)
    SAMPLE_FILE.write_text(json.dumps(done, indent=1))

    rows = [done[t] for t in sample if t in done]
    if not rows:
        return
    print(f"\nenriched {len(rows)}/{len(tracks)} tracks")
    for field in ("tempo", "key", "danceability", "genres", "tags", "listeners"):
        hits = sum(1 for r in rows if r.get(field))
        print(f"{field:13}: {hits:4}/{len(rows)} ({hits / len(rows):.0%})")


if __name__ == "__main__":
    main()
