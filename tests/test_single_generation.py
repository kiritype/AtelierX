"""Single free-prompt generation uses the existing service worker without external requests."""

import io

import pytest
from PIL import Image

from atelierx.image import library
from atelierx.image.uuid_migration import resolve
from test_image import FakeComfy


def _png():
    out = io.BytesIO()
    Image.new('RGB', (32, 24), (60, 120, 180)).save(out, format='PNG')
    return out.getvalue()


def _setup(client):
    wid = client.post('/api/works', json={'name': 'A blank work'}).json()['id']
    runtime = client.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = FakeComfy()
    return wid, runtime


@pytest.mark.parametrize('service', ['comfyui', 'novelai', 'pixai'])
def test_single_generation_saves_and_restores_without_character(unlocked, monkeypatch, service):
    client = unlocked
    wid, runtime = _setup(client)
    adapter = runtime.services[service]
    sent = []
    monkeypatch.setattr(adapter, 'busy', lambda: False)
    monkeypatch.setattr(
        adapter, 'submit', lambda job: (sent.append(job['snapshot']), {'id': 'remote-id', 'record': {}})[1]
    )
    monkeypatch.setattr(adapter, 'poll', lambda job, request: {'image': _png()})
    request = {
        'service': service,
        'positive': 'two people beside a lake',
        'negative': 'blur',
        'settings': {'seed': 17},
    }
    response = client.post(f'/api/works/{wid}/image/single', json=request)
    assert response.status_code == 200, response.text
    job_id = response.json()['job_id']
    job = runtime.queue.get(job_id)
    assert job['kind'] == 'single' and job['work_id'] == wid
    assert 'character_id' not in job and job['review_requested'] is False
    assert job['snapshot']['positive'] == request['positive']
    assert job['snapshot']['negative'] == request['negative']
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done' and sent[0]['settings']['seed'] == 17
    runs = client.get(f'/api/works/{wid}/image/single/runs').json()['runs']
    assert runs[0]['id'] == job_id and runs[0]['status'] == 'done'
    assert runs[0]['request']['positive'] == request['positive']
    assert runs[0]['path'].startswith(f'_single/{wid}/')
    assert client.get(runs[0]['image_url']).status_code == 200
    record = runtime.gallery.metadata(runs[0]['path'])
    assert record['schema_version'] == 2 and record['kind'] == 'single'
    runtime.remove_finished(job_id)
    saved = client.get(f'/api/works/{wid}/image/single/runs').json()['runs']
    assert saved[0]['id'] == job_id and saved[0]['request']['settings']['seed'] == 17
    assert saved[0]['actual']['positive'] == request['positive']
    assert saved[0]['actual']['negative'] == request['negative']
    assert saved[0]['actual']['settings']['seed'] == 17


def test_single_cancel_retry_failure_and_queue_resume(unlocked, monkeypatch):
    client = unlocked
    wid, runtime = _setup(client)
    body = {'positive': 'a city at dusk', 'service': 'comfyui', 'settings': {'seed': 3}}
    first = client.post(f'/api/works/{wid}/image/single', json=body).json()['job_id']
    assert client.post(f'/api/image/jobs/{first}/cancel').status_code == 200
    assert runtime.queue.get(first)['status'] == 'cancelled'
    retried = client.post(f'/api/image/jobs/{first}/retry').json()['job_id']
    assert retried != first
    assert runtime.queue.get(retried)['snapshot']['request']['positive'] == body['positive']
    adapter = runtime.services['comfyui']
    monkeypatch.setattr(adapter, 'busy', lambda: False)
    monkeypatch.setattr(adapter, 'submit', lambda job: (_ for _ in ()).throw(RuntimeError('fake failure')))
    job = runtime.queue.get(retried)
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'failed' and runtime.paused
    again = client.post(f'/api/image/jobs/{retried}/retry').json()['job_id']
    assert client.post('/api/image/queue/resume').json()['paused'] is False
    assert runtime.queue.get(again)['status'] == 'queued'
    runs = client.get(f'/api/works/{wid}/image/single/runs').json()['runs']
    assert {row['status'] for row in runs} == {'cancelled', 'failed', 'queued'}


