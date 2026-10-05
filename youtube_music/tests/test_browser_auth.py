"""Browser credential parsing must discard unrelated data and never execute input."""

import json
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser_auth import parse_browser_headers, save_browser_auth  # noqa: E402


HEADERS = {"Authorization": "SAPISIDHASH fake-signature", "Cookie": "SAPISID=fake-cookie",
           "X-Goog-AuthUser": "0", "X-Origin": "https://music.youtube.com"}


def test_plain_headers_are_normalized_and_unrelated_fields_removed():
    raw = '\n'.join(f'{key}: {value}' for key, value in {**HEADERS, 'X-Client-Data': 'irrelevant'}.items())
    parsed = parse_browser_headers(raw)
    assert parsed['cookie'] == HEADERS['Cookie']
    assert set(parsed) == {'accept', 'authorization', 'content-type', 'cookie', 'x-goog-authuser', 'x-origin'}


def test_json_headers_and_json_wrapper_are_supported():
    direct = parse_browser_headers(json.dumps(HEADERS))
    wrapped = parse_browser_headers(json.dumps({'headers': HEADERS, 'body': 'irrelevant'}))
    assert direct == wrapped


def test_copied_fetch_request_is_parsed_without_execution(tmp_path):
    marker = tmp_path / 'must-not-exist'
    raw = f'fetch("https://music.youtube.com", {{"headers": {json.dumps(HEADERS)}, "body": "unused"}}); require("fs").writeFileSync("{marker}", "bad");'
    assert parse_browser_headers(raw)['authorization'] == HEADERS['Authorization']
    assert not marker.exists()


def test_missing_cookie_rejected_without_echoing_secret_values():
    with pytest.raises(ValueError) as error:
        parse_browser_headers(json.dumps({'authorization': 'sensitive-value', 'x-goog-authuser': '0'}))
    assert 'sensitive-value' not in str(error.value)


def test_oauth_authorization_is_rejected():
    with pytest.raises(ValueError, match='SAPISIDHASH'):
        parse_browser_headers(json.dumps({**HEADERS, 'Authorization': 'Bearer fake-token'}))


def test_private_output_and_existing_file_preservation(tmp_path):
    output = tmp_path / 'private' / 'browser.json'
    headers = parse_browser_headers(json.dumps(HEADERS))
    save_browser_auth(output, headers)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text()) == headers
    with pytest.raises(FileExistsError):
        save_browser_auth(output, {'cookie': 'replacement'})
    assert json.loads(output.read_text()) == headers
