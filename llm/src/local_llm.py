"""Adapter for the forwarded local OpenAI-compatible chat endpoint."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

import chat_client

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_BASE_URL = "http://127.0.0.1:18088/v1"
ROUTER_MODELS = ("local-deepseek", "local-qwen", "local-gemma", "local-gemma-bf16")


def endpoint():
    """Resolve a public endpoint identity without embedded authentication."""
    load_dotenv(ENV_PATH)
    base = os.environ.get("LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    try:
        parts = urlsplit(base)
        _ = parts.port  # Validate numeric port syntax.
    except ValueError:
        raise ValueError("LOCAL_LLM_BASE_URL must be a valid HTTP(S) base URL") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname or
            parts.username is not None or parts.password is not None or parts.query or parts.fragment):
        raise ValueError("LOCAL_LLM_BASE_URL must be HTTP(S), without credentials, query or fragment")
    return base + ("/v1" if not parts.path else "") + "/chat/completions"


def validate_model(model, url):
    """The Claude router forwards unknown aliases remotely, so require known local names."""
    parts = urlsplit(url)
    if (parts.hostname in ("localhost", "127.0.0.1") and parts.port in (18088, 18082)
            and model not in ROUTER_MODELS):
        raise ValueError("Local router model must be one of: " + ", ".join(ROUTER_MODELS))


def api_key():
    load_dotenv(ENV_PATH)
    return os.environ.get("LOCAL_LLM_API_KEY") or None


def complete(messages, model, temperature=0, seed=0, response_format=None, max_tokens=None,
             attempts=4, key=None, *, url=None):
    """Use the same payload as OpenRouter; allow time for router model loading."""
    url = url or endpoint()
    validate_model(model, url)
    key = key or api_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return chat_client.complete(
        messages, model, temperature, seed, response_format, max_tokens, attempts,
        endpoint=url, headers=headers, timeout=900, label="Local LLM")