def test_single_validation_rejects_empty_and_unsupported_settings(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    url = f'/api/works/{wid}/image/single'
    assert client.post(url, json={'positive': ''}).status_code == 400
    for service in ('comfyui', 'novelai', 'pixai'):
        response = client.post(
            url, json={'positive': 'test', 'service': service, 'settings': {'unused_option': 1}}
        )
        assert response.status_code == 400
        assert response.json()['error']['key'] == 'server.single.unsupported_settings'
    assert runtime.queue.queued_count() == 0


def test_single_preset_common_and_actual_snapshot_survive_preset_changes(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    work = runtime.works.get(wid)
    library.save_item(
        runtime.paths,
        work,
        'common',
        'work',
        'sunlit',
        {'name': 'Sunlit', 'prompt': ['warm daylight # note'], 'target': 'positive'},
    )
    library.save_item(
        runtime.paths,
        work,
        'common',
        'work',
        'avoid',
        {'name': 'Avoid', 'prompt': ['blurry'], 'target': 'negative'},
    )
    library.save_preset(
        runtime.paths,
        'soft',
        {
            'service': 'comfyui',
            'family': 'anima',
            'settings': {'cfg': 6.5},
            'common': ['sunlit', 'avoid'],
            'artist': {'positive': 'gentle color', 'negative': 'darkness'},
        },
    )
    first = client.post(
        f'/api/works/{wid}/image/single',
        json={
            'service': 'comfyui',
            'positive': 'forest',
            'negative': 'noise',
            'preset_id': 'soft',
            'settings': {'seed': 27},
        },
    )
    assert first.status_code == 200, first.text
    first_job = runtime.queue.get(first.json()['job_id'])
    snapshot = first_job['snapshot']
    assert snapshot['positive'] == 'warm daylight, forest, gentle color'
    assert snapshot['negative'] == 'blurry, noise, darkness'
    run = client.get(f'/api/works/{wid}/image/single/runs').json()['runs'][0]
    assert run['actual']['positive'] == snapshot['positive']
    assert run['actual']['settings']['cfg'] == 6.5
    assert 'model_loader' not in run['actual']['settings']
    (runtime.paths.data / 'image' / 'presets' / f'{resolve(runtime.paths, "presets", "soft")}.json').unlink()
    second = client.post(
        f'/api/works/{wid}/image/single',
        json={
            'service': 'comfyui',
            'positive': run['actual']['positive'],
            'negative': run['actual']['negative'],
            'settings': run['actual']['settings'],
        },
    )
    assert second.status_code == 200, second.text
    repeated = runtime.queue.get(second.json()['job_id'])['snapshot']
    assert repeated['positive'] == snapshot['positive'] and repeated['negative'] == snapshot['negative']
    assert repeated['settings'] == snapshot['settings']


@pytest.mark.parametrize('service', ['comfyui', 'novelai', 'pixai'])
def test_gallery_regeneration_keeps_single_kind_and_history(unlocked, monkeypatch, service):
    client = unlocked
    wid, runtime = _setup(client)
    adapter = runtime.services[service]
    monkeypatch.setattr(adapter, 'busy', lambda: False)
    monkeypatch.setattr(adapter, 'submit', lambda job: {'id': 'fake-id', 'record': {}})
    monkeypatch.setattr(adapter, 'poll', lambda job, request: {'image': _png()})
    client.put('/api/image/review/settings', json={'enabled': True})

    first = client.post(
        f'/api/works/{wid}/image/single',
        json={
            'service': service,
            'positive': 'a lantern at dusk',
            'settings': {'seed': 17},
        },
    ).json()['job_id']
    paths = []
    for index in range(3):
        job = runtime.queue.get(first) if index == 0 else runtime.jobs[-1]
        assert job['kind'] == 'single' and job['service'] == service
        assert job.get('review_requested') is False
        job['status'] = 'running'
        runtime.run_job(job)
        assert job['status'] == 'done', job.get('error')
        path = runtime.gallery.metadata(job['image_url'].removeprefix('/api/image/files/'))
        assert path['kind'] == 'single' and path['service'] == service
        assert path['work_id'] == wid and path['request']['positive'] == 'a lantern at dusk'
        paths.append(job['image_url'].removeprefix('/api/image/files/'))
        if index < 2:
            response = client.post('/api/image/gallery/regenerate', json={'items': [paths[-1]]})
            assert response.status_code == 200, response.text
            assert response.json()['reviewing'] is False
            fresh = runtime.jobs[-1]
            assert fresh['seed'] != job['seed']
            assert fresh['snapshot']['settings']['seed'] == fresh['seed']
            assert fresh['snapshot']['request']['settings']['seed'] == 17

    assert all(path.startswith(f'_single/{wid}/') for path in paths)
    for job in list(runtime.jobs):
        runtime.remove_finished(job['id'])
    saved = client.get(f'/api/works/{wid}/image/single/runs').json()['runs']
    assert {run['path'] for run in saved} == set(paths)
    assert not runtime.rounds.rounds


def test_missing_character_identity_cannot_create_none_folder(unlocked):
    _, runtime = _setup(unlocked)
    with pytest.raises(ValueError):
        runtime.save_result(
            {
                'id': 'invalid',
                'work_id': 'W001',
                'character_id': None,
                'outfit_id': 'O001',
                'expression_id': 'E001',
            },
            _png(),
            {},
            'fake-id',
        )
    assert not (runtime.paths.output / 'W001' / 'None').exists()
