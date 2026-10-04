import asyncio
import json

import httpx
import pytest

from atelierx.core import llm
from atelierx.core.i18n import AppError


def provider_setup(unlocked, kind='openai_compatible'):
    service = unlocked.app.state.app.llm
    service.vault.put('cloud', 'api_key', 'test-private-token')
    service.save(
        {
            'schema_version': 1,
            'providers': {
                'cloud': {
                    'name': 'Cloud',
                    'type': kind,
                    'base_url': 'https://example.invalid/v1',
                    'key': 'secret:cloud',
                    'default_model': 'test-model',
                }
            },
            'tasks': {},
        }
    )
    return service


def test_external_completion_stream_and_json_fallback(unlocked, monkeypatch):
    service = provider_setup(unlocked)
    requests = []

    def handler(request):
        assert request.headers['authorization'] == 'Bearer test-private-token'
        assert str(request.url) == 'https://example.invalid/v1/chat/completions'
        body = json.loads(request.content)
        requests.append(body)
        if body.get('response_format'):
            return httpx.Response(400, json={'error': {'message': 'unsupported format'}})
        if body['stream']:
            chunks = [
                {'choices': [{'delta': {'reasoning_content': 'hidden', 'content': 'O'}}]},
                {
                    'choices': [{'delta': {'content': 'K'}}],
                    'usage': {'prompt_tokens': 3, 'completion_tokens': 2},
                },
            ]
            return httpx.Response(
                200, text=''.join(f'data: {json.dumps(c)}\n\n' for c in chunks) + 'data: [DONE]\n\n'
            )
        return httpx.Response(
            200,
            json={
                'choices': [{'message': {'content': 'OK'}}],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 1},
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    result = asyncio.run(service.probe('cloud'))
    assert result == {'ok': True, 'model': 'test-model', 'completion': True, 'stream': True}
    assert all(
        r['messages'] == [{'role': 'user', 'content': 'Reply with the single word OK.'}] for r in requests
    )
    asyncio.run(
        service.complete(
            'compression',
            [{'role': 'user', 'content': 'fixture'}],
            override={'provider': 'cloud'},
            json_mode=True,
        )
    )
    assert requests[-2]['response_format'] and 'response_format' not in requests[-1]


def test_vertex_manual_model_catalog_does_not_claim_network_test(unlocked, monkeypatch):
    service = provider_setup(unlocked, 'vertex_openai')
    monkeypatch.setattr(
        llm.httpx, 'AsyncClient', lambda **kw: pytest.fail('must not query unsupported model catalog')
    )
    assert asyncio.run(service.models('cloud')) == ['test-model']


@pytest.mark.parametrize(
    ('location', 'expected'),
    [
        (
            'global',
            'https://aiplatform.googleapis.com/v1/projects/atelierx-123/locations/global/endpoints/openapi',
        ),
        (
            'us-central1',
            'https://us-central1-aiplatform.googleapis.com/v1/projects/atelierx-123/locations/us-central1/endpoints/openapi',
        ),
    ],
)
def test_vertex_preset_builds_authoritative_endpoint_and_roundtrips(unlocked, location, expected):
    service = unlocked.app.state.app.llm
    doc = {
        'schema_version': 1,
        'providers': {
            'cloud': {
                'name': 'Vertex',
                'type': 'vertex_openai',
                'preset': 'vertex',
                'vertex_project': 'atelierx-123',
                'vertex_location': location,
                'base_url': 'https://attacker.invalid/ignored',
                'default_model': 'gemini-test',
            }
        },
        'tasks': {},
    }

    saved = service.save(doc)

    assert saved['providers']['cloud']['base_url'] == expected
    assert service.doc()['providers']['cloud'] == saved['providers']['cloud']


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('vertex_project', 'BadProject'),
        ('vertex_project', 'valid/project'),
        ('vertex_project', 'valid-project-'),
        ('vertex_location', '../evil'),
        ('vertex_location', 'us-central1?x=1'),
        ('vertex_location', '-us-central1'),
    ],
)
def test_vertex_preset_rejects_invalid_or_injected_fields(unlocked, field, value):
    service = unlocked.app.state.app.llm
    provider = {
        'name': 'Vertex',
        'type': 'vertex_openai',
        'preset': 'vertex',
        'vertex_project': 'atelierx-123',
        'vertex_location': 'global',
        'base_url': 'https://attacker.invalid',
    }
    provider[field] = value
    with pytest.raises(AppError):
        service.save({'providers': {'cloud': provider}})


def test_vertex_preset_requires_vertex_type_but_legacy_provider_remains_valid(unlocked):
    service = unlocked.app.state.app.llm
    with pytest.raises(AppError):
        service.save(
            {
                'providers': {
                    'cloud': {
                        'type': 'openai_compatible',
                        'preset': 'vertex',
                        'vertex_project': 'atelierx-123',
                        'vertex_location': 'global',
                        'base_url': 'https://example.invalid/v1',
                    }
                }
            }
        )
    legacy = {
        'providers': {
            'cloud': {
                'type': 'vertex_openai',
                'base_url': 'https://example.invalid/openapi',
            }
        }
    }
    assert service.save(legacy)['providers']['cloud']['base_url'] == 'https://example.invalid/openapi'


def test_provider_secrets_and_errors_do_not_leak(unlocked):
    service = provider_setup(unlocked)
    provider = service.doc()['providers']['cloud']
    response = httpx.Response(401, json={'error': {'message': 'echo test-private-token'}})
    assert 'test-private-token' not in str(service._http_error(provider, response))
    service.vault.delete('cloud')
    with pytest.raises(AppError):
        service._headers(provider)
    for patch in (
        {'key': 'plain-secret'},
        {'base_url': 'https://key:secret@example.com/v1'},
        {'base_url': 'file:///tmp'},
    ):
        with pytest.raises(AppError):
            service.save({'providers': {'cloud': {**provider, **patch}}})


def test_external_connection_still_requires_work_consent(unlocked):
    service = provider_setup(unlocked)

    class Work:
        name = 'fixture'

        def doc(self):
            return {}

    with pytest.raises(AppError) as error:
        service.require_consent(Work(), 'compression', {'provider': 'cloud'})
    assert error.value.status == 428


def test_run_provider_override_uses_provider_default_and_preserves_task_params(unlocked):
    service = provider_setup(unlocked)
    doc = service.doc()
    doc['providers']['other'] = {
        'name': 'Other',
        'type': 'openai_compatible',
        'base_url': 'https://other.invalid/v1',
        'default_model': 'other-default',
    }
    doc['tasks']['compression'] = {
        'provider': 'cloud',
        'model': 'task-model',
        'params': {'temperature': 0.1, 'top_p': 0.8},
    }
    service.save(doc)

    selected, model, params = service.resolve('compression', {'provider': 'other'})
    assert selected['id'] == 'other' and model == 'other-default'
    assert params == {'temperature': 0.1, 'top_p': 0.8}
    assert service.resolve('compression', {'provider': 'other', 'model': 'chosen-model'})[1] == 'chosen-model'
    assert service.resolve('compression', {'provider': 'cloud', 'model': ''})[1] == 'test-model'
    assert service.resolve('compression')[1] == 'task-model'
    assert service.doc()['tasks']['compression'] == doc['tasks']['compression']

    class Work:
        name = 'fixture'

        def doc(self):
            return {}

    with pytest.raises(AppError) as error:
        service.require_consent(Work(), 'compression', {'provider': 'other'})
    assert error.value.status == 428
    assert error.value.msg.values['provider'] == 'other'
