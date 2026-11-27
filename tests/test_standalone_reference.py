import io
import json
import zipfile

from starlette.testclient import TestClient

from atelierx.api.app import build_app
from conftest import FAST_KDF
from test_anima_reference_adapters import AdapterComfy, body, make_png, queue
from test_reference_generation import png, upload

REFERENCE = '/api/image/reference'


def test_image_only_references_survive_restart_and_are_reusable(paths, monkeypatch):
    app_url = 'http://127.0.0.1:8765'
    first_bytes, second_bytes = png(), make_png((36, 48), '#336699')
    with TestClient(build_app(paths, kdf=FAST_KDF), base_url=app_url) as client:
        assert client.get(f'{REFERENCE}/assets').status_code == 401
        assert (
            client.post('/api/auth/setup', json={'password': 'pass1234', 'language': 'ko'}).status_code == 200
        )
        runtime = client.app.state.app.image
        runtime.set_paused(True)
        runtime.comfy = AdapterComfy()
        first = upload(client, REFERENCE, first_bytes)
        second = upload(client, REFERENCE, second_bytes)
        revision = client.get(f'{REFERENCE}/draft').json()['revision']
        draft = {
            'schema_version': 1,
            'positive': 'evening in a bookshop',
            'negative': 'blur',
            'family': 'anima',
            'parameters': {
                'anima': {'settings': {'seed': 271}, 'preset': ''},
                'moss': {'settings': {}, 'preset': ''},
            },
            'reference': first,
            'guidance': '4.5',
            'animaEngine': 'snapref',
            'snaprefMode': 'char',
            'description': '',
            'second': {'reference': second, 'description': 'holds a book'},
            'firstOnRight': True,
        }
        invalid = {
            **draft,
            'parameters': {**draft['parameters'], 'anima': {'settings': {'loras': [None]}, 'preset': ''}},
        }
        assert (
            client.put(f'{REFERENCE}/draft', json={'draft': invalid, 'revision': revision}).status_code == 400
        )
        saved = client.put(f'{REFERENCE}/draft', json={'draft': draft, 'revision': revision})
        assert saved.status_code == 200, saved.text
        assert (
            client.put(f'{REFERENCE}/draft', json={'draft': draft, 'revision': revision}).status_code == 409
        )
        assert client.get('/api/image/single/draft').json()['draft'] is None

        payload = body(first, count=2)
        payload['reference']['snapref_mode'] = 'char'
        payload['reference']['subjects'][1]['id'] = second['id']
        job = queue(client, REFERENCE, payload, runtime)
        assert job['work_id'] is None
        job['status'] = 'running'
        runtime.run_job(job)
        assert job['status'] == 'done', job.get('error')
        scoped_gallery = runtime.gallery.for_prefixes(('_standalone',))
        with monkeypatch.context() as before_scan:
            before_scan.setattr(scoped_gallery, 'snapshot_items', list)
            run = client.get(f'{REFERENCE}/runs').json()['runs'][0]
        path = run['path']
        record = runtime.gallery.metadata(path)
        assert path.startswith('_standalone/')
        assert record['schema_version'] == 9 and record['work_id'] is None
        assert sorted(raw for _, raw, _ in runtime.comfy.uploads) == sorted([first_bytes, second_bytes])
        assert client.get('/api/image/single/runs').json() == {'runs': []}
        assert client.get('/api/works').json()['works'] == []
        runtime.remove_finished(job['id'])

    with TestClient(build_app(paths, kdf=FAST_KDF), base_url=app_url) as client:
        assert client.post('/api/auth/unlock', json={'password': 'pass1234'}).status_code == 200
        runtime = client.app.state.app.image
        runtime.set_paused(True)
        runtime.comfy = AdapterComfy()
        assert client.get(f'{REFERENCE}/draft').json() == saved.json()
        assert client.get(first['url']).content == first_bytes
        assert client.get(second['url']).content == second_bytes
        assert client.get(f'{REFERENCE}/assets').json()['assets'] == sorted(
            [first, second], key=lambda asset: asset['id']
        )
        restored = client.get(f'{REFERENCE}/runs').json()['runs'][0]
        assert restored['status'] == 'done' and restored['path'] == path and restored['seed'] == 271
        assert restored['reference']['subjects'][1]['url'] == second['url']
        assert restored['reference']['engine'] == 'snapref'
        assert restored['reference']['snapref_mode'] == 'char'
        assert client.get(restored['image_url']).content.startswith(b'\x89PNG')
        for same_seed in (True, False):
            response = client.post(f'{REFERENCE}/regenerate', json={'path': path, 'same_seed': same_seed})
            assert response.status_code == 200, response.text
            replay = runtime.queue.get(response.json()['job_id'])
            assert (replay['seed'] == 271) is same_seed
            assert replay['work_id'] is None and replay['snapshot']['reference'] == record['reference']
        for include in ('false', 'true'):
            response = client.get(f'{REFERENCE}/export', params={'path': path, 'include_reference': include})
            assert response.status_code == 200, response.text
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                files = {name for name in archive.namelist() if name.startswith('input/')}
                if include == 'true':
                    assert {archive.read(name) for name in files} == {first_bytes, second_bytes}
                else:
                    assert not files
                assert json.loads(archive.read('generation.json'))['work_id'] is None


def test_image_only_and_work_reference_scopes_stay_separate(unlocked):
    client = unlocked
    runtime = client.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = AdapterComfy()
    work = client.post('/api/works', json={'id': '_standalone', 'name': 'Reserved root'})
    assert work.status_code == 201, work.text
    wid = work.json()['id']
    in_work = f'/api/works/{wid}/image/reference'
    standalone_asset = upload(client, REFERENCE, png())
    work_asset = upload(client, in_work, make_png((24, 40), '#224477'))
    assert client.get(f'{REFERENCE}/assets').json() == {'assets': [standalone_asset]}
    for url, foreign in ((REFERENCE, work_asset), (in_work, standalone_asset)):
        assert client.get(f'{url}/assets/{foreign["id"]}').status_code == 404
        assert client.post(f'{url}/queue', json=body(foreign)).status_code == 400
    for url, asset, other in ((REFERENCE, standalone_asset, in_work), (in_work, work_asset, REFERENCE)):
        job = queue(client, url, body(asset), runtime)
        job['status'] = 'running'
        runtime.run_job(job)
        assert job['status'] == 'done', job.get('error')
        path = client.get(f'{url}/runs').json()['runs'][0]['path']
        assert client.post(f'{other}/assets', json={'gallery_path': path}).status_code == 400
        assert client.post(f'{other}/regenerate', json={'path': path}).status_code == 400
        assert client.get(f'{other}/export', params={'path': path}).status_code == 400
        assert all(run['path'] != path for run in client.get(f'{other}/runs').json()['runs'])
