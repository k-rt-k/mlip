"""Save browser authentication for YouTube Music; credentials stay local.

Sign in at music.youtube.com as mlip.team0@gmail.com, NOT your personal account.
In Developer Tools > Network, open Library to trigger an authenticated POST
/browse request. Right-click that request > Copy > Copy as fetch (Node.js).
In your own terminal:

    uv run python youtube_music/scripts/setup_auth.py

Paste the headers, then press Ctrl-D. On macOS, piping the clipboard avoids
long-paste limits and echoing the credentials:

    pbpaste | uv run python youtube_music/scripts/setup_auth.py --stdin

Saved header text, JSON headers, and Chrome "Copy as fetch" requests also work:

    uv run python youtube_music/scripts/setup_auth.py --headers-file browser_headers.json

To replace expired/wrong credentials, add --refresh. The script tests the
authenticated account connection before saving; failed checks preserve the
previous credentials. Optionally add --verify-playlist PRIVATE_TEAM_PLAYLIST_ID
to confirm ownership of a known private team playlist. Account metadata exposes
the display name/handle, not the email; always check the selected email in-browser.

Copied request code is parsed, never executed; only six relevant headers survive.
Output defaults to data/youtube_music/browser.json, with owner-only permissions.
Use this path as --auth in the playlist scripts. Do not paste headers into chat.
Browser authentication is our only account-auth method: OAuth bearer tokens
failed with HTTP 400 in our pilot (https://github.com/sigma67/ytmusicapi/issues/813).
https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html
"""

import argparse
import os
from pathlib import Path
import sys
import tempfile

from ytmusicapi import setup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from browser_auth import parse_browser_headers, save_browser_auth  # noqa: E402
from playlists import make_client  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--stdin", action="store_true", help="Read copied request headers from stdin without echoing them")
    source.add_argument("--headers-file", type=Path, help="Saved header text, JSON headers, or a copied fetch request")
    parser.add_argument("--output", type=Path, default=Path("data/youtube_music/browser.json"))
    parser.add_argument("--refresh", action="store_true", help="Replace credentials only after successful authentication")
    parser.add_argument("--verify-playlist", help="Require ownership of this known private team playlist")
    args = parser.parse_args()
    if args.output.exists() and not args.refresh:
        parser.error("Browser credential file already exists; add --refresh to replace it.")
    print("Use headers copied while logged into mlip.team0@gmail.com, not your personal account.", flush=True)
    headers_raw = args.headers_file.read_text(encoding="utf-8") if args.headers_file else sys.stdin.read() if args.stdin else setup()
    if not headers_raw.strip():
        parser.error("No request headers supplied on stdin")
    headers = parse_browser_headers(headers_raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temporary:
        candidate = Path(temporary) / "browser.json"
        save_browser_auth(candidate, headers)
        print("Testing authenticated connection…", flush=True)
        client = make_client(candidate)
        account = client.get_account_info()
        if not account.get("accountName"):
            raise RuntimeError("Authenticated account information was missing.")
        print(f"✅ Connected: {account['accountName']} ({account.get('channelHandle') or 'no channel handle'}).", flush=True)
        if args.verify_playlist:
            playlist = client.get_playlist(args.verify_playlist, limit=1)
            if playlist.get("owned") is not True or playlist.get("privacy") != "PRIVATE":
                raise RuntimeError("This account does not own the expected private team playlist.")
            print("✅ Private team playlist ownership verified.", flush=True)
        os.replace(candidate, args.output)
    print(f"✅ Fresh browser authentication saved to {args.output}; keep this file local.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Library exceptions may include request data; never print credential payloads.
        print(f"❌ Authentication setup failed ({type(exc).__name__}); previous credentials unchanged. "
              "Copy a fresh authenticated request from mlip.team0@gmail.com and retry.", file=sys.stderr)
        raise SystemExit(1)
