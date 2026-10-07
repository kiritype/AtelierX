"""Uploading adopted images (decision 0023): the plan's paths and states, the upload, unchanged files, clashes."""

import time

import httpx

from test_deploy_s3 import FakeBucket
from test_image import FakeComfy, stop_worker


def _setup(c):
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    stop_worker(runtime)
    runtime.gpu.admit = lambda kind: None
    targets = [{'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': e} for e in ('smile', 'laugh')]
    c.post(f'/api/works/{wid}/image/jobs', json={'targets': targets})
    for job in list(runtime.jobs):
        job['status'] = 'running'
        runtime.run_job(job)
    paths = [i['path'] for i in c.get('/api/image/gallery', params={'work': wid}).json()['results']]
    c.post('/api/image/gallery/review', json={'verdict': 'pass', 'items': [{'path': p} for p in paths]})

    c.post('/api/vault', json={'name': 'deploy-main-id', 'kind': 'api_key', 'value': 'key-id'})
    c.post('/api/vault', json={'name': 'deploy-main-secret', 'kind': 'api_key', 'value': 'secret'})
    target = {
        'name': 'R2',
        'account_id': 'acct',
        'bucket': 'images',
        'access_key_id': 'secret:deploy-main-id',
        'secret_access_key': 'secret:deploy-main-secret',
        'public_url': 'https://img.example.com',
    }
    assert c.put('/api/image/deploy/targets', json={'targets': {'main': target}}).status_code == 200
    bucket = FakeBucket()
    runtime.deploy.transport = httpx.MockTransport(bucket)
    return wid, runtime, bucket


def _set_outfit_code(c, wid, code):
    url = f'/api/works/{wid}/image/characters/C001'
    loaded = c.get(url).json()
    loaded['design']['outfits']['o01']['code'] = code
    assert (
        c.put(url, json={'design': loaded['design'], 'base_revision': loaded['revision']}).status_code == 200
    )


def _wait(c, run_id):
    for _ in range(100):
        run = c.get(f'/api/image/deploy/runs/{run_id}').json()
        if run['status'] not in ('running', 'cancelling'):
            return run
        time.sleep(0.05)
    raise AssertionError('upload did not finish')


def test_plan_upload_and_unchanged_files(unlocked):
    c = unlocked
    wid, _runtime, bucket = _setup(c)
    body = {'work': wid, 'target': 'main'}

    # Without an outfit code the path cannot be made.
    plan = c.post('/api/image/deploy/plan', json=body).json()
    assert plan['counts'] == {'no_code': 2}

    _set_outfit_code(c, wid, 'uniform')
    plan = c.post('/api/image/deploy/plan', json=body).json()
    paths = sorted(r['path'] for r in plan['rows'])
    assert paths == [f'{wid}/C001/uniform/002.webp', f'{wid}/C001/uniform/003.webp']
    assert plan['counts'] == {'new': 2}
    assert plan['rows'][0]['url'].startswith(f'https://img.example.com/{wid}/C001/uniform/')

    run = c.post('/api/image/deploy/upload', json=body).json()
    run = _wait(c, run['id'])
    assert run['status'] == 'done' and run['done'] == 2 and all(r['ok'] for r in run['results'])
    assert sorted(bucket.objects) == paths
    body_bytes, _ = bucket.objects[paths[0]]
    assert body_bytes[:4] == b'RIFF' and body_bytes[8:12] == b'WEBP'
    assert bucket.requests[-1].headers['content-type'] == 'image/webp'
    assert 'cache-control' not in bucket.requests[-1].headers

    # The same files again: nothing to upload.
    plan = c.post('/api/image/deploy/plan', json=body).json()
    assert plan['counts'] == {'unchanged': 2}
    assert c.post('/api/image/deploy/upload', json=body).status_code == 400

    # A changed file at the same path is an overwrite.
    key = paths[0]
    bucket.objects[key] = (b'old', 'different')
    plan = c.post('/api/image/deploy/plan', json=body).json()
    assert {r['path']: r['status'] for r in plan['rows']}[key] == 'overwrite'


