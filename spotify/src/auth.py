"""Spotify authentication: PKCE flow (user data), no client secret required.

Config comes from spotify/.env (see .env.example). Each user's token is cached
to a gitignored per-user file so the browser consent step happens once per
person (see users.py).
"""

import os

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE

from users import SPOTIFY_DIR, cache_path, check_identity, validate

ENV_PATH = SPOTIFY_DIR / ".env"

# Scopes needed for the EDA: personal listening data, read-only.
SCOPES = (
    "user-top-read",
    "user-library-read",
    "playlist-read-private",
    "user-follow-read",
    "user-read-recently-played",
)

# Loopback IP, not "localhost" — Spotify rejects localhost redirect URIs.
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8080/callback"


class _PKCE(SpotifyPKCE):
    """SpotifyPKCE lacks show_dialog; without it a browser already logged into
    Spotify auto-approves silently as whoever is signed in. Force the consent
    page (it has a "Not you?" account switch)."""

    def get_authorize_url(self, state=None):
        return super().get_authorize_url(state=state) + "&show_dialog=true"


def get_spotify(user, scopes=SCOPES):
    """Authenticated spotipy.Spotify for `user` (opens browser on first run)."""
    validate(user)
    load_dotenv(ENV_PATH)
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    if not client_id:
        raise RuntimeError(
            f"SPOTIPY_CLIENT_ID not set. Copy {SPOTIFY_DIR}/.env.example to .env "
            "and fill in the Client ID from developer.spotify.com/dashboard "
            "(see docs/spotify_api.md for setup steps)."
        )
    auth_manager = _PKCE(
        client_id=client_id,
        redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        scope=" ".join(scopes),
        cache_handler=CacheFileHandler(cache_path=str(cache_path(user))),
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    check_identity(sp, user)
    return sp
