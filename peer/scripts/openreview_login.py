"""Mint a 7-day OpenReview bearer token and store it in peer/.env.

Prompts for your openreview.net password with hidden input; the password is
used once for login and never written anywhere. Re-run when the token expires.

    ~/mamba/envs/claude/bin/python peer/scripts/openreview_login.py [--username you@cmu.edu]
"""

import argparse
import getpass
import sys
from pathlib import Path

import openreview.api

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openreview_auth import BASEURLS, ENV_PATH, MAX_TOKEN_SECONDS, _settings, write_token  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--username", help="OpenReview login email (default: OPENREVIEW_USERNAME from .env)")
    p.add_argument("--env", type=Path, default=ENV_PATH)
    p.add_argument("--expires", type=int, default=MAX_TOKEN_SECONDS,
                   help="Token lifetime in seconds (max 7 days)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    username = args.username or _settings(args.env).get("OPENREVIEW_USERNAME") \
        or input("OpenReview email: ").strip()
    password = getpass.getpass(f"OpenReview password for {username}: ")

    client = openreview.api.OpenReviewClient(
        baseurl=BASEURLS[2], username=username, password=password,
        tokenExpiresIn=min(args.expires, MAX_TOKEN_SECONDS),
    )
    del password
    path = write_token(args.env, client.token)
    print(f"Logged in as {username}. Token stored in {path} (mode 600, expires in "
          f"{min(args.expires, MAX_TOKEN_SECONDS) // 86400} days).")


if __name__ == "__main__":
    main()
