"""A failed live import restores the pre-import files before requests resume (#265)."""

import io
import json
import zipfile

import pytest

from atelierx.api import package_routes
from atelierx.core import packages


def _upload(client, raw):
    response = client.post('/api/packages/upload', content=raw, headers={'Content-Type': 'application/zip'})
    assert response.status_code == 200, response.text
    return response.json()['token']


def _bad_conversion(_server):
    raise RuntimeError('injected post-import conversion failure')


def test_settings_import_rolls_back_legacy_json_and_reopens_api(unlocked):
    server = unlocked.app.state.app
    original = (server.paths.data / 'image' / 'expressions.json').read_bytes()
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr(
            'atelierx-package.json',
            json.dumps(
                {
                    'format': 'atelierx-package',
                    'schema_version': 1,
                    'kind': 'settings',
                    'areas': ['image_library'],
                }
            ),
        )
        archive.writestr('settings/image_library/expressions.json', '{malformed')
    token = _upload(unlocked, package.getvalue())
    with pytest.raises(ValueError, match='malformed image data'):
        unlocked.post('/api/packages/settings/import', json={'token': token, 'areas': ['image_library']})
    assert (server.paths.data / 'image' / 'expressions.json').read_bytes() == original
    assert unlocked.get('/api/image/library/expressions').status_code == 200


def test_work_package_conversion_failure_removes_new_work_and_reopens_api(unlocked, monkeypatch):
    server = unlocked.app.state.app
    wid = unlocked.post('/api/samples/single/install').json()['id']
    raw = unlocked.post(
        '/api/packages/works/export', json={'ids': [wid], 'options': {'images': 'none'}}
    ).content
    before = {path.name for path in server.paths.works.iterdir()}
    token = _upload(unlocked, raw)
    monkeypatch.setattr(package_routes, 'migrate_runtime_guarded', _bad_conversion)
    with pytest.raises(RuntimeError, match='post-import'):
        unlocked.post('/api/packages/works/import', json={'token': token, 'works': [{'index': 0}]})
    assert {path.name for path in server.paths.works.iterdir()} == before
    assert unlocked.get('/api/works').status_code == 200


def test_settings_import_restores_vault_memory_as_well_as_file(unlocked):
    server = unlocked.app.state.app
    assert (
        unlocked.post(
            '/api/vault',
            json={
                'name': 'synthetic',
                'kind': 'other',
                'value': 'incoming-synthetic',
                'note': '',
            },
        ).status_code
        == 200
    )
    exported = unlocked.post(
        '/api/packages/settings/export', json={'areas': ['vault', 'image_library']}
    ).content
    assert (
        unlocked.post(
            '/api/vault',
            json={
                'name': 'synthetic',
                'kind': 'other',
                'value': 'current-synthetic',
                'note': '',
            },
        ).status_code
        == 200
    )
    before_file = server.vault.path.read_bytes()
    before_memory = json.dumps(server.vault._secrets, sort_keys=True)
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported)) as source, zipfile.ZipFile(changed, 'w') as target:
        for name in source.namelist():
            data = b'{malformed' if name == 'settings/image_library/expressions.json' else source.read(name)
            target.writestr(name, data)
    token = _upload(unlocked, changed.getvalue())
    with pytest.raises(ValueError, match='malformed image data'):
        unlocked.post(
            '/api/packages/settings/import',
            json={
                'token': token,
                'areas': ['vault', 'image_library'],
                'vault_password': 'pass1234',
            },
        )
    assert server.vault.path.read_bytes() == before_file
    assert json.dumps(server.vault._secrets, sort_keys=True) == before_memory
    assert unlocked.get('/api/works').status_code == 200


def test_interrupt_during_work_extraction_removes_partial_folder(unlocked, monkeypatch):
    server = unlocked.app.state.app
    wid = unlocked.post('/api/samples/single/install').json()['id']
    raw = unlocked.post(
        '/api/packages/works/export', json={'ids': [wid], 'options': {'images': 'none'}}
    ).content
    token = _upload(unlocked, raw)
    before = {path.name for path in server.paths.works.iterdir()}

    def interrupt(*_args):
        raise KeyboardInterrupt('synthetic extraction interruption')

    monkeypatch.setattr(packages, '_write_member', interrupt)
    with pytest.raises(KeyboardInterrupt, match='synthetic extraction'):
        server.packages.import_works(token, [{'index': 0}])
    assert {path.name for path in server.paths.works.iterdir()} == before


def test_reused_import_token_does_not_undo_previous_success(unlocked):
    wid = unlocked.post('/api/samples/single/install').json()['id']
    raw = unlocked.post(
        '/api/packages/works/export', json={'ids': [wid], 'options': {'images': 'none'}}
    ).content
    token = _upload(unlocked, raw)
    done = unlocked.post('/api/packages/works/import', json={'token': token, 'works': [{'index': 0}]})
    assert done.status_code == 200, done.text
    imported = done.json()['imported'][0]['id']
    assert (
        unlocked.post(
            '/api/packages/works/import', json={'token': token, 'works': [{'index': 0}]}
        ).status_code
        == 404
    )
    assert unlocked.get(f'/api/works/{imported}').status_code == 200
