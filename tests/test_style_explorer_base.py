"""A base style stays fixed while the explicit candidate lists add materials."""

import copy
import json

import pytest

from atelierx.image.style_explorer import SCHEMA_VERSION
from atelierx.image.util import atomic_json
from test_style_explorer import BASE, complete, create, explorer, generate, token
from test_style_explorer_materials import install_loras, material

__all__ = ['explorer']

BASE_PRESET = {
    'id': 'base',
    'name': 'Base',
    'artist': {'positive': '(base artist:0.7)', 'negative': 'base negative'},
}


def test_base_loras_artist_upscale_and_saved_preset_keep_the_actual_recipe(explorer):
    client, runtime = explorer
    names = [f'anima/{name}.safetensors' for name in ('z-last', 'a-first', 'extra')]
    install_loras(runtime, names)
    catalog = runtime.comfy.catalog()
    catalog.update(upscale_models=['upscale.pth'], nodes={'upscale': True})
    runtime.comfy.catalog = lambda: copy.deepcopy(catalog)
    loras = [
        {'name': names[0], 'strength_model': 0.37, 'strength_clip': 0},
        {'name': names[1], 'strength_model': 0.82, 'strength_clip': -0.2},
    ]
    upscale = {'model': 'upscale.pth', 'scale': 1.5, 'steps': 8, 'denoise': 0.25}
    session, _ = create(
        client,
        base_preset=BASE_PRESET,
        settings={'loras': loras, 'upscale': upscale},
        materials=[material('ink'), material('oil'), material(names[2], kind='lora', value=0.6)],
        rules={'artist_min': 1, 'artist_max': 1, 'lora_min': 1, 'lora_max': 1},
    )
    assert session['config']['settings']['loras'] == loras
    session = complete(runtime, generate(client, session, 2))
    for candidate, graph in zip(session['candidates'], runtime.comfy.prompts, strict=True):
        expected = loras + [{'name': names[2], 'strength_model': 0.6, 'strength_clip': 0.6}]
        assert candidate['settings']['loras'] == expected
        loaders = [node['inputs'] for node in graph.values() if node['class_type'] == 'LoraLoader']
        assert [(v['lora_name'], v['strength_model'], v['strength_clip']) for v in loaders] == [
            (v['name'], v['strength_model'], v['strength_clip']) for v in expected
        ]
        assert candidate['settings']['upscale'] == upscale
        assert any(
            node['class_type'] == 'KSampler' and node['inputs']['denoise'] == 0.25 for node in graph.values()
        )
        assert candidate['style_positive'].startswith('(base artist:0.7), ')
        assert candidate['negative'] == 'blurry, base negative'
        assert {
            node['inputs']['text'] for node in graph.values() if node['class_type'] == 'CLIPTextEncode'
        } == {candidate['positive'], candidate['negative']}
    candidate = session['candidates'][0]
    response = client.post(
        f'{BASE}/{session["id"]}/preset',
        json={
            'revision': session['revision'],
            'request_id': token(),
            'candidate_id': candidate['id'],
            'name': 'Saved base',
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    preset = next(p for p in client.get('/api/image/presets').json() if p['id'] == saved['preset_id'])
    assert preset['settings']['loras'] == candidate['settings']['loras']
    assert preset['settings']['upscale'] == upscale
    assert preset['artist'] == {'positive': candidate['style_positive'], 'negative': 'base negative'}
    assert 'seed' not in preset['settings']


@pytest.mark.parametrize('service,limit', [('comfyui', 16), ('pixai', 5)])
def test_base_and_additional_loras_share_provider_limit_and_reject_duplicates(explorer, service, limit):
    client, runtime = explorer
    names = [f'anima/{index}.safetensors' for index in range(limit + 1)]
    install_loras(runtime, names)
    loras = (
        [{'name': name} for name in names[: limit - 1]]
        if service == 'comfyui'
        else [{'id': str(123456 + index), 'weight': 0.4} for index in range(limit - 1)]
    )
    extras = [
        material(names[index], kind='lora', **({'id': str(123456 + index)} if service == 'pixai' else {}))
        for index in (limit - 1, limit)
    ]
    session, body = create(
        client,
        service=service,
        family='anima' if service == 'comfyui' else 'pixai',
        base_preset=BASE_PRESET,
        settings={'loras': loras},
        materials=extras,
        rules={'lora_min': 1, 'lora_max': 1},
    )
    assert len(generate(client, session, 1)['candidates'][0]['settings']['loras']) == limit
    body['request_id'] += 'a'
    body['rules'] = {'lora_min': 2, 'lora_max': 2}
    assert client.post(BASE, json=body).status_code == 400
    body['rules'] = {'lora_min': 0, 'lora_max': 1}
    body['materials'] = [material(names[0], kind='lora', **({'id': '123456'} if service == 'pixai' else {}))]
    assert client.post(BASE, json=body).status_code == 400


def test_schema_three_keeps_anima_format_and_existing_candidates_when_resumed(explorer):
    client, runtime = explorer
    session, _ = create(
        client,
        materials=[
            {'kind': 'tag', 'name': name, 'weight': {'mode': 'fixed', 'value': 1}}
            for name in ('first_artist', 'second_artist')
        ],
        rules={'artist_min': 1, 'artist_max': 1},
    )
    session = generate(client, session, 1)
    path = runtime.explorer._path(session['id'])
    doc = json.loads(path.read_text())
    doc['schema_version'] = 3
    original = copy.deepcopy(doc['candidates'][0])
    atomic_json(path, doc)
    viewed = runtime.explorer.get(session['id'])
    assert viewed['config']['artist_format'] == 'anima'
    assert 'base_preset' not in viewed['config']
    generate(client, viewed, 1)
    upgraded = json.loads(path.read_text())
    assert upgraded['schema_version'] == SCHEMA_VERSION
    assert upgraded['candidates'][0] == original
    assert all('@' in candidate['style_positive'] for candidate in upgraded['candidates'])


@pytest.mark.parametrize('service', ['novelai', 'pixai'])
def test_internet_base_style_and_lora_values_reach_provider_payload(explorer, service):
    client, runtime = explorer
    loras = (
        [
            {'id': '123456780', 'weight': 0.37, 'trigger_words': 'base trigger'},
            {'id': '123456781', 'weight': 0.82},
        ]
        if service == 'pixai'
        else []
    )
    session, _ = create(
        client,
        service=service,
        family=service,
        base_preset=BASE_PRESET,
        settings={'loras': loras},
        materials=[material('new artist', value=1.5)],
        rules={'artist_min': 1, 'artist_max': 1, 'lora_min': 0, 'lora_max': 0},
    )
    candidate = generate(client, session, 1)['candidates'][0]
    body = runtime.services[service].request_body(runtime.queue.get(candidate['job_id']))
    if service == 'pixai':
        assert candidate['settings']['loras'] == loras
        assert body['loras'] == [
            {'modelId': '123456780', 'weight': 0.37, 'triggerWords': 'base trigger'},
            {'modelId': '123456781', 'weight': 0.82},
        ]
        assert body['prompt'] == candidate['positive']
        assert body['negativePrompt'] == 'blurry, base negative'
    else:
        assert body['input'] == 'a red lighthouse, (base artist:0.7), 1.5::new artist::'
        assert body['parameters']['negative_prompt'] == 'blurry, base negative'
