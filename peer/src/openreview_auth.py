"""OpenReview authentication.

Anonymous API reads are blocked (403 "Challenge verification required" on both
API v1 and v2 as of Sept 2026), so every call needs a logged-in client.

Preferred: a bearer token in peer/.env (OPENREVIEW_TOKEN), minted for up to a
week by `peer/scripts/openreview_login.py`, so no password is stored.
Fallback: OPENREVIEW_USERNAME + OPENREVIEW_PASSWORD in the same file.
"""

import os
from pathlib import Path

import openreview
import openreview.api
from dotenv import dotenv_values

PEER_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = PEER_DIR / ".env"

BASEURLS = {
    1: "https://api.openreview.net",
    2: "https://api2.openreview.net",
}
PLACEHOLDERS = {"you@example.com", "your-password-here", "your-token-here", ""}
MAX_TOKEN_SECONDS = 7 * 24 * 3600  # OpenReview's cap on expiresIn


def _settings(env_path):
    """Merge peer/.env (if present) under the process environment."""
    values = dict(dotenv_values(env_path)) if Path(env_path).exists() else {}
    for key in ("OPENREVIEW_TOKEN", "OPENREVIEW_USERNAME", "OPENREVIEW_PASSWORD"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return {k: (v if v not in PLACEHOLDERS else None) for k, v in values.items()}


def get_client(api_version=2, env_path=ENV_PATH):
    """Return a logged-in OpenReview client for API v1 or v2 (token first, then password)."""
    if api_version not in BASEURLS:
        raise ValueError(f"api_version must be 1 or 2, got {api_version!r}")
    cls = openreview.api.OpenReviewClient if api_version == 2 else openreview.Client
    s = _settings(env_path)
    if s.get("OPENREVIEW_TOKEN"):
        return cls(baseurl=BASEURLS[api_version], token=s["OPENREVIEW_TOKEN"])
    if s.get("OPENREVIEW_USERNAME") and s.get("OPENREVIEW_PASSWORD"):
        return cls(baseurl=BASEURLS[api_version], username=s["OPENREVIEW_USERNAME"],
                   password=s["OPENREVIEW_PASSWORD"])
    raise RuntimeError(
        f"No OpenReview credentials in {env_path}. Run "
        "`python peer/scripts/openreview_login.py` to store a token (no password kept), "
        "or set OPENREVIEW_USERNAME/OPENREVIEW_PASSWORD."
    )


def write_token(env_path, token):
    """Set OPENREVIEW_TOKEN in `env_path`, dropping any stored password. File mode 0600."""
    env_path = Path(env_path)
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    kept = [ln for ln in lines
            if not ln.startswith(("OPENREVIEW_TOKEN=", "OPENREVIEW_PASSWORD="))]
    kept.append(f"OPENREVIEW_TOKEN={token}")
    env_path.write_text("\n".join(kept) + "\n")
    env_path.chmod(0o600)
    return env_path
