"""Image-only emotion batches through the existing reference workers and saved history."""

import io
import json

import pytest
from PIL import Image
from starlette.testclient import TestClient

from atelierx.api.app import build_app
from atelierx.image import job_queue, moss_reference
from conftest import FAST_KDF
from image_ids import image_id
from test_anima_reference_adapters import AdapterComfy, body
from test_moss_reference import ENCODER, MODEL, VAE, MossComfy
from test_reference_generation import png, upload

REFERENCE = '/api/image/reference'
EMOTIONS = f'{REFERENCE}/emotions'
APP_URL = 'http://127.0.0.1:8765'


def _save_item(client, kind, slug, item, revision=None):
    response = client.put(f'/api/image/library/{kind}/{slug}', json={'item': item, 'revision': revision})
    assert response.status_code == 200, response.text
    return response.json()[image_id(client, kind, slug)]


def _emotions(client):
    smile = _save_item(client, 'expressions', 'batch_smile', {'name': 'Smile', 'prompt': ['gentle smile']})
    frown = _save_item(client, 'expressions', 'batch_frown', {'name': 'Frown', 'prompt': ['deep frown']})
    return [smile, frown]


def _request(emotions, family='anima', composition=None):
    return {
        'family': family,
        'expression_ids': [item['id'] for item in emotions],
        'composition': composition or {'mode': 'none'},
    }


