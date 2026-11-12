"""Model pools and frozen artist formatting reach the provider requests."""

import copy
import json

import httpx
import pytest

from atelierx.image.util import atomic_json
from test_style_explorer import BASE, complete, create, explorer, generate, token

__all__ = ['explorer']


def install_models(runtime, family):
    catalog = runtime.comfy.catalog()
    first = f'{family}/first.safetensors'
    second = f'{family}/second.safetensors'
    models = {
        first if family == 'anima' else f'checkpoint::{first}': {
            'loader': 'UNETLoader' if family == 'anima' else 'CheckpointLoaderSimple',
            'filename': first,
        },
        f'checkpoint::{second}': {'loader': 'CheckpointLoaderSimple', 'filename': second},
    }
    catalog['models'] = list(models)
    catalog['model_entries'] = models
    runtime.comfy.catalog = lambda: copy.deepcopy(catalog)
    return models


@pytest.mark.parametrize('family', ['anima', 'sdxl'])
def test_model_pool_drives_the_actual_comfy_loader(explorer, family):
    client, runtime = explorer
    models = install_models(runtime, family)
    session, _ = create(
        client,
        family=family,
        models=list(models),
        settings={'model': 'stale-model.safetensors', 'steps': 19},
        materials=[],
        rules={},
    )
    assert session['config']['models'] == list(models)
    assert session['config']['settings']['model'] == next(iter(models))
    session = complete(runtime, generate(client, session, 2))
    assert {candidate['settings']['model'] for candidate in session['candidates']} == models.keys()
    for candidate, graph in zip(session['candidates'], runtime.comfy.prompts, strict=True):
        chosen = models[candidate['settings']['model']]
        loader = graph['1']
        assert loader['class_type'] == candidate['settings']['model_loader'] == chosen['loader']
        assert candidate['settings']['model_filename'] == chosen['filename']
        field = 'unet_name' if chosen['loader'] == 'UNETLoader' else 'ckpt_name'
        assert loader['inputs'][field] == chosen['filename']
        assert (
            next(node['inputs']['steps'] for node in graph.values() if node['class_type'] == 'KSampler') == 19
        )


def test_pixai_pool_submits_each_models_version_and_matching_parameters(explorer, monkeypatch):
    client, runtime = explorer
    sdxl, dit = '1861558740588989558', '1983308862240288769'
    session, _ = create(
        client,
        service='pixai',
        family='pixai',
        models=[sdxl, dit],
        settings={'model': '123456789', 'mode': 'pro', 'sampler': 'Euler', 'steps': 31, 'cfg_scale': 4.5},
        materials=[],
        rules={},
    )
    assert session['config']['models'] == [sdxl, dit]
    session = generate(client, session, 2)
    service = runtime.services['pixai']
    sent = {}

    def submit(request):
        assert request.url.path == '/v2/image/create'
        body = json.loads(request.content)
        sent[body['modelVersionId']] = body
        return httpx.Response(201, json={'id': 'mock-task'})

    monkeypatch.setattr(service, 'key', lambda: 'test-only')
    with httpx.Client(transport=httpx.MockTransport(submit)) as mock:
        monkeypatch.setattr(service, 'send', lambda request: request(mock))
        for candidate in session['candidates']:
            body = service.submit(runtime.queue.get(candidate['job_id']))['record']
            assert body['modelVersionId'] == candidate['settings']['model']
    assert set(sent) == {sdxl, dit}
    assert sent[sdxl]['sampling'] == {'method': 'Euler', 'steps': 31, 'cfgScale': 4.5}
    assert 'mode' not in sent[sdxl]
    assert sent[dit]['mode'] == 'pro' and 'sampling' not in sent[dit]


@pytest.mark.parametrize(
    'service,models',
    [
        ('comfyui', ['anima/first.safetensors', 'first.safetensors']),
        ('comfyui', ['anima/first.safetensors', 'checkpoint::sdxl/foreign.safetensors']),
        ('comfyui', ['anima/first.safetensors', 'missing.safetensors']),
        ('comfyui', ''),
        ('pixai', ['1861558740588989558', '123456789']),
    ],
)
def test_model_pool_rejects_duplicate_unknown_and_other_family_models(explorer, service, models):
    client, runtime = explorer
    available = install_models(runtime, 'anima')
    catalog = runtime.comfy.catalog()
    other = 'checkpoint::sdxl/foreign.safetensors'
    catalog['models'] = [*available, other]
    catalog['model_entries'][other] = {
        'loader': 'CheckpointLoaderSimple',
        'filename': 'sdxl/foreign.safetensors',
    }
    runtime.comfy.catalog = lambda: copy.deepcopy(catalog)
    response = client.post(
        BASE,
        json={
            'request_id': token(),
            'service': service,
            'positive': 'one tree',
            'models': models,
            'materials': [],
        },
    )
    assert response.status_code == 400, response.text
    assert not runtime.jobs


