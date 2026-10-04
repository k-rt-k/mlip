"""Offline checks for LLM prompting, parsing, OpenRouter retries, and song resolution."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import openrouter  # noqa: E402
from parse import parse_songs, track_keys  # noqa: E402
from prompts import PROMPT_VERSION, SYSTEM, prompt_only, seeds_only, song_schema  # noqa: E402
from resolve import RESOLVE_VERSION, matches, resolve_song  # noqa: E402


def seed(title, *artists):
    return {"video_id": title, "title": title, "artists": list(artists)}


def raw(video_id, title, *artists, **extra):
    return {"videoId": video_id, "title": title, "artists": [{"name": a} for a in artists], **extra}


# prompts

def test_prompt_only_renders_request_count_and_version():
    messages = prompt_only("Cozy acoustic songs.", 20)
    assert messages[0] == {"role": "system", "content": SYSTEM}
    assert "Cozy acoustic songs." in messages[1]["content"]
    assert "20" in messages[1]["content"]
    assert PROMPT_VERSION == "v1"


def test_seeds_only_lists_every_seed_with_artists_and_no_request_text():
    messages = seeds_only([seed("Halo", "Beyoncé"), seed("Yellow", "Coldplay", "Guest")], 10)
    user = messages[1]["content"]
    assert "1. Halo — Beyoncé" in user and "2. Yellow — Coldplay, Guest" in user
    assert "10" in user


def test_schema_requires_title_and_artist():
    schema = song_schema()["json_schema"]["schema"]
    assert schema["properties"]["songs"]["items"]["required"] == ["title", "artist"]


# parse

def test_parse_valid_json_drops_duplicates_seed_repeats_and_malformed():
    text = json.dumps({"songs": [
        {"title": "Halo (Live)", "artist": "Beyonce"},       # seed repeat after normalisation
        {"title": "Yellow", "artist": "Coldplay"},
        {"title": "yellow", "artist": "coldplay"},            # duplicate
        {"title": "", "artist": "Nobody"},                   # malformed
        {"artist": "No title"},                              # malformed
        {"title": "Clocks", "artist": "Coldplay"},
    ]})
    songs, stats = parse_songs(text, exclude=track_keys([seed("Halo", "Beyoncé")]))
    assert songs == [{"title": "Yellow", "artist": "Coldplay"}, {"title": "Clocks", "artist": "Coldplay"}]
    assert stats == {"returned": 6, "kept": 2, "malformed": 2, "duplicates": 1, "seed_repeats": 1}


def test_parse_accepts_fenced_json_and_bare_lists():
    fenced = 'Sure!\n```json\n{"songs": [{"title": "A", "artist": "B"}]}\n```'
    assert parse_songs(fenced)[0] == [{"title": "A", "artist": "B"}]
    assert parse_songs('[{"title": "A", "artist": "B"}]')[0] == [{"title": "A", "artist": "B"}]


def test_parse_without_json_raises():
    with pytest.raises(ValueError):
        parse_songs("I cannot help with that.")


# openrouter

def response(status, body=None, headers=None):
    r = MagicMock(status_code=status, headers=headers or {})
    r.json.return_value = body or {}
    r.raise_for_status.side_effect = None if status < 400 else openrouter.requests.HTTPError(str(status))
    return r


OK = {"id": "gen-1", "model": "google/gemma", "provider": "Google AI Studio",
      "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
      "usage": {"prompt_tokens": 5, "completion_tokens": 7}}


def fake_requests(monkeypatch, *responses):
    http = MagicMock()
    http.post.side_effect = list(responses)
    http.HTTPError = openrouter.requests.HTTPError
    monkeypatch.setattr(openrouter, "requests", http)
    monkeypatch.setattr(openrouter.time, "sleep", lambda s: None)
    return http


def test_complete_retries_rate_limit_then_returns_metadata(monkeypatch):
    http = fake_requests(monkeypatch, response(429, headers={"Retry-After": "1"}), response(200, OK))
    out = openrouter.complete([{"role": "user", "content": "hi"}], "m", seed=3, key="sk-test")
    assert out["text"] == "{}" and out["model"] == "google/gemma" and out["provider"] == "Google AI Studio"
    assert out["retries"] == 1 and out["usage"]["completion_tokens"] == 7
    payload = http.post.call_args.kwargs["json"]
    assert payload["temperature"] == 0 and payload["seed"] == 3 and payload["model"] == "m"


def test_complete_retries_error_in_ok_body_and_gives_up(monkeypatch):
    busy = {"error": {"code": 502, "message": "upstream busy"}}
    fake_requests(monkeypatch, *[response(200, busy)] * 3)
    with pytest.raises(RuntimeError, match="upstream busy"):
        openrouter.complete([], "m", key="sk-test", attempts=3)


def test_complete_does_not_retry_client_errors(monkeypatch):
    http = fake_requests(monkeypatch, response(401), response(200, OK))
    with pytest.raises(openrouter.requests.HTTPError):
        openrouter.complete([], "m", key="sk-test")
    assert http.post.call_count == 1


def test_missing_key_message_names_variable_not_value(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(openrouter, "ENV_PATH", tmp_path / ".env")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        openrouter.api_key()


# resolve

def test_matches_normalises_titles_artists_and_video_style_titles():
    track = {"title": "Yellow (Remastered)", "artists": ["Coldplay"]}
    assert matches(track, "Yellow", "coldplay")
    assert matches({"title": "Coldplay - Yellow (Official Video)", "artists": ["Coldplay"]}, "Yellow", "Coldplay")
    assert matches({"title": "Crazy in Love", "artists": ["Beyoncé", "JAY-Z"]}, "Crazy in Love", "Beyonce feat. Jay-Z")
    assert matches({"title": "Comptine d'un autre été, l'après-midi", "artists": ["Yann Tiersen"]},
                   "Comptine d'un autre été: L'après-midi", "Yann Tiersen")
    assert matches({"title": "Nocturne in E Flat Major, Op. 9, No. 2", "artists": ["Frédéric Chopin"]},
                   "Nocturne in E-flat Major, Op. 9 No. 2", "Fryderyk Chopin")  # surname fallback
    assert not matches({"title": "Hello", "artists": ["Lionel Richie"]}, "Hello", "Adele")
    assert not matches(track, "Yellow", "Someone Else")
    assert not matches(track, "Fix You", "Coldplay")


def test_resolve_returns_first_match_with_alternates_and_uses_cache():
    client = MagicMock()
    client.search.return_value = [raw("x", "Yellow", "Cover Band"), raw("a", "Yellow", "Coldplay"),
                                  raw("b", "Yellow (Live)", "Coldplay")]
    cache = {}
    hit = resolve_song(client, "Yellow", "Coldplay", cache)
    assert hit["video_id"] == "a" and hit["alt_video_ids"] == ["b"]
    assert resolve_song(client, "Yellow", "Coldplay", cache) == hit
    assert client.search.call_count == 1
    assert all(k.startswith(f"v{RESOLVE_VERSION}|") for k in cache)  # matcher changes invalidate old entries
    assert client.search.call_args.kwargs["filter"] == "songs"


def test_resolve_prefers_exact_title_over_version_variants():
    client = MagicMock()
    client.search.return_value = [raw("r", "Experience (Reimagined)", "Ludovico Einaudi"),
                                  raw("e", "Experience", "Ludovico Einaudi")]
    hit = resolve_song(client, "Experience", "Ludovico Einaudi", {})
    assert hit["video_id"] == "e" and hit["alt_video_ids"] == ["r"]


def test_resolve_falls_back_to_videos_and_returns_none_when_unmatched():
    client = MagicMock()
    client.search.side_effect = [[], [raw("v", "Coldplay - Yellow (Official Video)", "Coldplay")]]
    assert resolve_song(client, "Yellow", "Coldplay", {})["video_id"] == "v"
    assert [c.kwargs["filter"] for c in client.search.call_args_list] == ["songs", "videos"]
    client.search.side_effect = [[], []]
    assert resolve_song(client, "Made Up Song", "Nobody", {}) is None
