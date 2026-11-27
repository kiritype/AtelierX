"""MossRef readiness, graphs and replay through a ComfyUI HTTP double."""

import io
import json
import zipfile

import pytest

from atelierx.image import comfy_locate, moss_reference
from test_reference_generation import ReferenceComfy, png, upload

MODEL = 'moss\\moss_image_sft_int8_convrot.safetensors'
ENCODER = 'moss\\qwen3.5_9b_int8_convrot.safetensors'
VAE = 'moss\\flux2-vae.safetensors'


class MossComfy(ReferenceComfy):
    url = 'http://comfy.example.invalid:8188'

    def __init__(self):
        super().__init__()
        self.schemas = {
            moss_reference.NODE: {
                'input': {
                    'required': {
                        'model': ['MODEL'],
                        'vae': ['VAE'],
                        'reference_image': ['IMAGE'],
                        'adapter': [[moss_reference.WEIGHT, 'custom_adapter_path']],
                        'role': [['auto', 'character']],
                        'cfg_reference': [['positive', 'both']],
                        'ref_edge': ['INT'],
                    },
                    'optional': {
                        'positive': ['CONDITIONING'],
                        'role_2': [['auto', 'character']],
                        'role_3': [['auto', 'character']],
                        'foundation_dir': ['STRING'],
                        'custom_adapter_path': ['STRING'],
                        'ref_attn_bias': ['FLOAT'],
                        'target_strength': ['FLOAT'],
                    },
                },
                'output': ['MODEL'],
            },
            moss_reference.EDIT_NODE: {
                'input': {
                    'required': {
                        'clip': ['CLIP'],
                        'prompt': ['STRING'],
                        'edit_format': ['COMBO', {'options': ['ai-toolkit', 'Moss-Image-Edit']}],
                        'images': [
                            'COMFY_AUTOGROW_V3',
                            {'template': {'prefix': 'image_', 'input': {'required': {'image': ['IMAGE']}}}},
                        ],
                        'image_strength': ['FLOAT'],
                    },
                    'optional': {'vae': ['VAE']},
                },
                'output': ['CONDITIONING'],
            },
        }

    def catalog(self):
        base = 'moss/moss_image_base_bf16.safetensors'
        checkpoint = 'checkpoint::moss/moss_image_sft_bf16.safetensors'
        return {
            **super().catalog(),
            'models': [base, MODEL, checkpoint, 'moss/renamed-sft.safetensors'],
            'text_encoders': ['qwen.safetensors', ENCODER],
            'vaes': ['flux2-vae_small.safetensors', VAE],
            'loras': ['style.safetensors'],
            'samplers': ['euler'],
            'schedulers': ['sgm_uniform'],
            'clip_types': ['moss_image'],
            'model_entries': {checkpoint: {'loader': 'CheckpointLoaderSimple', 'filename': 'checkpoint'}},
            'nodes': {'moss': True, 'moss_slg': True},
        }

    def request(self, path, body=None, raw=False, timeout=15):
        if path.startswith('/object_info/'):
            name = path.rsplit('/', 1)[-1]
            return {name: self.schemas[name]} if name in self.schemas else {}
        return super().request(path, body, raw, timeout)


@pytest.fixture
def moss(unlocked, request):
    client = unlocked
    runtime = client.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = MossComfy()
    if getattr(request, 'param', False):
        return client, runtime, '/api/image/reference'
    work_id = client.post('/api/works', json={'name': 'MossRef test'}).json()['id']
    return client, runtime, f'/api/works/{work_id}/image/reference'