def test_anima_escapes_artist_names_and_reuses_the_same_graph_from_new_and_old_presets(explorer):
    client, runtime = explorer
    rows = [
        {'kind': 'tag', 'name': r'@Foo_Bar \(Part\)', 'weight': {'mode': 'fixed', 'value': 1}},
        {'kind': 'tag', 'name': 'Artist:Homunculus (Alchemynote)', 'weight': {'mode': 'fixed', 'value': 2}},
    ]
    session, _ = create(
        client,
        materials=rows,
        rules={'artist_min': 2, 'artist_max': 2},
        positive='1girl, (sky:1.15)',
    )
    assert session['config']['artist_format'] == 'anima'
    session = complete(runtime, generate(client, session, 1))
    (candidate,) = session['candidates']
    style = r'@foo bar \(part\), (@homunculus \(alchemynote\):2)'
    assert candidate['style_positive'] == style
    graph = runtime.comfy.prompts[0]
    assert {node['inputs']['text'] for node in graph.values() if node['class_type'] == 'CLIPTextEncode'} == {
        f'1girl, (sky:1.15), {style}',
        'blurry',
    }
    response = client.post(
        f'{BASE}/{session["id"]}/preset',
        json={
            'request_id': token(),
            'revision': session['revision'],
            'candidate_id': candidate['id'],
            'name': 'Anima weighted artists',
        },
    )
    assert response.status_code == 200, response.text
    preset_id = response.json()['preset_id']
    path = runtime.paths.data / 'image' / 'presets' / f'{preset_id}.json'
    stored = json.loads(path.read_text(encoding='utf-8'))
    assert set(stored['settings']).isdisjoint({'seed', 'model_loader', 'model_filename'})
    assert stored['artist']['positive'] == style
    wid = client.post('/api/samples/single/install').json()['id']
    direct = {'positive': '1girl, (sky:1.15)', 'negative': 'blurry', 'preset_id': preset_id}

    submitted = client.post(f'/api/works/{wid}/image/single', json={**direct, 'settings': {'seed': 123}})
    assert submitted.status_code == 200, submitted.text
    job = runtime.queue.get(submitted.json()['job_id'])
    assert runtime.services['comfyui'].graph(job) == graph

    stored['settings'].update(model_loader='outdated loader', model_filename='outdated filename')
    atomic_json(path, stored)
    disk = path.read_bytes()
    legacy = next(item for item in client.get('/api/image/presets').json() if item['id'] == preset_id)
    assert set(legacy['settings']).isdisjoint({'model_loader', 'model_filename'})
    assert legacy['settings']['model'] == candidate['settings']['model']
    assert path.read_bytes() == disk
    submitted = client.post(
        f'/api/works/{wid}/image/single',
        json={
            **direct,
            'settings': {**legacy['settings'], 'seed': 123},
            'prompt_sources': [
                {
                    'kind': 'style',
                    'id': preset_id,
                    'name': legacy['name'],
                    **legacy['artist'],
                }
            ],
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert runtime.services['comfyui'].graph(runtime.queue.get(submitted.json()['job_id'])) == graph


def test_anima_rejects_artist_aliases_that_resolve_to_the_same_tag(explorer):
    client, runtime = explorer
    response = client.post(
        BASE,
        json={
            'request_id': token(),
            'positive': 'one tree',
            'materials': [
                {'kind': 'tag', 'name': name, 'weight': {'mode': 'fixed', 'value': 1}}
                for name in ('Foo_Bar (part)', r'@foo bar \(part\)')
            ],
        },
    )
    assert response.status_code == 400, response.text
    assert not runtime.jobs


def test_saved_v2_anima_session_keeps_literal_artists_and_existing_recipe_hashes(explorer):
    client, runtime = explorer
    name = 'Legacy_Artist (Suffix)'
    session, body = create(
        client,
        materials=[
            {
                'kind': 'tag',
                'name': name,
                'role': 'style',
                'weight': {'mode': 'random', 'low': 0.8, 'high': 1, 'step': 0.2},
            },
        ],
        rules={'artist_min': 1, 'artist_max': 1},
    )
    session = generate(client, session, 1)
    path = runtime.explorer._path(session['id'])
    doc = json.loads(path.read_text(encoding='utf-8'))
    doc['schema_version'] = 2
    del doc['config']['artist_format']
    del doc['config']['materials'][0]['role']
    del doc['candidates'][0]['materials'][0]['role']
    atomic_json(path, doc)
    disk = path.read_bytes()
    queue_snapshot = copy.deepcopy(runtime.jobs[0]['snapshot'])
    assert client.post(BASE, json=body).json()['id'] == session['id']
    viewed = client.get(f'{BASE}/{session["id"]}').json()
    assert viewed['config']['artist_format'] == 'literal'
    assert path.read_bytes() == disk
    continued = generate(client, viewed, 1)
    assert {row['style_positive'] for row in continued['candidates']} == {name, f'({name}:0.8)'}
    migrated = json.loads(path.read_text(encoding='utf-8'))
    assert migrated['schema_version'] == 4
    assert migrated['candidates'][0] == doc['candidates'][0]
    assert runtime.jobs[0]['snapshot'] == queue_snapshot
