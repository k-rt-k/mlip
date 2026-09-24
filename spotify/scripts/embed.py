"""Download track previews and embed them with one of the audio models.

Previews come from Deezer (keyed by ISRC) and are shared across users;
embeddings are per-model and also shared, since both are per-track.

    python spotify/scripts/embed.py --user <slug> --model clap [--limit N]

Resumable: tracks already present in the model's .npz are skipped.
"""

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "spotify" / "src"))

from embeddings import EMBEDDERS, get_embedder  # noqa: E402
from previews import PREVIEW_DIR, download_previews, track_isrcs  # noqa: E402
from users import DATA_ROOT, user_arg  # noqa: E402

EMBED_DIR = DATA_ROOT / "embeddings"


def load_existing(path):
    """Return {track_id: vector} already computed for this model."""
    if not path.exists():
        return {}
    stored = np.load(path, allow_pickle=False)
    return dict(zip(stored["ids"].tolist(), stored["vectors"]))


def save(path, vectors_by_id):
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = sorted(vectors_by_id)
    np.savez(path, ids=np.array(ids),
             vectors=np.stack([vectors_by_id[i] for i in ids]))


def main():
    parser = user_arg(__doc__)
    parser.add_argument("--model", required=True, choices=sorted(EMBEDDERS))
    parser.add_argument("--limit", type=int, help="only process this many tracks")
    args = parser.parse_args()

    tracks = track_isrcs(args.user)
    if args.limit:
        tracks = dict(sorted(tracks.items())[:args.limit])
    print(f"{len(tracks)} tracks with an ISRC")

    clips, unavailable = download_previews(tracks, PREVIEW_DIR)
    print(f"previews: {len(clips)} available, {len(unavailable)} without audio "
          f"(cached in {PREVIEW_DIR})")

    out_path = EMBED_DIR / f"{args.model}.npz"
    done = load_existing(out_path)
    todo = {tid: path for tid, path in clips.items() if tid not in done}
    print(f"{len(done)} already embedded, {len(todo)} to go")
    if not todo:
        return

    embedder = get_embedder(args.model)
    ids = sorted(todo)
    vectors = embedder.embed_audio([todo[i] for i in ids])
    done.update(zip(ids, vectors))
    save(out_path, done)
    print(f"wrote {len(done)} x {vectors.shape[1]} embeddings to {out_path}")


if __name__ == "__main__":
    main()
