import base64
import hashlib
import io
import json
import zipfile

import pytest
from PIL import Image

from test_image import FakeComfy


class ReferenceComfy(FakeComfy):
    def __init__(self):
        super().__init__()
        self.node_ready = True
        self.weights_ready = True
        self.uploads = []

    def reference_status(self):
        return {
            'node_ready': self.node_ready,
            'weights_ready': self.weights_ready,
            'ready': self.node_ready and self.weights_ready,
        }

    def upload(self, name, raw, subfolder):
        self.uploads.append((name, raw, subfolder))
        return {'name': name, 'subfolder': subfolder}


@pytest.fixture
def reference_setup(unlocked):
    work_id = unlocked.post('/api/works', json={'name': 'Reference test'}).json()['id']
    runtime = unlocked.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = ReferenceComfy()
    return unlocked, work_id, runtime, f'/api/works/{work_id}/image/reference'


def png():
    out = io.BytesIO()
    Image.new('RGB', (32, 48), '#a37a55').save(out, format='PNG')
    return out.getvalue()


def upload(client, url, raw):
    response = client.post(
        f'{url}/assets',
        json={
            'filename': 'reference.png',
            'data_url': 'data:image/png;base64,' + base64.b64encode(raw).decode(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def request(asset):
    return {
        'service': 'comfyui',
        'positive': 'walking on a rainy street',
        'negative': 'blur',
        'settings': {'family': 'anima', 'seed': 271, 'width': 768, 'height': 1344},
        'reference': {'id': asset['id'], 'guidance': 3.5},
    }


def test_reference_request_save_export_and_regenerate(reference_setup):
    client, wid, runtime, url = reference_setup
    original = png()
    asset = upload(client, url, original)
    assert asset['sha256'] == hashlib.sha256(original).hexdigest()
    assert client.get(asset['url']).content == original
    reply = client.post(f'{url}/queue', json=request(asset))
    assert reply.status_code == 200, reply.text
    job_id = reply.json()['job_id']
    job = runtime.queue.get(job_id)
    assert runtime.comfy.uploads == []
    assert client.get(f'{url}/runs').json()['runs'][0]['reference']['guidance'] == 3.5

    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')
    name, raw, subfolder = runtime.comfy.uploads[0]
    assert raw == original and not subfolder and name.startswith('atelierx-reference-')
    run = client.get(f'{url}/runs').json()['runs'][0]
    assert client.get(f'/api/works/{wid}/image/single/runs').json() == {'runs': []}
    record = runtime.gallery.metadata(run['path'])
    assert record['schema_version'] == 6
    assert record['reference']['id'] == asset['id']
    result = client.get(run['image_url']).content
    with Image.open(io.BytesIO(result)) as image:
        editor = json.loads(image.text['workflow'])
        assert json.loads(image.text['prompt']) == runtime.comfy.prompts[0]
        assert json.loads(image.text['atelierx'])['reference'] == record['reference']
    assert {node['type'] for node in editor['nodes']} >= {'AnimaRefAdapter', 'LoadImage'}

    for include in (False, True):
        response = client.get(
            f'{url}/export', params={'path': run['path'], 'include_reference': str(include).lower()}
        )
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            members = {'result.png', 'workflow.json', 'prompt.json', 'generation.json'}
            if include:
                asset_file = f'input/{name}'
                members.add(asset_file)
                assert archive.read(asset_file) == original
            assert set(archive.namelist()) == members
            assert json.loads(archive.read('workflow.json')) == editor
            assert json.loads(archive.read('prompt.json')) == record['workflow']

    clone = client.post(f'{url}/regenerate', json={'path': run['path'], 'same_seed': True})
    assert clone.status_code == 200, clone.text
    regenerated = runtime.queue.get(clone.json()['job_id'])
    assert regenerated['seed'] == 271 and regenerated['snapshot']['reference'] == record['reference']
    runtime.remove_finished(job_id)
    assert any(r['path'] == run['path'] for r in client.get(f'{url}/runs').json()['runs'])


def test_reference_rejects_disabled_services_bad_inputs_and_missing_dependencies(
    reference_setup, monkeypatch
):
    client, wid, runtime, url = reference_setup
    asset = upload(client, url, png())
    body = request(asset)
    for bad in (
        {**body, 'service': 'novelai'},
        {**body, 'settings': {'family': 'sdxl'}},
        {**body, 'settings': {'family': 'moss'}},
        {**body, 'reference': {'id': asset['id'], 'guidance': True}},
        {**body, 'reference': {'id': asset['id'], 'guidance': 20.1}},
    ):
        assert client.post(f'{url}/queue', json=bad).status_code == 400
    assert (
        client.post(f'{url}/assets', json={'data_url': 'data:image/png;base64,Z29uZQ=='}).status_code == 400
    )
    other = client.post('/api/works', json={'name': 'Other work'}).json()['id']
    assert client.get(asset['url'].replace(wid, other)).status_code == 404
    assert client.post(url.replace(wid, other) + '/queue', json=body).status_code == 400
    with monkeypatch.context() as classified:
        classified.setattr(
            runtime.models, 'classify', lambda catalog: {'models': {'anima\\m.safetensors': 'moss'}}
        )
        mislabeled = {**body, 'settings': {**body['settings'], 'model': 'anima\\m.safetensors'}}
        assert (
            client.post(f'{url}/queue', json=mislabeled).json()['error']['key']
            == 'server.reference.anima_only'
        )
    runtime.comfy.node_ready = False
    assert client.post(f'{url}/queue', json=body).json()['error']['key'] == 'server.reference.missing_node'
    runtime.comfy.node_ready, runtime.comfy.weights_ready = True, False
    assert client.post(f'{url}/queue', json=body).json()['error']['key'] == 'server.reference.missing_weights'
    assert runtime.queue.jobs == [] and runtime.comfy.uploads == []


def test_gallery_reference_keeps_a_copy_and_rejects_other_work(reference_setup):
    client, wid, runtime, url = reference_setup
    original = png()
    relative = f'{wid}/C001/images/o01/smile/example.png'
    path = runtime.gallery.root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(original)
    picked = client.post(f'{url}/assets', json={'gallery_path': relative})
    assert picked.status_code == 200, picked.text
    other = client.post('/api/works', json={'name': 'Other work'}).json()['id']
    assert (
        client.post(url.replace(wid, other) + '/assets', json={'gallery_path': relative}).status_code == 400
    )
    path.unlink()
    assert client.get(picked.json()['url']).content == original
