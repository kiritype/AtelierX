"""Anima reference adapter selection, ordered subjects, and saved workflows."""

import io
import json
import zipfile

import pytest
from PIL import Image

from atelierx.image import anima_reference
from atelierx.image.comfy import REFERENCE_NODE, REFERENCE_WEIGHT
from test_reference_generation import ReferenceComfy, png, request, upload

SNAPREF_WEIGHT = anima_reference.ADAPTERS[anima_reference.SNAPREF]


class AdapterComfy(ReferenceComfy):
    def __init__(self):
        super().__init__()
        self.loras = [REFERENCE_WEIGHT, SNAPREF_WEIGHT]
        self.snapref_node = True
        self.stitch_node = True

    def request(self, path, body=None, raw=False, timeout=15):
        if path == '/models/loras':
            return self.loras
        if path == '/object_info/ImageStitch':
            return {'ImageStitch': {}} if self.stitch_node else {}
        if path == '/object_info/AnimaRefAdapter':
            optional = {
                'clip': ['CLIP'],
                'snapref_mode': [['cs', 'char']],
                'ref_caption': ['STRING'],
                'snapref_guidance': ['BOOLEAN'],
                'ref_weight': ['FLOAT'],
            }
            return {REFERENCE_NODE: {'input': {'optional': optional if self.snapref_node else {}}}}
        return super().request(path, body, raw, timeout)


@pytest.fixture
def setup(unlocked, monkeypatch):
    client = unlocked
    work_id = client.post('/api/works', json={'name': 'Anima adapter test'}).json()['id']
    runtime = client.app.state.app.image
    runtime.set_paused(True)
    monkeypatch.setattr(runtime, 'comfy', AdapterComfy())
    return client, work_id, runtime, f'/api/works/{work_id}/image/reference'


def make_png(size, color):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, format='PNG')
    return stream.getvalue()


def body(asset, *, engine='snapref', count=1):
    result = request(asset)
    result['reference'] = {
        'engine': engine,
        'subjects': [{'id': asset['id'], 'slot': 'a', 'position': 'center' if count == 1 else 'left'}],
    }
    if count == 2:
        result['reference']['subjects'].append({'id': asset['id'], 'slot': 'b', 'position': 'right'})
    return result


def queue(client, url, payload, runtime):
    response = client.post(f'{url}/queue', json=payload)
    assert response.status_code == 200, response.text
    return runtime.queue.get(response.json()['job_id'])


def test_reference_status_distinguishes_adapters_and_two_person_readiness(setup):
    client, _, runtime, url = setup
    status = '/api/image/reference/status'
    assert client.get(status).json() == {'ready': True, 'node_ready': True, 'weights_ready': True}
    runtime.comfy.loras = [SNAPREF_WEIGHT]
    runtime.comfy.stitch_node = False
    explicit = client.get(status, params={'family': 'anima'}).json()
    assert explicit == {
        'ready': False,
        'node_ready': True,
        'weights_ready': False,
        'stitch_ready': False,
        'adapters': {
            'anima_v2': {'ready': False, 'node_ready': True, 'weights_ready': False},
            'snapref': {'ready': True, 'node_ready': True, 'weights_ready': True},
        },
    }
    asset = upload(client, url, png())
    single = queue(client, url, body(asset), runtime)
    assert single['snapshot']['reference']['snapref_mode'] == 'cs'
    two = client.post(f'{url}/queue', json=body(asset, count=2))
    assert two.status_code == 400 and two.json()['error']['key'] == 'server.reference.stitch_node'
    runtime.comfy.snapref_node = False
    unready = client.post(f'{url}/queue', json=body(asset))
    assert unready.status_code == 400 and unready.json()['error']['key'] == 'server.reference.snapref_node'
    assert runtime.comfy.uploads == []


