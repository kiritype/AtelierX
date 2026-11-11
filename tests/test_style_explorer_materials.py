"""Material selection, provider requests, and backward-compatible session recovery."""

import copy
import json

import httpx
import pytest

from atelierx.core import revisions
from atelierx.image.runtime import ImageRuntime
from atelierx.image.util import atomic_json
from test_style_explorer import BASE, action, complete, create, explorer, generate, token

__all__ = ['explorer']


def material(name, *, kind='tag', mode='candidate', role='style', value=1, weight=None, **extra):
    return {
        'kind': kind,
        'name': name,
        'mode': mode,
        'role': role,
        'weight': weight if weight is not None else {'mode': 'fixed', 'value': value},
        **extra,
    }


def random_weight(low, high, step):
    return {'mode': 'random', 'low': low, 'high': high, 'step': step}


def install_loras(runtime, names, family='anima'):
    catalog = runtime.comfy.catalog()
    catalog['loras'] = names
    if family == 'sdxl':
        model = 'sdxl/model.safetensors'
        catalog['models'] = [model]
        catalog['model_entries'] = {model: {'loader': 'CheckpointLoaderSimple', 'filename': model}}
    runtime.comfy.catalog = lambda: copy.deepcopy(catalog)


@pytest.mark.parametrize('family', ['anima', 'sdxl'])
def test_comfy_workflow_and_preset_apply_only_resolved_materials(explorer, family):
    client, runtime = explorer
    hero, ink, oil = [f'{family}/{name}.safetensors' for name in ('hero', 'ink', 'oil')]
    install_loras(runtime, [hero, ink, oil], family)
    session, _ = create(
        client,
        family=family,
        settings={'loras': [{'name': 'ignored/stale.safetensors'}]},
        materials=[
            material('hero portrait', role='character', mode='always', value=0.87512345),
            material('rim lighting', role='other', weight=random_weight(0.2, 0.5, 0.15)),
            material('excluded tag', mode='exclude'),
            material(
                hero, kind='lora', role='character', mode='always', value=0.37, trigger_words='hero pose'
            ),
            material(ink, kind='lora', weight=random_weight(0.23, 0.46, 0.1), trigger_words='ink strokes'),
            material(oil, kind='lora', weight=random_weight(0.23, 0.46, 0.1), trigger_words='oil strokes'),
            material('missing.safetensors', kind='lora', mode='exclude', trigger_words='missing trigger'),
        ],
        rules={'artist_min': 2, 'artist_max': 2, 'lora_min': 2, 'lora_max': 2, 'lora_low': 1, 'lora_high': 1},
    )
    assert 'loras' not in session['config']['settings']
    assert 'artists' not in session['config']
    session = complete(runtime, generate(client, session, 2))
    for candidate, graph in zip(session['candidates'], runtime.comfy.prompts, strict=True):
        loaders = {
            node['inputs']['lora_name']: (node['inputs']['strength_model'], node['inputs']['strength_clip'])
            for node in graph.values()
            if node['class_type'] == 'LoraLoader'
        }
        assert loaders.pop(hero) == (0.37, 0.37)
        assert len(loaders) == 1
        name, (model_strength, clip_strength) = loaders.popitem()
        assert name in (ink, oil)
        assert model_strength == clip_strength and model_strength in (0.23, 0.33, 0.43)
        lighting = next(row['weight'] for row in candidate['materials'] if row['name'] == 'rim lighting')
        assert lighting in (0.2, 0.35, 0.5)
        trigger = 'ink strokes' if name == ink else 'oil strokes'
        expected = f'(hero portrait:0.87512345), (rim lighting:{lighting}), hero pose, {trigger}'
        assert candidate['style_positive'] == expected
        assert {
            node['inputs']['text'] for node in graph.values() if node['class_type'] == 'CLIPTextEncode'
        } == {
            f'a red lighthouse, {expected}',
            'blurry',
        }
        assert graph['1']['class_type'] == ('CheckpointLoaderSimple' if family == 'sdxl' else 'UNETLoader')

    first = session['candidates'][0]
    response = client.post(
        f'{BASE}/{session["id"]}/preset',
        json={
            'revision': session['revision'],
            'request_id': token(),
            'candidate_id': first['id'],
            'name': 'Resolved materials',
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    preset = next(
        item for item in client.get('/api/image/presets').json() if item['id'] == result['preset_id']
    )
    assert preset['artist']['positive'] == first['style_positive']
    assert preset['settings']['loras'] == first['settings']['loras']


def test_comfy_pool_can_exceed_workflow_limit(explorer):
    client, runtime = explorer
    names = [f'anima/style{i}.safetensors' for i in range(17)]
    install_loras(runtime, names)
    session, _ = create(
        client,
        materials=[material(name, kind='lora', value=0.75) for name in names],
        rules={'lora_min': 1, 'lora_max': 1},
    )
    candidate = generate(client, session, 1)['candidates'][0]
    assert len(session['config']['materials']) == 17
    assert len(candidate['settings']['loras']) == 1
    assert candidate['settings']['loras'][0]['name'] in names


def test_pixai_mock_submission_preserves_ids_weights_and_trigger_words(explorer, monkeypatch):
    client, runtime = explorer
    model = '1861558740588989558'
    session, _ = create(
        client,
        service='pixai',
        family='pixai',
        settings={'model': model, 'loras': 'ignored'},
        materials=[
            material('soft lines', mode='always', value=0.8),
            material(
                'Hero',
                kind='lora',
                mode='always',
                role='character',
                value=0.91,
                id='123456780',
                trigger_words='#hero',
            ),
            *[
                material(
                    'Style',
                    kind='lora',
                    id=f'12345679{i}',
                    weight=random_weight(0.35, 0.56, 0.1),
                    trigger_words=f'palette {i}',
                )
                for i in range(6)
            ],
            material('Disabled', kind='lora', mode='exclude', id='123456781', trigger_words='disabled'),
        ],
        rules={'artist_min': 1, 'artist_max': 1, 'lora_min': 2, 'lora_max': 2, 'lora_high': 1.5},
    )
    candidate = generate(client, session, 1)['candidates'][0]
    job = runtime.queue.get(candidate['job_id'])
    service = runtime.services['pixai']
    requests = []

    def submit(request):
        requests.append(request)
        return httpx.Response(201, json={'id': 'mock-pixai-task'})

    monkeypatch.setattr(service, 'key', lambda: 'test-only')
    with httpx.Client(transport=httpx.MockTransport(submit)) as mock:
        monkeypatch.setattr(service, 'send', lambda request: request(mock))
        assert service.submit(job)['id'] == 'mock-pixai-task'

    (request,) = requests
    assert request.method == 'POST' and request.url.path == '/v2/image/create'
    body = json.loads(request.content)
    assert body['modelVersionId'] == model
    assert body['prompt'] == 'a red lighthouse, (soft lines:0.8)'
    assert body['negativePrompt'] == 'blurry' and body['seed'] == 123
    fixed, random = body['loras']
    assert fixed == {'modelId': '123456780', 'weight': 0.91, 'triggerWords': '#hero'}
    assert random['modelId'] in {f'12345679{i}' for i in range(6)}
    assert random['weight'] in (0.35, 0.45, 0.55)
    assert random['triggerWords'] == f'palette {random["modelId"][-1]}'


def test_novelai_weighted_prompt_uses_materials_instead_of_legacy_pools(explorer):
    client, runtime = explorer
    session, _ = create(
        client,
        service='novelai',
        family='novelai',
        settings={'loras': [{'name': 'stale'}]},
        materials=[
            material('ink', mode='always', value=0.81234567),
            material('pencil', weight=random_weight(1.05, 1.2, 0.1)),
            material('excluded', mode='exclude'),
        ],
        rules={'artist_min': 2, 'artist_max': 2},
    )
    candidate = generate(client, session, 1)['candidates'][0]
    job = runtime.queue.get(candidate['job_id'])
    body = runtime.services['novelai'].request_body(job)
    assert body['input'] in {
        'a red lighthouse, 0.81234567::ink::, 1.05::pencil::',
        'a red lighthouse, 0.81234567::ink::, 1.15::pencil::',
    }
    assert body['parameters']['seed'] == 123


@pytest.mark.parametrize(
    'service,rows,rules',
    [
        ('comfyui', [material('ink'), material('ink', mode='exclude')], {}),
        ('comfyui', [material('ink', mode='always')], {'artist_min': 0, 'artist_max': 0}),
        ('comfyui', [material('ink', mode='exclude')], {'artist_min': 1, 'artist_max': 1}),
        ('comfyui', [material('ink', value=True)], {}),
        ('comfyui', [material('ink', value=float('nan'))], {}),
        ('comfyui', [material('ink', weight=random_weight(0, 1, float('inf')))], {}),
        ('comfyui', [material('ink', weight=random_weight(0, 1, 0))], {}),
        ('comfyui', [material('ink', weight=random_weight(0, 1, 0.00001))], {}),
        ('comfyui', [material('ink', weight=random_weight(1, 0, 0.1))], {}),
        ('comfyui', [material('ink', role='unrecognized')], {}),
        ('comfyui', [material('ink', mode='unrecognized')], {}),
        ('comfyui', [material('wrong.safetensors', kind='lora')], {}),
        ('comfyui', [material('sdxl/ink.safetensors', kind='lora')], {}),
        (
            'comfyui',
            [material('anima/ink.safetensors', kind='lora'), material('ink.safetensors', kind='lora')],
            {},
        ),
        ('novelai', [material('ink', kind='lora', mode='exclude')], {}),
        ('pixai', [material('ink', kind='lora', id='invalid')], {}),
        ('pixai', [material('ink', kind='lora', id='123456789', value=1.01)], {}),
        (
            'pixai',
            [material('ink', kind='lora', id='123456789'), material('oil', kind='lora', id='123456789')],
            {},
        ),
        ('pixai', [material(str(i), kind='lora', id=f'12345678{i}') for i in range(6)], {'lora_max': 6}),
    ],
)
def test_invalid_materials_and_counts_are_rejected_without_admission(explorer, service, rows, rules):
    client, runtime = explorer
    install_loras(runtime, ['anima/ink.safetensors', 'sdxl/ink.safetensors', 'anima/oil.safetensors'])
    # Test the alias against an unambiguous basename while preserving a mismatched catalog entry.
    if len(rows) == 2 and rows[1]['name'] == 'ink.safetensors':
        install_loras(runtime, ['anima/ink.safetensors'])
    response = client.post(
        BASE,
        content=json.dumps(
            {
                'request_id': token(),
                'service': service,
                'positive': 'a red lighthouse',
                'materials': rows,
                'rules': rules,
            }
        ),
        headers={'Content-Type': 'application/json'},
    )
    assert response.status_code == 400, response.text
    assert not runtime.jobs
    assert not client.get(BASE).json()['sessions']


def test_legacy_session_read_and_restart_preserve_frozen_records_and_recipe_identity(explorer):
    client, runtime = explorer
    lora = 'anima/legacy.safetensors'
    install_loras(runtime, [lora])
    session, body = create(
        client,
        artists=[{'name': name, 'mode': 'candidate'} for name in ('ink', 'oil', 'paint', 'pencil')],
        settings={'loras': [{'name': lora, 'strength_model': 0.8}]},
        rules={
            'artist_min': 1,
            'artist_max': 1,
            'artist_low': 0.9,
            'artist_high': 0.9,
            'lora_min': 1,
            'lora_max': 1,
            'lora_low': 0.5,
            'lora_high': 0.5,
        },
    )
    session = complete(runtime, generate(client, session, 3))
    session = action(client, session, 'pair').json()
    session = action(client, session, 'vote', pair_id=session['pair']['id'], result='tie').json()
    session = action(client, session, 'pair').json()
    path = runtime.explorer._path(session['id'])
    v1 = json.loads(path.read_text(encoding='utf-8'))
    v1['schema_version'] = 1
    del v1['config']['materials']
    for candidate in v1['candidates']:
        del candidate['materials']
        legacy_settings = {
            **v1['config']['settings'],
            'loras': [{'name': lora, 'strength_model': 0.5, 'strength_clip': 0.5}],
        }
        candidate['_signature'] = revisions.of(
            {
                'settings': legacy_settings,
                'artists': candidate['artists'],
                'style_positive': f'({candidate["artists"][0]["name"]}:0.9)',
                'style_negative': '',
            }
        )
    atomic_json(path, v1)
    disk = path.read_bytes()
    snapshots = [copy.deepcopy(job['snapshot']) for job in runtime.jobs]

    assert client.post(BASE, json=body).json()['id'] == session['id']
    migrated_view = client.get(f'{BASE}/{session["id"]}').json()
    assert path.read_bytes() == disk
    assert [job['snapshot'] for job in runtime.jobs] == snapshots
    assert len(runtime.jobs) == 3
    assert migrated_view['votes'] == session['votes'] and migrated_view['pair'] == session['pair']
    assert all(row['weight']['mode'] == 'random' for row in migrated_view['config']['materials'])

    restarted = ImageRuntime(runtime.paths, runtime.works, runtime.llm)
    restarted.comfy = runtime.comfy
    assert restarted.explorer.get(session['id']) == migrated_view
    assert path.read_bytes() == disk
    assert len(restarted.jobs) == 3
    result = restarted.explorer.generate(
        session['id'],
        {
            'request_id': token(),
            'revision': migrated_view['revision'],
            'count': 1,
        },
    )
    migrated = json.loads(path.read_text(encoding='utf-8'))
    assert migrated['schema_version'] == 2
    assert migrated['candidates'][:3] == v1['candidates']
    for key in ('pair', 'votes', '_create_request', '_create_fingerprint'):
        assert migrated[key] == v1[key]
    assert {key: migrated['_requests'][key] for key in v1['_requests']} == v1['_requests']
    assert [job['snapshot'] for job in restarted.jobs[:3]] == snapshots
    assert len({candidate['positive'] for candidate in result['candidates']}) == 4
    assert result['candidates'][3]['settings']['loras'] == [
        {'name': lora, 'strength_model': 0.5, 'strength_clip': 0.5},
    ]


def test_future_session_schema_cannot_be_changed_or_reconciled(explorer):
    client, runtime = explorer
    session, _ = create(client, materials=[material('ink')])
    session = generate(client, session, 1)
    path = runtime.explorer._path(session['id'])
    future = json.loads(path.read_text(encoding='utf-8'))
    future['schema_version'] = 99
    atomic_json(path, future)
    disk = path.read_bytes()

    response = action(client, session, 'cancel')
    assert response.status_code == 409, response.text
    assert response.json()['error']['key'] == 'server.explorer.schema_version'
    assert runtime.jobs[0]['status'] == 'queued'
    runtime.jobs[0]['status'] = 'failed'
    runtime.explorer.reconcile(session['id'])
    assert path.read_bytes() == disk