def _preview(client, payload):
    response = client.post(f'{EMOTIONS}/preview', json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert isinstance(preview['revision'], str) and preview['revision']
    return preview


def _runtime(client, comfy):
    runtime = client.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = comfy
    return runtime


def _queued(client, runtime, payload, preview):
    response = client.post(f'{EMOTIONS}/queue', json=payload)
    assert response.status_code == 200, response.text
    accepted = response.json()
    jobs = runtime.queue.select(
        lambda job: (job['snapshot'].get('reference_batch') or {}).get('id') == accepted['batch_id']
    )
    assert accepted['count'] == len(jobs) == len(preview['rows'])
    assert accepted['job_id'] == jobs[0]['id']
    indices = []
    for job, row in zip(jobs, preview['rows'], strict=True):
        snapshot = job['snapshot']
        assert snapshot['positive'] == row['positive']
        assert snapshot['negative'] == row['negative']
        assert job['work_id'] is None and snapshot['work_id'] is None
        batch = snapshot['reference_batch']
        assert batch['count'] == len(jobs)
        indices.append(batch['index'])
        for key in ('expression_id', 'expression_name', 'composition_id', 'composition_name'):
            assert batch[key] == row[key]
    assert indices == list(range(len(jobs)))
    return accepted, jobs


def _run(runtime, job):
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')


def test_emotion_composition_preview_uses_global_library_and_family(unlocked):
    client = unlocked
    close = _save_item(
        client,
        'compositions',
        'batch_close',
        {'name': 'Close', 'prompt': ['tight portrait'], 'negative': ['wide angle'], 'targets': ['anima']},
    )
    other = _save_item(
        client,
        'compositions',
        'batch_moss',
        {'name': 'Moss shot', 'prompt': ['outdoors'], 'negative': ['indoors'], 'targets': ['moss']},
    )
    emotions = [
        _save_item(
            client,
            'expressions',
            'batch_bright',
            {'name': 'Bright', 'prompt': ['bright smile'], 'negative': ['tears'], 'composition': close['id']},
        ),
        _save_item(
            client,
            'expressions',
            'batch_worried',
            {
                'name': 'Worried',
                'prompt': ['worried eyes'],
                'negative': ['laughter'],
                'composition': other['id'],
            },
        ),
    ]
    none = _preview(client, _request(emotions))
    assert [row['expression_id'] for row in none['rows']] == [item['id'] for item in emotions]
    assert all(row['composition_id'] is None for row in none['rows'])
    assert (
        'bright smile' in none['rows'][0]['positive'] and 'tight portrait' not in none['rows'][0]['positive']
    )
    assert none['rows'][0]['negative'] == 'tears'
    linked = _preview(client, _request(emotions, composition={'mode': 'linked'}))
    first, second = linked['rows']
    assert first['expression_name'] == 'Bright'
    assert first['composition_name'] == 'Close' and first['composition_id'] == close['id']
    assert not first['composition_omitted']
    assert first['positive'] == 'tight portrait, bright smile'
    assert first['negative'] == 'wide angle, tears'
    assert 'worried eyes' in second['positive'] and 'outdoors' not in second['positive']
    assert second['composition_omitted'] and second['negative'] == 'laughter'

    unlinked = _emotions(client)[0]
    absent = _save_item(
        client,
        'expressions',
        'batch_absent',
        {'name': 'Absent shot', 'prompt': ['smiling'], 'composition': '00000000-0000-0000-0000-000000000000'},
    )
    linked_status = _preview(client, _request([unlinked, absent], composition={'mode': 'linked'}))
    assert [row['composition_omitted'] for row in linked_status['rows']] == [False, True]
    assert all(row['composition_id'] is None for row in linked_status['rows'])

    explicit = _preview(client, _request(emotions, composition={'mode': 'library', 'id': close['id']}))
    assert all(
        row['composition_id'] == close['id'] and not row['composition_omitted'] for row in explicit['rows']
    )
    assert all(
        'tight portrait' in row['positive'] and 'wide angle' in row['negative'] for row in explicit['rows']
    )
    assert (
        client.post(
            f'{EMOTIONS}/preview', json=_request(emotions, composition={'mode': 'library', 'id': other['id']})
        ).status_code
        == 400
    )
    layout = _save_item(
        client,
        'compositions',
        'batch_layout',
        {
            'name': 'Layout',
            'moss_layout': {
                'schema_version': 1,
                'mode': 'layout',
                'scene': 'studio',
                'items': [],
                'width': 1024,
                'height': 1024,
            },
        },
    )
    with_layout = _save_item(
        client,
        'expressions',
        'batch_layout_joy',
        {'name': 'Smile', 'prompt': ['smile'], 'composition': layout['id']},
    )
    moss_linked = _preview(client, _request([with_layout], 'moss', {'mode': 'linked'}))
    assert moss_linked['rows'][0]['composition_omitted'] and moss_linked['rows'][0]['positive'] == 'smile'
    assert (
        client.post(
            f'{EMOTIONS}/preview',
            json=_request([with_layout], 'moss', {'mode': 'library', 'id': layout['id']}),
        ).status_code
        == 400
    )
    assert client.get('/api/works').json()['works'] == []


def test_emotion_batch_rejects_stale_preview_and_never_admits_a_partial_batch(unlocked, monkeypatch):
    client = unlocked
    runtime = _runtime(client, AdapterComfy())
    escaped = _save_item(client, 'expressions', 'batch_hash', {'name': 'Hash', 'prompt': [r'\#compass']})
    emotions = [escaped, _emotions(client)[1]]
    recipe = _request(emotions)
    first_preview = _preview(client, recipe)
    assert first_preview['rows'][0]['positive'] == '#compass'
    asset = upload(client, REFERENCE, png())
    options = body(asset)
    base = {**recipe, 'settings': options['settings'], 'reference': options['reference']}
    _save_item(
        client,
        'expressions',
        'batch_frown',
        {'name': 'Frown updated', 'prompt': ['a quiet frown']},
        emotions[1]['revision'],
    )
    stale = client.post(f'{EMOTIONS}/queue', json={**base, 'preview_revision': first_preview['revision']})
    assert stale.status_code == 409, stale.text
    preview = _preview(client, recipe)
    assert preview['revision'] != first_preview['revision']
    valid = {**base, 'preview_revision': preview['revision']}
    bad_reference = {**options['reference'], 'subjects': body(asset, count=2)['reference']['subjects']}
    for changed in (
        {**valid, 'reference': bad_reference},
        {**valid, 'expression_ids': [emotions[0]['id'], '00000000-0000-0000-0000-000000000000']},
        {
            **valid,
            'reference': {
                'engine': 'snapref',
                'subjects': [{'id': '0' * 64, 'slot': 'a', 'position': 'center'}],
            },
        },
    ):
        assert client.post(f'{EMOTIONS}/queue', json=changed).status_code == 400
        assert not runtime.queue.jobs
    assert not runtime.comfy.uploads

    with monkeypatch.context() as limited:
        limited.setattr(job_queue, 'MAX_QUEUED', 1)
        over_limit = client.post(f'{EMOTIONS}/queue', json=valid)
        assert over_limit.status_code == 400, over_limit.text
        assert not runtime.queue.jobs

    def fail_queue_write():
        raise OSError('queue write failed')

    with monkeypatch.context() as disk:
        disk.setattr(runtime.queue, 'persist', fail_queue_write)
        with pytest.raises(OSError, match='queue write failed'):
            runtime.enqueue_reference_emotions(valid)
        assert not runtime.queue.jobs

    _, jobs = _queued(
        client,
        runtime,
        {
            **valid,
            'positive': 'user override sentinel',
            'negative': 'user negative sentinel',
            'preset_id': 'user preset sentinel',
        },
        preview,
    )
    assert all(not job['snapshot'].get('generation_preset') for job in jobs)


def test_anima_emotion_batch_recovers_saved_group_after_retry_and_restart(paths):
    with TestClient(build_app(paths, kdf=FAST_KDF), base_url=APP_URL) as client:
        assert (
            client.post('/api/auth/setup', json={'password': 'pass1234', 'language': 'ko'}).status_code == 200
        )
        runtime = _runtime(client, AdapterComfy())
        emotions = _emotions(client)
        recipe = _request(emotions)
        assert client.get('/api/works').json()['works'] == []
        preview = _preview(client, recipe)
        asset = upload(client, REFERENCE, png())
        options = body(asset, engine='anima_v2')
        payload = {
            **recipe,
            'settings': options['settings'],
            'reference': options['reference'],
            'preview_revision': preview['revision'],
        }
        accepted, (first, failure) = _queued(client, runtime, payload, preview)
        assert all(job['seed'] == job['snapshot']['settings']['seed'] == 271 for job in (first, failure))
        runtime.queue.update(failure, status='failed')
        retry = client.post(f'/api/image/jobs/{failure["id"]}/retry')
        assert retry.status_code == 200, retry.text
        second = runtime.queue.get(retry.json()['job_id'])
        assert second['id'] != failure['id'] and second['seed'] == failure['seed']
        assert second['snapshot'] == failure['snapshot'] and second['work_id'] is None
        assert runtime.queue.paused
        for job in (first, second):
            _run(runtime, job)
        runs = client.get(f'{REFERENCE}/runs').json()['runs']
        completed = {run['id']: run for run in runs if run['status'] == 'done'}
        assert set(completed) == {first['id'], second['id']}
        for job in (first, second):
            run = completed[job['id']]
            assert run['reference_batch'] == job['snapshot']['reference_batch']
            assert run['path'].startswith('_standalone/')
            record = runtime.gallery.metadata(run['path'])
            assert record['schema_version'] == 10 and record['work_id'] is None
            assert record['reference_batch'] == run['reference_batch']
            with Image.open(io.BytesIO(client.get(run['image_url']).content)) as image:
                assert json.loads(image.text['atelierx'])['reference_batch'] == run['reference_batch']
        runtime.remove_finished()
        assert not runtime.queue.jobs

    with TestClient(build_app(paths, kdf=FAST_KDF), base_url=APP_URL) as client:
        assert client.post('/api/auth/unlock', json={'password': 'pass1234'}).status_code == 200
        runs = client.get(f'{REFERENCE}/runs').json()['runs']
        assert {run['id']: run['path'] for run in runs} == {
            key: run['path'] for key, run in completed.items()
        }
        assert {run['reference_batch']['id'] for run in runs} == {accepted['batch_id']}
        assert {run['reference_batch']['expression_id'] for run in runs} == {item['id'] for item in emotions}
        assert all(run['status'] == 'done' and run['seed'] == 271 for run in runs)
        assert client.get('/api/image/single/runs').json() == {'runs': []}
        assert client.get('/api/works').json()['works'] == []


def test_mossref_emotion_batch_executes_the_previewed_text(unlocked):
    client = unlocked
    runtime = _runtime(client, MossComfy())
    emotions = _emotions(client)
    recipe = _request(emotions, family='moss')
    preview = _preview(client, recipe)
    raw = png()
    asset = upload(client, REFERENCE, raw)
    payload = {
        **recipe,
        'settings': {'family': 'moss', 'model': MODEL, 'text_encoder': ENCODER, 'vae': VAE, 'seed': 549},
        'reference': {'id': asset['id'], 'engine': 'mossref'},
        'preview_revision': preview['revision'],
    }
    _, jobs = _queued(client, runtime, payload, preview)
    assert all(job['seed'] == 549 and job['snapshot']['reference']['id'] == asset['id'] for job in jobs)
    _run(runtime, jobs[0])
    graph = runtime.comfy.prompts[0]
    encoder = next(node for node in graph.values() if node['class_type'] == moss_reference.EDIT_NODE)
    assert encoder['inputs']['prompt'] == preview['rows'][0]['positive']
    assert any(node['class_type'] == moss_reference.NODE for node in graph.values())
    assert [uploaded[1] for uploaded in runtime.comfy.uploads] == [raw]