def test_snapref_two_people_replay_and_export_use_the_frozen_left_right_graph(setup):
    client, work_id, runtime, url = setup
    original_right, original_left = png(), make_png((28, 42), '#aa1250')
    right = upload(client, url, original_right)
    left = upload(client, url, original_left)
    payload = body(right)
    payload['reference'].update(
        snapref_mode='char',
        subjects=[
            {'id': right['id'], 'slot': 'a', 'position': 'right', 'description': 'wearing glasses'},
            {'id': left['id'], 'slot': 'b', 'position': 'left', 'description': 'wearing a gold cape'},
        ],
    )
    job = queue(client, url, payload, runtime)
    job_id = job['id']
    assert runtime.comfy.uploads == []
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')
    run = client.get(f'{url}/runs').json()['runs'][0]
    assert run['id'] == job_id
    record = runtime.gallery.metadata(run['path'])
    assert record['schema_version'] == 8 and record['job_id'] == job_id
    assert record['reference']['scene'] == payload['positive']
    assert run['reference']['engine'] == 'snapref' and run['reference']['snapref_mode'] == 'char'
    assert [subject['id'] for subject in run['reference']['subjects']] == [right['id'], left['id']]
    assert all('url' not in subject for subject in record['reference']['subjects'])
    assert client.get(run['reference']['subjects'][0]['url']).content == original_right
    assert client.get(f'/api/works/{work_id}/image/single/runs').json() == {'runs': []}
    assert record['positive'] == (
        'walking on a rainy street. Two people. The person on the left is wearing a gold cape. '
        'The person on the right is wearing glasses.'
    )
    graph = runtime.comfy.prompts[0]
    nodes = {node['class_type']: (ident, node['inputs']) for ident, node in graph.items()}
    stitch_id, stitch = nodes['ImageStitch']
    left_name, right_name = (graph[stitch[key][0]]['inputs']['image'] for key in ('image1', 'image2'))
    assert runtime.comfy.uploads == [(left_name, original_left, ''), (right_name, original_right, '')]
    assert {key: stitch[key] for key in anima_reference.STITCH_SETTINGS} == anima_reference.STITCH_SETTINGS
    adapter_id, adapter = nodes[REFERENCE_NODE]
    assert adapter['image'] == [stitch_id, 0] and adapter['lora_name'] == SNAPREF_WEIGHT
    assert adapter['clip'] == ['2', 0] and adapter['snapref_mode'] == 'char'
    assert adapter['ref_weight'] == 1 and adapter['snapref_guidance'] is False
    sampler = nodes['KSampler'][1]
    assert sampler['model'] == [adapter_id, 0]
    assert graph[sampler['positive'][0]]['inputs']['text'] == record['positive']

    for include in (False, True):
        response = client.get(
            f'{url}/export', params={'path': run['path'], 'include_reference': str(include).lower()}
        )
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            files = {'result.png', 'workflow.json', 'prompt.json', 'generation.json'}
            if include:
                files.update((f'input/{left_name}', f'input/{right_name}'))
                assert archive.read(f'input/{left_name}') == original_left
                assert archive.read(f'input/{right_name}') == original_right
            assert set(archive.namelist()) == files
            assert json.loads(archive.read('prompt.json')) == graph
            assert json.loads(archive.read('generation.json'))['reference'] == record['reference']
            editor = json.loads(archive.read('workflow.json'))
            ui = {node['type']: node for node in editor['nodes']}
            assert ui['ImageStitch']['widgets_values'] == ['right', True, 0, 'white']
            assert [socket['name'] for socket in ui['ImageStitch']['inputs']] == ['image1', 'image2']
            assert ui[REFERENCE_NODE]['inputs'][-1]['name'] == 'clip'
            assert ui[REFERENCE_NODE]['widgets_values'] == [
                SNAPREF_WEIGHT,
                4.5,
                'apg',
                1,
                1,
                1,
                'char',
                '',
                False,
                1,
            ]
            links = {link[0]: link for link in editor['links']}
            assert links[ui[REFERENCE_NODE]['inputs'][2]['link']][1] == ui['ImageStitch']['id']

    response = client.post(f'{url}/regenerate', json={'path': run['path'], 'same_seed': True})
    assert response.status_code == 200, response.text
    repeat = runtime.queue.get(response.json()['job_id'])
    assert repeat['seed'] == job['seed'] and repeat['snapshot']['reference'] == record['reference']
    assert repeat['snapshot']['positive'] == record['positive']
    repeat['status'] = 'failed'
    response = client.post(f'/api/image/jobs/{repeat["id"]}/retry')
    assert response.status_code == 200, response.text
    retry = runtime.queue.get(response.json()['job_id'])
    assert retry['snapshot']['reference'] == record['reference'] and retry['seed'] == job['seed']
    sent = runtime.services['comfyui'].submit(retry)
    assert sent['record'] == graph


