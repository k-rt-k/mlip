"""Per-user paths and identity guard for multi-user auth on one machine.

Each Spotify user gets their own token cache and data dir, keyed by a slug the
person chooses (`--user alice`). Pure path helpers plus one guard that stops a
cache file from silently holding someone else's token.
"""

import argparse
import json
import re
from pathlib import Path

SPOTIFY_DIR = Path(__file__).resolve().parents[1]
DATA_ROOT = SPOTIFY_DIR.parent / "data" / "spotify"

_SLUG = re.compile(r"^[a-z0-9_-]+$")


def validate(user):
    """Return the slug or raise — it becomes a filename, so keep it boring."""
    if not isinstance(user, str) or not _SLUG.match(user):
        raise ValueError(f"user must match [a-z0-9_-]+, got {user!r}")
    return user


def cache_path(user):
    return SPOTIFY_DIR / f".cache-pkce-{validate(user)}"


def data_dir(user):
    return DATA_ROOT / validate(user)


def check_identity(sp, user):
    """Ensure the token behind `sp` belongs to `user`; return the profile.

    First run records data/spotify/<user>/profile.json. Later runs compare the
    Spotify account id against it, catching the case where the browser
    auto-approved a different logged-in account.
    """
    profile = sp.current_user()
    marker = data_dir(user) / "profile.json"
    if marker.exists():
        expected = json.loads(marker.read_text())["id"]
        if expected != profile["id"]:
            raise RuntimeError(
                f"token for --user {user} belongs to Spotify account "
                f"{profile['id']!r}, but {marker} records {expected!r}. "
                f"Delete {cache_path(user)} and re-authenticate as the right account."
            )
    else:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(profile, indent=1))
    return profile


def user_arg(description):
    """Argparse parser with the required --user slug every script takes."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--user", required=True,
                        help="slug naming whose data (e.g. kartik)")
    return parser
