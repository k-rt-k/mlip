"""Save browser authentication for YouTube Music; credentials stay local.

Sign in at music.youtube.com. In Developer Tools > Network, copy the request
headers of a successful authenticated POST /browse request. In your own terminal:

    uv run python youtube_music/scripts/setup_auth.py

Paste the headers, then press Ctrl-D. On macOS, piping the clipboard avoids
long-paste limits and echoing the credentials:

    pbpaste | uv run python youtube_music/scripts/setup_auth.py --stdin

Saved header text, JSON headers, and Chrome "Copy as fetch" requests also work:

    uv run python youtube_music/scripts/setup_auth.py --headers-file browser_headers.json

Copied request code is parsed, never executed; only six relevant headers survive.
Output defaults to data/youtube_music/browser.json, with owner-only permissions.
Use this path as --auth in the playlist scripts. Do not paste headers into chat.
Browser authentication is our only account-auth method: OAuth bearer tokens
failed with HTTP 400 in our pilot (https://github.com/sigma67/ytmusicapi/issues/813).
https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html
"""

import argparse
from pathlib import Path
import sys

from ytmusicapi import setup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from browser_auth import parse_browser_headers, save_browser_auth  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--stdin", action="store_true", help="Read copied request headers from stdin without echoing them")
    source.add_argument("--headers-file", type=Path, help="Saved header text, JSON headers, or a copied fetch request")
    parser.add_argument("--output", type=Path, default=Path("data/youtube_music/browser.json"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Browser credential file already exists; reuse it or choose another output path.")
    headers_raw = args.headers_file.read_text(encoding="utf-8") if args.headers_file else sys.stdin.read() if args.stdin else setup()
    if not headers_raw.strip():
        parser.error("No request headers supplied on stdin")
    headers = parse_browser_headers(headers_raw)
    save_browser_auth(args.output, headers)
    print(f"Saved browser authentication to {args.output}; keep this file local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
