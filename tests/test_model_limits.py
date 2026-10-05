"""Model context lengths (03-llm: 모델 맥락 길이): read from the service, else the known-model table."""

import asyncio
import json

import httpx
import pytest

from atelierx.core import agent
from atelierx.core.i18n import AppError
from atelierx.core.llm import Providers
from atelierx.core.model_limits import known, ollama_limits


class FakeVault:
    def reveal(self, name):
        return {'k': 'secret-value'}.get(name)


def _providers(paths, provider, handler):
    llm = Providers(paths, FakeVault())
    llm.save({'schema_version': 1, 'providers': {'p': provider}, 'tasks': {}})
    llm.transport = httpx.MockTransport(handler)
    return llm


def _info(llm, model):
    return asyncio.run(llm.model_info('p', model))


def test_ollama_reports_the_context_under_its_architecture_name():
    shown = {
        'model_info': {'general.architecture': 'deepseek4', 'deepseek4.context_length': 1048576},
        'capabilities': ['completion', 'thinking'],
    }
    assert ollama_limits(shown) == {
        'context': 1048576,
        'max_output': None,
        'capabilities': ['completion', 'thinking'],
    }
    # Without the architecture field any *.context_length counts; a smaller num_ctx is what the model really uses.
    local = {'model_info': {'qwen3.context_length': 40960}, 'parameters': 'temperature 0.6\nnum_ctx 8192'}
    assert ollama_limits(local)['context'] == 8192
    assert ollama_limits({'model_info': {}}) is None


def test_ollama_cloud_is_asked_at_api_show_beside_the_openai_path(paths):
    seen = []

    def handler(request):
        seen.append(
            (
                request.method,
                str(request.url),
                request.headers.get('authorization'),
                json.loads(request.content),
            )
        )
        return httpx.Response(
            200, json={'model_info': {'general.architecture': 'kimi-k3', 'kimi-k3.context_length': 1048576}}
        )

    provider = {
        'name': 'Ollama',
        'type': 'openai_compatible',
        'preset': 'ollama',
        'base_url': 'https://ollama.com/v1',
        'key': 'secret:k',
    }
    info = _info(_providers(paths, provider, handler), 'kimi-k3')
    assert info == {'context': 1048576, 'max_output': None, 'capabilities': [], 'source': 'service'}
    assert seen == [('POST', 'https://ollama.com/api/show', 'Bearer secret-value', {'model': 'kimi-k3'})]


def test_gemini_openrouter_and_lm_studio_report_their_limits(paths):
    def gemini(request):
        assert str(request.url) == 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro'
        assert request.headers['x-goog-api-key'] == 'secret-value'
        return httpx.Response(200, json={'inputTokenLimit': 1048576, 'outputTokenLimit': 65536})

    provider = {
        'name': 'G',
        'type': 'openai_compatible',
        'preset': 'gemini',
        'key': 'secret:k',
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
    }
    assert _info(_providers(paths, provider, gemini), 'models/gemini-2.5-pro')['max_output'] == 65536

    def openrouter(request):
        return httpx.Response(
            200,
            json={
                'data': [
                    {'id': 'other', 'context_length': 1},
                    {
                        'id': 'vendor/model',
                        'context_length': 200000,
                        'top_provider': {'max_completion_tokens': 32000},
                    },
                ]
            },
        )

    provider = {'name': 'O', 'type': 'openai_compatible', 'base_url': 'https://openrouter.ai/api/v1'}
    info = _info(_providers(paths, provider, openrouter), 'vendor/model')
    assert (info['context'], info['max_output']) == (200000, 32000)

    def lm_studio(request):
        assert str(request.url) == 'http://127.0.0.1:1234/api/v0/models/qwen3-32b'
        return httpx.Response(200, json={'max_context_length': 40960, 'loaded_context_length': 16384})

    provider = {'name': 'L', 'type': 'openai_compatible', 'base_url': 'http://127.0.0.1:1234/v1'}
    assert _info(_providers(paths, provider, lm_studio), 'qwen3-32b')['context'] == 16384


def test_services_that_do_not_tell_fall_back_to_the_table(paths):
    def never(request):
        raise AssertionError('Vertex is not asked')

    vertex = {'name': 'V', 'type': 'vertex_openai', 'base_url': 'https://aiplatform.googleapis.com/v1/x'}
    assert _info(_providers(paths, vertex, never), 'google/gemini-2.5-pro') == {
        'context': 1048576,
        'max_output': None,
        'capabilities': [],
        'source': 'table',
    }

    def down(request):
        raise httpx.ConnectError('down')

    deepseek = {'name': 'D', 'type': 'openai_compatible', 'base_url': 'https://api.deepseek.com'}
    assert _info(_providers(paths, deepseek, down), 'deepseek-chat')['source'] == 'table'
    ollama = {
        'name': 'O',
        'type': 'openai_compatible',
        'preset': 'ollama',
        'base_url': 'https://ollama.com/v1',
    }
    assert _info(_providers(paths, ollama, down), 'unknown-model')['source'] is None
    assert known('Gemini-3-Pro')['context'] == 1048576


def test_the_agent_budget_uses_the_saved_length_then_the_table_up_to_the_cap():
    share = agent.CONTEXT_SHARE
    assert agent.context_budget({}, 'some-model') == int(8192 * share)
    assert agent.context_budget({}, 'deepseek-chat') == int(131072 * share)
    saved = {'models': {'m': {'context': 32768}}}
    assert agent.context_budget(saved, 'm') == int(32768 * share)
    assert agent.context_budget({}, 'gemini-2.5-pro') == int(agent.DEFAULT_CONTEXT_CAP * share)
    assert agent.context_budget({}, 'gemini-2.5-pro', cap=400000) == int(400000 * share)


def test_saving_refuses_token_counts_that_are_not_whole_numbers(paths):
    llm = Providers(paths, FakeVault())
    base = {'schema_version': 1, 'tasks': {}}
    for doc in (
        {**base, 'providers': {'p': {'name': 'm', 'type': 'mock', 'models': {'m': {'context': '32k'}}}}},
        {**base, 'providers': {'p': {'name': 'm', 'type': 'mock', 'models': {'m': {'max_output': 0}}}}},
        {**base, 'providers': {}, 'context_cap': -1},
    ):
        with pytest.raises(AppError):
            llm.save(doc)
    llm.save(
        {
            **base,
            'context_cap': 200000,
            'providers': {'p': {'name': 'm', 'type': 'mock', 'models': {'m': {'context': 32768}}}},
        }
    )


def test_the_model_info_route(unlocked):
    info = unlocked.get('/api/providers/local/model-info', params={'model': 'gemini-2.5-flash'}).json()
    assert info['source'] == 'table'
    assert unlocked.get('/api/providers/local/model-info').status_code == 400