def test_edited_paths_clashes_ratings_and_retrying_only_some(unlocked):
    c = unlocked
    wid, _runtime, bucket = _setup(c)
    _set_outfit_code(c, wid, 'uniform')
    body = {'work': wid, 'target': 'main'}
    plan = c.post('/api/image/deploy/plan', json=body).json()
    smile = next(r for r in plan['rows'] if r['expression_id'] == 'smile')
    laugh = next(r for r in plan['rows'] if r['expression_id'] == 'laugh')

    # Two images at one path: both held back.
    clash = {**body, 'paths': {laugh['source']: smile['path']}}
    assert c.post('/api/image/deploy/plan', json=clash).json()['counts'] == {'clash': 2}
    edited = c.post('/api/image/deploy/plan', json={**body, 'paths': {laugh['source']: 'cards/laugh'}}).json()
    assert {r['path'] for r in edited['rows']} == {smile['path'], 'cards/laugh.webp'}
    bad = c.post('/api/image/deploy/plan', json={**body, 'paths': {laugh['source']: 'a/../b'}})
    assert bad.status_code == 400

    assert c.post('/api/image/deploy/plan', json={**body, 'ratings': ['nsfw']}).json()['rows'] == []
    # Every rating unticked is no rating at all (#164); null or left out is every rating.
    assert c.post('/api/image/deploy/plan', json={**body, 'ratings': []}).json()['rows'] == []
    assert len(c.post('/api/image/deploy/plan', json={**body, 'ratings': None}).json()['rows']) == 2
    assert c.post('/api/image/deploy/upload', json={**body, 'ratings': []}).status_code == 400
    assert bucket.objects == {}
    # A work's own path format.
    c.put(f'/api/works/{wid}/image/deploy', json={'target': 'main', 'path_format': 'chat/{expression}'})
    plan = c.post('/api/image/deploy/plan', json={'work': wid}).json()
    assert {r['path'] for r in plan['rows']} == {'chat/002.webp', 'chat/003.webp'}

    run = c.post('/api/image/deploy/upload', json={'work': wid, 'only': ['chat/003.webp']}).json()
    run = _wait(c, run['id'])
    assert [r['path'] for r in run['results']] == ['chat/003.webp']
    assert list(bucket.objects) == ['chat/003.webp']


def test_the_gallery_range_holds_for_plan_and_upload(unlocked):
    """The character or outfit chosen in the gallery limits what is planned and sent (#163)."""
    c = unlocked
    wid, _runtime, bucket = _setup(c)
    _set_outfit_code(c, wid, 'uniform')
    body = {'work': wid, 'target': 'main'}

    def rows(**scope):
        return len(c.post('/api/image/deploy/plan', json={**body, **scope}).json()['rows'])

    assert rows(character='C001') == 2
    assert rows(character='C001', outfit='o01') == 2
    assert rows(character='C999') == 0
    assert rows(character='C001', outfit='o99') == 0
    # Uploading outside the range sends nothing.
    assert c.post('/api/image/deploy/upload', json={**body, 'character': 'C999'}).status_code == 400
    assert bucket.objects == {}


def test_a_failed_file_is_reported_and_the_rest_go_on(unlocked):
    c = unlocked
    wid, runtime, bucket = _setup(c)
    _set_outfit_code(c, wid, 'uniform')
    real = bucket.__call__

    def flaky(request):
        if request.method == 'PUT' and request.url.path.endswith('002.webp'):
            return httpx.Response(500, content=b'<Error><Code>InternalError</Code></Error>')
        return real(request)

    runtime.deploy.transport = httpx.MockTransport(flaky)
    run = _wait(c, c.post('/api/image/deploy/upload', json={'work': wid, 'target': 'main'}).json()['id'])
    assert run['status'] == 'done'
    failed = [r for r in run['results'] if not r['ok']]
    assert (
        len(failed) == 1
        and failed[0]['path'].endswith('002.webp')
        and 'HTTP 500' in failed[0]['error']['text']
    )
    assert len(bucket.objects) == 1