def test_anima_v2_one_person_keeps_scene_and_guidance(setup):
    client, _, runtime, url = setup
    asset = upload(client, url, png())
    payload = body(asset, engine='anima_v2')
    payload['reference']['subjects'][0]['description'] = 'gold cape'
    payload['reference']['guidance'] = 6.4
    single = queue(client, url, payload, runtime)
    sent = runtime.services['comfyui'].submit(single)['record']
    assert single['snapshot']['positive'] == payload['positive']
    assert single['snapshot']['reference']['guidance'] == 6.4
    assert not any(node['class_type'] == 'ImageStitch' for node in sent.values())
    adapter = next(node['inputs'] for node in sent.values() if node['class_type'] == REFERENCE_NODE)
    assert adapter['lora_name'] == REFERENCE_WEIGHT and adapter['ref_guidance'] == 6.4
    assert 'clip' not in adapter

    two = body(asset, engine='anima_v2', count=2)
    pair = queue(client, url, two, runtime)
    assert pair['snapshot']['positive'] == 'walking on a rainy street. Two people.'
    assert pair['snapshot']['reference']['guidance'] == 4.5


def test_two_person_result_keeps_preset_tags_separate_from_position_prompt(setup):
    client, _, runtime, url = setup
    preset_response = client.put(
        '/api/image/presets/reference-ink',
        json={
            'name': 'Reference ink',
            'service': 'comfyui',
            'family': 'anima',
            'artist': {'positive': 'ink drawing'},
        },
    )
    assert preset_response.is_success, preset_response.text
    preset_id = next(item['id'] for item in preset_response.json() if item['name'] == 'Reference ink')
    payload = body(upload(client, url, png()), count=2)
    payload['positive'] += ' # a private working note'
    job = queue(client, url, {**payload, 'preset_id': preset_id}, runtime)

    assert job['snapshot']['reference']['scene'] == 'walking on a rainy street'
    assert job['snapshot']['reference']['scene_prompt'] == 'walking on a rainy street, ink drawing'
    assert job['snapshot']['positive'] == 'walking on a rainy street, ink drawing. Two people.'


def test_invalid_two_person_slots_and_oversized_stitch_are_rejected(setup):
    client, _, runtime, url = setup
    asset = upload(client, url, png())
    single = body(asset)
    single['reference']['subjects'][0]['slot'] = 'b'
    response = client.post(f'{url}/queue', json=single)
    assert response.status_code == 400 and response.json()['error']['key'] == 'server.reference.subjects'

    payload = body(asset, count=2)
    payload['reference']['subjects'][1]['position'] = 'left'
    response = client.post(f'{url}/queue', json=payload)
    assert response.status_code == 400 and response.json()['error']['key'] == 'server.reference.subjects'
    payload['reference']['subjects'][1]['position'] = 'right'
    payload['reference']['snapref_mode'] = 'style'
    response = client.post(f'{url}/queue', json=payload)
    assert response.status_code == 400 and response.json()['error']['key'] == 'server.reference.snapref_mode'

    tall = upload(client, url, make_png((2, 4000), '#142471'))
    wide = upload(client, url, make_png((4000, 2), '#99187a'))
    oversized = body(tall, count=2)
    oversized['reference']['subjects'][1]['id'] = wide['id']
    response = client.post(f'{url}/queue', json=oversized)
    assert response.status_code == 400 and response.json()['error']['key'] == 'server.reference.stitch_size'
    assert runtime.comfy.uploads == []
