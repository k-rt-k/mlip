"""Spotify authentication: PKCE flow (user data), no client secret required.

Config comes from spotify/.env (see .env.example). Token is cached to a
gitignored file so the browser consent step happens only once.
"""

import os
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE

SPOTIFY_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = SPOTIFY_DIR / ".env"
CACHE_PATH = SPOTIFY_DIR / ".cache-pkce"

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


def get_spotify(scopes=SCOPES, cache_path=CACHE_PATH):
    """Return an authenticated spotipy.Spotify (opens browser on first run)."""
    load_dotenv(ENV_PATH)
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    if not client_id:
        raise RuntimeError(
            f"SPOTIPY_CLIENT_ID not set. Copy {SPOTIFY_DIR}/.env.example to .env "
            "and fill in the Client ID from developer.spotify.com/dashboard "
            "(see docs/spotify_api.md for setup steps)."
        )
    auth_manager = SpotifyPKCE(
        client_id=client_id,
        redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        scope=" ".join(scopes),
        cache_handler=CacheFileHandler(cache_path=str(cache_path)),
    )
    return spotipy.Spotify(auth_manager=auth_manager)
