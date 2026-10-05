"""Normalize copied browser headers without executing copied request code."""

import json
import os
from pathlib import Path
import re

from ytmusicapi import setup

RELEVANT_HEADERS = {"accept", "authorization", "content-type", "cookie", "x-goog-authuser", "x-origin"}


def parse_browser_headers(raw):
    """Accept header text, JSON, or Chrome's Copy as fetch; retain six fields."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'"headers"\s*:\s*', raw)
        try:
            if match:
                parsed, _ = json.JSONDecoder().raw_decode(raw[match.end():].lstrip())
            else:
                parsed = json.loads(setup(headers_raw=raw))
        except Exception:
            raise ValueError("Could not parse browser request headers; copy an authenticated /browse request.") from None
    if isinstance(parsed, dict) and "headers" in parsed:
        parsed = parsed["headers"]
    if not isinstance(parsed, dict):
        raise ValueError("Request headers must form a JSON object or copied header text.")
    headers = {str(key).lower(): value for key, value in parsed.items()}
    normalized = {key: value for key, value in headers.items() if key in RELEVANT_HEADERS}
    normalized.setdefault("accept", "*/*")
    normalized.setdefault("content-type", "application/json")
    normalized.setdefault("x-origin", headers.get("origin", "https://music.youtube.com"))
    missing = {"authorization", "cookie", "x-goog-authuser"} - normalized.keys()
    if missing:
        raise ValueError("Missing required header names: " + ", ".join(sorted(missing)))
    normalized["x-goog-authuser"] = str(normalized["x-goog-authuser"])
    if any(not isinstance(value, str) or not value for value in normalized.values()):
        raise ValueError("Relevant headers must have nonempty string values.")
    if "SAPISIDHASH" not in normalized["authorization"]:
        raise ValueError("Expected browser SAPISIDHASH authorization, not OAuth tokens.")
    return normalized


def save_browser_auth(path, headers):
    """Create a private credential file without overwriting an existing one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        json.dump(headers, stream, indent=2)
        stream.write("\n")
