"""Download track previews and embed them with one of the audio models.

    python spotify/scripts/embed.py --user kartik --model clap
    (normally one job per shard via spotify/scripts/babel_embed.sbatch)

Embeddings are written only under /data/user_data, outside the git repo; the
script refuses to start otherwise, so it runs on Babel compute nodes only.

Work proceeds in chunks - download a chunk, embed it, save - so a preempted
job loses at most one chunk and a rerun resumes where it stopped. Babel
preemption has GraceTime=0, so frequent saves are the checkpoint; there is
no chance to save on SIGTERM.

With --shard i/N a job only touches its slice of the tracks, writes its own
output file, and paces Deezer at 1/N of the budget: all cluster jobs leave
through a shared NAT pool, so they share one per-IP rate limit. Every run
logs its node to <out-dir>/manifest/, since the preview cache it builds lives
on that node's local /scratch.
"""

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "spotify" / "src"))

from embeddings import EMBEDDERS, get_embedder  # noqa: E402
from jobs import (  # noqa: E402
    DEFAULT_OUT_DIR,
    parse_shard,
    record,
    require_persistent_out,
    shard_of,
    shard_tag,
)
from previews import MIN_INTERVAL, PREVIEW_DIR, download_previews, track_isrcs  # noqa: E402
from users import user_arg  # noqa: E402


def load_existing(path):
    """Return {track_id: vector} already computed for this output file."""
    if not path.exists():
        return {}
    stored = np.load(path, allow_pickle=False)
    return dict(zip(stored["ids"].tolist(), stored["vectors"]))


def save(path, vectors_by_id):
    """Write atomically, so a kill mid-save cannot corrupt the checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = sorted(vectors_by_id)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, ids=np.array(ids), vectors=np.stack([vectors_by_id[i] for i in ids]))
    tmp.replace(path)


def main():
    parser = user_arg(__doc__)
    parser.add_argument("--model", required=True, choices=sorted(EMBEDDERS))
    parser.add_argument("--shard", default="0/1", help="i/N: process only shard i of N")
    parser.add_argument("--preview-dir", type=Path, default=PREVIEW_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="must resolve under /data/user_data, outside the repo")
    parser.add_argument("--chunk", type=int, default=256,
                        help="tracks per download+embed+save step")
    parser.add_argument("--limit", type=int, help="only process this many tracks")
    parser.add_argument("--device", help="torch device for clap/muq "
                                        "(default: cuda > mps > cpu)")
    args = parser.parse_args()

    args.out_dir = require_persistent_out(args.out_dir, REPO_ROOT)
    index, total = parse_shard(args.shard)
    tag = shard_tag(args.model, index, total)
    out_path = args.out_dir / args.model / f"shard-{index}-of-{total}.npz"
    log_path = args.out_dir / "manifest" / f"{tag}.jsonl"

    tracks = {tid: meta for tid, meta in sorted(track_isrcs(args.user).items())
              if shard_of(tid, total) == index}
    if args.limit:
        tracks = dict(list(tracks.items())[:args.limit])
    done = load_existing(out_path)
    todo = [tid for tid in tracks if tid not in done]

    start = record(log_path, event="start", model=args.model, shard=args.shard,
                   preview_dir=str(args.preview_dir.resolve()),
                   tracks=len(tracks), already_done=len(done))
    print(f"{tag} on {start['node']} (job {start['job_id']}): "
          f"{len(tracks)} tracks, {len(done)} done, {len(todo)} to go")

    embedder = get_embedder(args.model, device=args.device) if todo else None
    unavailable = 0
    for offset in range(0, len(todo), args.chunk):
        chunk = {tid: tracks[tid] for tid in todo[offset:offset + args.chunk]}
        clips, missing = download_previews(chunk, args.preview_dir,
                                           pause=MIN_INTERVAL * total)
        unavailable += len(missing)
        if clips:
            ids = sorted(clips)
            done.update(zip(ids, embedder.embed_audio([clips[i] for i in ids])))
            save(out_path, done)
        print(f"  {min(offset + args.chunk, len(todo))}/{len(todo)} "
              f"({len(done)} embedded, {unavailable} without audio)", flush=True)

    record(log_path, event="done", preview_dir=str(args.preview_dir.resolve()),
           embedded=len(done), unavailable=unavailable)
    print(f"wrote {len(done)} embeddings to {out_path}")


if __name__ == "__main__":
    main()
