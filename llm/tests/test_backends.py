"""Offline checks for backend selection, request fidelity, and saved-run isolation."""

import json
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import chat_client
import local_llm
import openrouter
import run_llm_baseline as runner
from prompts import song_schema


@pytest.fixture
def http(monkeypatch, tmp_path):
    monkeypatch.setattr(local_llm, 'ENV_PATH', tmp_path / '.env')
    monkeypatch.delenv('LOCAL_LLM_BASE_URL', raising=False)
    monkeypatch.delenv('LOCAL_LLM_API_KEY', raising=False)
    response = MagicMock(status_code=200, headers={})
    response.json.return_value = {
        'model': 'served-weights', 'choices': [
            {'message': {'content': '{"songs": []}'}, 'finish_reason': 'stop'}]}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(chat_client.requests, 'post', post)
    return post


def test_local_keeps_schema_and_seed_without_openrouter_key(http, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    result = local_llm.complete([], 'local-deepseek', seed=7, response_format=song_schema())
    assert http.call_args.args == ('http://127.0.0.1:18088/v1/chat/completions',)
    assert http.call_args.kwargs['headers'] == {}
    assert http.call_args.kwargs['timeout'] == 900
    assert http.call_args.kwargs['json']['seed'] == 7
    assert http.call_args.kwargs['json']['response_format'] == song_schema()
    assert result['model'] == 'served-weights' and result['provider'] is None
    assert result['usage'] is None and result['text'] == '{"songs": []}'


def test_local_optional_auth_and_custom_endpoint(http, monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://localhost:18080/v1/')
    monkeypatch.setenv('LOCAL_LLM_API_KEY', 'local-secret')
    local_llm.complete([], 'served-model')
    assert http.call_args.args[0] == 'http://localhost:18080/v1/chat/completions'
    assert http.call_args.kwargs['headers'] == {'Authorization': 'Bearer local-secret'}


def test_router_rejects_unknown_model_before_http(http):
    with pytest.raises(ValueError, match='local-deepseek'):
        local_llm.complete([], 'qwen/qwen3.8-27b:free')
    http.assert_not_called()


@pytest.mark.parametrize('url', ['http://user:secret@localhost:18080/v1',
                                'http://localhost:18080/v1?key=secret',
                                'http://localhost:18080/v1#secret', 'file:///tmp/local'])
def test_endpoint_rejects_embedded_credentials(monkeypatch, url):
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', url)
    with pytest.raises(ValueError) as exc:
        local_llm.endpoint()
    assert 'secret' not in str(exc.value)


def test_unsupported_schema_is_not_silently_retried(http):
    http.return_value.status_code = 400
    http.return_value.raise_for_status.side_effect = chat_client.requests.HTTPError('unsupported schema')
    with pytest.raises(chat_client.requests.HTTPError):
        local_llm.complete([], 'local-gemma', response_format=song_schema())
    assert http.call_count == 1


def test_provider_error_redacts_key(http, monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_API_KEY', 'local-secret')
    http.return_value.json.return_value = {'error': {'code': 401, 'message': 'bad local-secret'}}
    with pytest.raises(RuntimeError) as exc:
        local_llm.complete([], 'local-gemma')
    assert 'local-secret' not in str(exc.value)


def test_legacy_openrouter_cache_reuses_original_hash(tmp_path):
    request = {'model': runner.DEFAULT_MODEL, 'messages': [], 'seed': 0}
    path = tmp_path / 'raw.json'
    first = MagicMock(return_value={'text': 'saved'})
    runner.cached_complete(path, request, first)
    again = MagicMock()
    assert runner.cached_complete(path, request, again) == ({'text': 'saved'}, True)
    again.assert_not_called()
    local_request = request | {'backend': 'local', 'endpoint': local_llm.endpoint()}
    fresh = MagicMock(return_value={'text': 'local'})
    assert runner.cached_complete(path, local_request, fresh)[1] is False
    assert 'Authorization' not in path.read_text()


@pytest.mark.parametrize('saved', [
    {'run': {'model_requested': runner.DEFAULT_MODEL}},
    {'request': {'model': runner.DEFAULT_MODEL}},
])
def test_local_cannot_overwrite_legacy_run(tmp_path, saved):
    path = tmp_path / ('prompt_only.json' if 'run' in saved else 'raw/prompt_only-01.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='different'):
        runner.validate_run_directory(tmp_path, 'local', local_llm.endpoint(), 'local-qwen')
    runner.validate_run_directory(tmp_path, 'openrouter', openrouter.URL, runner.DEFAULT_MODEL)
    assert json.loads(path.read_text()) == saved


def test_changed_endpoint_or_model_cannot_overwrite_local_run(tmp_path):
    saved = {'run': {'backend': 'local', 'endpoint': local_llm.endpoint(),
                     'model_requested': 'local-gemma'}}
    (tmp_path / 'seeds_only.json').write_text(json.dumps(saved))
    for endpoint, model in [('http://localhost:18080/v1/chat/completions', 'local-gemma'),
                            (local_llm.endpoint(), 'local-qwen')]:
        with pytest.raises(ValueError):
            runner.validate_run_directory(tmp_path, 'local', endpoint, model)
    runner.validate_run_directory(tmp_path, 'local', local_llm.endpoint(), 'local-gemma')


def test_local_model_required_before_data_or_credentials(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run', '--backend', 'local', '--mode', 'seeds_only', '--run-id', 'x'])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2


def test_local_runner_records_backend_and_unknown_cost(http, tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_API_KEY', 'local-secret')
    inputs = tmp_path / 'inputs.json'
    inputs.write_text(json.dumps({'prompts': [{'prompt_id': 1, 'prompt': 'quiet jazz'}]}))
    monkeypatch.setattr(runner, 'make_client', MagicMock())
    monkeypatch.setattr(sys, 'argv', ['run', '--backend', 'local', '--model', 'local-gemma',
        '--mode', 'prompt_only', '--run-id', 'local-test', '--input', str(inputs),
        '--out-root', str(tmp_path)])
    runner.main()
    output = json.loads((tmp_path / 'runs/local-test/prompt_only.json').read_text())
    assert output['run']['backend'] == 'local'
    assert output['run']['endpoint'] == local_llm.endpoint()
    assert output['summary']['cost_usd'] is None
    assert output['examples'][0]['status'] == 'ok'
    request = json.loads((tmp_path / 'runs/local-test/raw/prompt_only-01.json').read_text())['request']
    assert request['backend'] == 'local' and request['endpoint'] == local_llm.endpoint()
    assert 'key' not in request
    assert 'local-secret' not in json.dumps(output) + json.dumps(request)


def test_adapters_share_normalized_response_and_openrouter_defaults(http, monkeypatch):
    monkeypatch.setattr(chat_client.time, 'monotonic', lambda: 1.0)
    remote = openrouter.complete([], 'm', key='remote-secret')
    assert http.call_args.args[0] == openrouter.URL
    assert http.call_args.kwargs['timeout'] == 180
    assert http.call_args.kwargs['headers']['X-Title'] == 'mlip-llm-baseline'
    assert local_llm.complete([], 'local-qwen') == remote


def test_default_runner_keeps_openrouter_payload_and_credentials(http, tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs.json'
    inputs.write_text(json.dumps({'prompts': [{'prompt_id': 1, 'prompt': 'quiet jazz'}]}))
    monkeypatch.setattr(runner, 'make_client', MagicMock())
    monkeypatch.setattr(openrouter, 'api_key', lambda: 'remote-secret')
    monkeypatch.setattr(sys, 'argv', ['run', '--mode', 'prompt_only', '--run-id', 'remote-test',
                                   '--input', str(inputs), '--out-root', str(tmp_path)])
    runner.main()
    output = json.loads((tmp_path / 'runs/remote-test/prompt_only.json').read_text())
    assert output['run']['backend'] == 'openrouter'
    assert output['run']['model_requested'] == runner.DEFAULT_MODEL
    assert output['summary']['cost_usd'] == 0.0
    raw_path = tmp_path / 'runs/remote-test/raw/prompt_only-01.json'
    request = json.loads(raw_path.read_text())['request']
    assert set(request) == {'model', 'messages', 'temperature', 'seed', 'response_format'}
    assert 'remote-secret' not in raw_path.read_text()


def test_original_committed_cache_still_reuses_saved_response():
    root = Path(__file__).resolve().parents[2]
    run_dir = root / 'data/llm/runs/qwen3.8-27b-v1'
    runner.validate_run_directory(run_dir, 'openrouter', openrouter.URL, runner.DEFAULT_MODEL)
    path = run_dir / 'raw/prompt_only-01.json'
    saved = json.loads(path.read_text())
    call = MagicMock(side_effect=AssertionError('must use saved cache'))
    assert runner.cached_complete(path, saved['request'], call) == (saved['response'], True)
    call.assert_not_called()


def test_pinned_provider_cannot_mix_with_unpinned_run(tmp_path):
    saved = {'run': {'model_requested': 'qwen/qwen3.8-27b', 'provider_pinned': 'ModelRun'}}
    (tmp_path / 'seeds_only.json').write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='provider'):
        runner.validate_run_directory(tmp_path, 'openrouter', openrouter.URL, 'qwen/qwen3.8-27b')
    runner.validate_run_directory(tmp_path, 'openrouter', openrouter.URL, 'qwen/qwen3.8-27b', 'ModelRun')


def test_provider_pin_rejected_for_local_backend(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run', '--backend', 'local', '--model', 'local-qwen',
        '--provider', 'ModelRun', '--mode', 'seeds_only', '--run-id', 'x'])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
