"""OpenReview authentication.

Anonymous API reads are blocked (403 "Challenge verification required" on both
API v1 and v2 as of Sept 2026), so every call needs a logged-in client.
Credentials come from peer/.env (see .env.example).
"""

import os
from pathlib import Path

import openreview
from dotenv import load_dotenv

PEER_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = PEER_DIR / ".env"

BASEURLS = {
    1: "https://api.openreview.net",
    2: "https://api2.openreview.net",
}


def credentials(env_path=ENV_PATH):
    load_dotenv(env_path)
    username = os.environ.get("OPENREVIEW_USERNAME")
    password = os.environ.get("OPENREVIEW_PASSWORD")
    if not (username and password):
        raise RuntimeError(
            f"OPENREVIEW_USERNAME/OPENREVIEW_PASSWORD not set. Copy {PEER_DIR}/.env.example "
            "to .env and fill in your openreview.net login (see docs/openreview_api.md)."
        )
    return username, password


def get_client(api_version=2, env_path=ENV_PATH):
    """Return a logged-in OpenReview client for API v1 or v2."""
    if api_version not in BASEURLS:
        raise ValueError(f"api_version must be 1 or 2, got {api_version!r}")
    username, password = credentials(env_path)
    cls = openreview.api.OpenReviewClient if api_version == 2 else openreview.Client
    return cls(baseurl=BASEURLS[api_version], username=username, password=password)
