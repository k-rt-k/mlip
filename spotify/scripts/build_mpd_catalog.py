"""Build a resumable SQLite track catalog without extracting MPD's ZIP."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mpd import build_catalog

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    summary = build_catalog(args.archive, args.database)
    if (summary['playlists'], summary['entries'], summary['tracks']) != (1000000, 66346428, 2262292):
        raise RuntimeError(f'MPD counts differ from published totals: {summary}')
    args.database.with_suffix('.summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(summary)
