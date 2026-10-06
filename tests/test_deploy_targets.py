"""Deployment targets (decision 0023): settings with vault references, a connection check, a work's choice."""

import httpx

from test_deploy_s3 import FakeBucket


def _target(**change):
    return {
        'name': '내 R2',
        'kind': 'r2',
        'account_id': 'abc123',
        'bucket': 'rp-images',
        'access_key_id': 'secret:deploy-main-id',
        'secret_access_key': 'secret:deploy-main-secret',
        'public_url': 'https://img.example.com/',
        'path_format': '',
        **change,
    }


def test_targets_keep_vault_references_and_check_the_connection(unlocked):
    c = unlocked
    assert c.get('/api/image/deploy/targets').json()['targets'] == []
    saved = c.put('/api/image/deploy/targets', json={'targets': {'main': _target()}})
    assert saved.status_code == 200
    (target,) = saved.json()['targets']
    assert target['public_url'] == 'https://img.example.com'
    assert target['path_format'] == '{work}/{character}/{outfit}/{expression}'
    assert target['ready'] is False  # the keys are not in the vault yet

    check = c.post('/api/image/deploy/targets/main/check')
    assert check.status_code == 400 and 'Register the access key' in check.json()['error']['text']

    c.post('/api/vault', json={'name': 'deploy-main-id', 'kind': 'api_key', 'value': 'key-id'})
    c.post('/api/vault', json={'name': 'deploy-main-secret', 'kind': 'api_key', 'value': 'secret'})
    assert c.get('/api/image/deploy/targets').json()['targets'][0]['ready'] is True

    runtime = c.app.state.app.image
    bucket = FakeBucket(bucket='rp-images')
    original = runtime.deploy_targets.client
    runtime.deploy_targets.client = lambda ident, transport=None: original(ident, httpx.MockTransport(bucket))
    assert c.post('/api/image/deploy/targets/main/check').json() == {'ok': True}
    assert str(bucket.requests[-1].url).startswith('https://abc123.r2.cloudflarestorage.com/rp-images?')

    bucket.fail = (403, 'AccessDenied')
    refused = c.post('/api/image/deploy/targets/main/check')
    assert refused.status_code == 502 and 'no permission' in refused.json()['error']['text']


def test_bad_target_settings_are_refused(unlocked):
    c = unlocked
    for change in (
        {'bucket': 'No_Caps'},
        {'account_id': ''},
        {'access_key_id': 'plain-key'},
        {'public_url': 'ftp://x'},
        {'path_format': '{work}/{nope}'},
        {'path_format': '{work}//{expression}'},
    ):
        response = c.put('/api/image/deploy/targets', json={'targets': {'main': _target(**change)}})
        assert response.status_code == 400, change
    assert c.put('/api/image/deploy/targets', json={'targets': {'Bad ID': _target()}}).status_code == 400


def test_a_work_picks_a_target_and_may_have_its_own_path_format(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    url = f'/api/works/{wid}/image/deploy'
    assert c.get(url).json() == {'schema_version': 1, 'target': None, 'path_format': None}
    saved = c.put(url, json={'target': 'main', 'path_format': 'cards/{character}/{expression}'})
    assert saved.json()['path_format'] == 'cards/{character}/{expression}'
    assert c.get(url).json()['target'] == 'main'
    assert c.put(url, json={'target': 'main', 'path_format': '{x}'}).status_code == 400
