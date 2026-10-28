"""Shared OpenAI-compatible completion transport and normalized response metadata."""

import time

import requests


def complete(messages, model, temperature=0, seed=0, response_format=None, max_tokens=None,
             attempts=4, *, endpoint, headers, timeout=180, label="LLM", extra=None):
    """Retry rate-limit/provider errors; preserve generation settings on every attempt.

    `extra` adds backend-specific payload fields (e.g. OpenRouter provider routing).
    """
    if attempts < 1:
        raise ValueError("attempts must be positive")
    payload = {"model": model, "messages": messages, "temperature": temperature, "seed": seed}
    if response_format:
        payload["response_format"] = response_format
    if max_tokens:
        payload["max_tokens"] = max_tokens
    payload.update(extra or {})
    for attempt in range(attempts):
        start = time.monotonic()
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        latency = round(time.monotonic() - start, 3)
        status, message = response.status_code, f"HTTP {response.status_code}"
        if status < 400:
            body = response.json()
            error = body.get("error")
            if not error and body["choices"][0].get("finish_reason") == "error":
                error = {"code": 502, "message": "provider error mid-generation (finish_reason=error)"}
            if not error:
                choice = body["choices"][0]
                return {"text": choice["message"].get("content") or "",
                        "finish_reason": choice.get("finish_reason"), "id": body.get("id"),
                        "model": body.get("model"), "provider": body.get("provider"),
                        "usage": body.get("usage"), "latency_s": latency, "retries": attempt}
            code = error.get("code")
            status, message = (code if isinstance(code, int) else 500), error.get("message", message)
        # Providers may echo an authentication value in their JSON error message.
        for value in headers.values():
            if value.startswith("Bearer "):
                message = str(message).replace(value[7:], "[redacted]")
        if status != 429 and status < 500:
            response.raise_for_status()
            raise RuntimeError(f"{label} error {status}: {message}")
        if attempt == attempts - 1:
            raise RuntimeError(f"{label} gave up after {attempts} attempts: {message}")
        retry_after = str((response.headers or {}).get("Retry-After", ""))
        time.sleep(float(retry_after) if retry_after.isdigit() else min(60, 5 * 2 ** attempt))