def test_moss_reference_status_checks_schemas_and_local_files(moss, tmp_path, monkeypatch):
    client, runtime, _ = moss

    def get():
        return client.get('/api/image/reference/status?family=moss').json()

    assert client.get('/api/image/reference/status').json() == {
        'ready': True,
        'node_ready': True,
        'weights_ready': True,
    }
    assert get() == {
        'ready': True,
        'node_ready': True,
        'edit_node_ready': True,
        'weights_ready': None,
        'foundation_ready': None,
        'models': [MODEL],
        'text_encoders': [ENCODER],
        'vaes': [VAE],
    }
    runtime.comfy.url = 'http://127.0.0.1:8188'
    monkeypatch.setattr(
        comfy_locate,
        'running',
        lambda url: {
            'arguments': ['--base-directory', str(tmp_path)],
            'comfy_path': str(tmp_path / 'another'),
        },
    )
    missing = get()
    assert not missing['ready'] and not missing['weights_ready'] and not missing['foundation_ready']
    root = tmp_path / 'models' / 'moss_ref'
    foundation = root / moss_reference.FOUNDATION
    foundation.mkdir(parents=True)
    (root / moss_reference.WEIGHT).touch()
    (foundation / 'adapter_config.json').touch()
    assert get()['weights_ready'] is True and get()['ready'] is False
    (foundation / 'adapter_model.safetensors').touch()
    assert get()['ready'] is True
    runtime.comfy.schemas[moss_reference.EDIT_NODE]['input']['required']['images'][1]['template'][
        'prefix'
    ] = 'different_'
    incompatible = get()
    assert incompatible['edit_node_ready'] is False and incompatible['ready'] is False


def test_running_models_root_respects_comfy_overrides(tmp_path, monkeypatch):
    local = {'comfy_path': str(tmp_path / 'install'), 'arguments': []}
    monkeypatch.setattr(comfy_locate, 'running', lambda url: local)
    url = 'http://127.0.0.1:8188'
    base = tmp_path / 'base'
    models = tmp_path / 'custom_models'
    assert comfy_locate.running_models_root(url) == tmp_path / 'install' / 'models'
    local['arguments'] = ['--base-directory', str(base)]
    assert comfy_locate.running_models_root(url) == base / 'models'
    local['arguments'] = [f'--models-directory={models}', '--base-directory', str(base)]
    assert comfy_locate.running_models_root(url) == models
    local['arguments'].extend(['--models-directory', 'relative/models'])
    assert comfy_locate.running_models_root(url) is None
    assert comfy_locate.running_models_root('http://comfy.example.invalid:8188') is None


