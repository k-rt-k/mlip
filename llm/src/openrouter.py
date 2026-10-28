"""OpenRouter adapter; credentials come from llm/.env, never saved requests."""

import os
from pathlib import Path

from dotenv import load_dotenv

import chat_client

URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def api_key():
    load_dotenv(ENV_PATH)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(f"OPENROUTER_API_KEY not set — add it to {ENV_PATH}")
    return key


def complete(messages, model, temperature=0, seed=0, response_format=None, max_tokens=None,
             attempts=4, key=None, provider=None):
    """One chat completion via the shared client, keeping OpenRouter defaults.

    `provider` pins one host with no fallback, keeping weights/quantization fixed.
    """
    extra = {"provider": {"order": [provider], "allow_fallbacks": False}} if provider else None
    return chat_client.complete(
        messages, model, temperature, seed, response_format, max_tokens, attempts,
        endpoint=URL, headers={"Authorization": f"Bearer {key or api_key()}",
                               "X-Title": "mlip-llm-baseline"}, label="OpenRouter", extra=extra)
