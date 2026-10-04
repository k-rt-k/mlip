"""Minimal OpenRouter chat client with retries; the key comes from llm/.env, never arguments or logs."""

import os
from pathlib import Path
import time

import requests
from dotenv import load_dotenv

URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def api_key():
    load_dotenv(ENV_PATH)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(f"OPENROUTER_API_KEY not set — add it to {ENV_PATH}")
    return key


def complete(messages, model, temperature=0, seed=0, response_format=None, max_tokens=None,
             attempts=4, key=None):
    """One chat completion; returns text plus model/provider/usage/latency metadata.

    Retries 429/5xx, including errors OpenRouter reports inside a 200 body;
    other client errors fail immediately because they will not heal.
    """
    payload = {"model": model, "messages": messages, "temperature": temperature, "seed": seed}
    if response_format:
        payload["response_format"] = response_format
    if max_tokens:
        payload["max_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {key or api_key()}", "X-Title": "mlip-llm-baseline"}
    for attempt in range(attempts):
        start = time.monotonic()
        response = requests.post(URL, headers=headers, json=payload, timeout=180)
        latency = round(time.monotonic() - start, 3)
        status, message = response.status_code, f"HTTP {response.status_code}"
        if status < 400:
            body = response.json()
            error = body.get("error")
            if not error:
                choice = body["choices"][0]
                return {"text": choice["message"].get("content") or "",
                        "finish_reason": choice.get("finish_reason"), "id": body.get("id"),
                        "model": body.get("model"), "provider": body.get("provider"),
                        "usage": body.get("usage"), "latency_s": latency, "retries": attempt}
            code = error.get("code")
            status, message = (code if isinstance(code, int) else 500), error.get("message", message)
        if status != 429 and status < 500:
            response.raise_for_status()
            raise RuntimeError(f"OpenRouter error {status}: {message}")
        if attempt == attempts - 1:
            raise RuntimeError(f"OpenRouter gave up after {attempts} attempts: {message}")
        retry_after = str((response.headers or {}).get("Retry-After", ""))
        time.sleep(float(retry_after) if retry_after.isdigit() else min(60, 5 * 2 ** attempt))