def test_moss_reference_workflow_and_replay(moss):
    client, runtime, url = moss
    asset = upload(client, url, png())
    settings = {'family': 'moss', 'model': MODEL, 'text_encoder': ENCODER, 'vae': VAE, 'seed': 271}
    base = {
        'positive': 'Use Picture 1 for the hair. Walking under the stars.',
        'negative': 'blur',
        'settings': settings,
        'reference': {'id': asset['id'], 'engine': 'mossref'},
    }
    for changed in (
        {**base, 'moss_layout': {'mode': 'layout'}},
        {**base, 'reference': {**base['reference'], 'role': 'style'}},
        {**base, 'settings': {**settings, 'family': 'anima'}},
        {**base, 'settings': {**settings, 'model': 'moss/moss_image_base_bf16.safetensors'}},
        {**base, 'settings': {**settings, 'text_encoder': 'qwen.safetensors'}},
        {**base, 'settings': {**settings, 'moss_slg': True}},
        {**base, 'settings': {**settings, 'loras': [{'name': 'style.safetensors'}]}},
    ):
        assert client.post(f'{url}/queue', json=changed).status_code == 400
    assert runtime.comfy.uploads == []

    reply = client.post(f'{url}/queue', json={**base, 'settings': {'family': 'moss', 'seed': 271}})
    assert reply.status_code == 200, reply.text
    job = runtime.queue.get(reply.json()['job_id'])
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')
    graph = runtime.comfy.prompts[0]
    nodes = {node['class_type']: ident for ident, node in graph.items()}
    assert 'ModelSamplingAuraFlow' not in nodes and 'SkipLayerGuidanceDiTSimple' not in nodes
    assert graph[nodes['EmptyFlux2LatentImage']]['inputs']['batch_size'] == 1
    image = [nodes['LoadImage'], 0]
    positive = [nodes[moss_reference.EDIT_NODE], 0]
    assert graph[positive[0]]['inputs'] == {
        'clip': [nodes['CLIPLoader'], 0],
        'prompt': base['positive'],
        'images.image_0': image,
        'image_strength': 0.05,
        'edit_format': 'ai-toolkit',
    }
    adapter = graph[nodes[moss_reference.NODE]]['inputs']
    assert adapter['positive'] == positive and adapter['reference_image'] == image
    assert adapter['role'] == 'auto' and adapter['adapter'] == moss_reference.WEIGHT
    sampler = graph[nodes['KSampler']]['inputs']
    assert sampler['positive'] == positive and sampler['model'] == [nodes[moss_reference.NODE], 0]
    assert (sampler['steps'], sampler['cfg'], sampler['scheduler']) == (35, 3.5, 'sgm_uniform')

    run = client.get(f'{url}/runs').json()['runs'][0]
    assert run['actual']['settings']['family'] == 'moss' and run['reference']['engine'] == 'mossref'
    response = client.get(f'{url}/export', params={'path': run['path'], 'include_reference': 'true'})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        exported = json.loads(archive.read('workflow.json'))
        ui = {node['type']: node for node in exported['nodes']}
        encoder = ui[moss_reference.EDIT_NODE]
        assert encoder['widgets_values'] == [base['positive'], 'ai-toolkit', 0.05]
        assert encoder['inputs'][1]['name'] == 'images.image_0'
        assert encoder['inputs'][1]['link'] and not encoder['inputs'][2]['link']
        assert ui[moss_reference.NODE]['inputs'][5]['link'] in encoder['outputs'][0]['links']
        assert archive.read(f'input/{runtime.comfy.uploads[0][0]}') == png()
        assert json.loads(archive.read('prompt.json')) == graph
        record = json.loads(archive.read('generation.json'))
        assert record['schema_version'] == 7
        assert record['reference']['foundation_revision']

    replay = client.post(f'{url}/regenerate', json={'path': run['path'], 'same_seed': True})
    assert replay.status_code == 200, replay.text
    copy = runtime.queue.get(replay.json()['job_id'])
    assert copy['seed'] == 271 and copy['snapshot']['reference'] == job['snapshot']['reference']
    copy['status'] = 'running'
    runtime.run_job(copy)
    assert copy['status'] == 'done' and runtime.comfy.prompts[1] == graph


@pytest.mark.parametrize('moss', [False, True], indirect=True, ids=['work', 'image_only'])
def test_moss_reference_retry_keeps_original_graph_after_setup(moss, monkeypatch):
    client, runtime, url = moss
    asset = upload(client, url, png())
    reply = client.post(
        f'{url}/queue',
        json={
            'positive': 'Use Picture 1. Watering plants.',
            'settings': {'family': 'moss', 'seed': 815},
            'reference': {'id': asset['id'], 'engine': 'mossref'},
        },
    )
    assert reply.status_code == 200, reply.text
    job = runtime.queue.get(reply.json()['job_id'])
    request = runtime.comfy.request

    def missing_foundation(path, *args, **kwargs):
        if path == '/history/p1':
            return {
                'p1': {
                    'status': {
                        'status_str': 'error',
                        'messages': [
                            [
                                'execution_error',
                                {'exception_message': 'Moss-Image-Edit foundation directory not found'},
                            ],
                        ],
                    }
                }
            }
        return request(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(runtime.comfy, 'request', missing_foundation)
        job['status'] = 'running'
        runtime.run_job(job)
    assert job['status'] == 'failed'
    assert client.get(f'{url}/runs').json()['runs'][0]['error']['key'] == 'server.reference.moss_files'

    reply = client.post(f'/api/image/jobs/{job["id"]}/retry')
    assert reply.status_code == 200, reply.text
    retry = runtime.queue.get(reply.json()['job_id'])
    assert retry['snapshot'] == job['snapshot'] and retry['seed'] == 815
    assert retry['work_id'] == job['work_id'] and runtime.paused
    retry['status'] = 'running'
    runtime.run_job(retry)
    assert retry['status'] == 'done' and runtime.comfy.prompts[1] == runtime.comfy.prompts[0]
