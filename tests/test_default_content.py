"""Official pack import: global scope, revision checks, dependencies and rollback (#328)."""

import hashlib
import io
import json
import zipfile

import pytest

from atelierx.image import default_content, library
from atelierx.image.util import atomic_json, read_json

CATALOG = 'https://content.example.test/catalog.json'


def package(kind):
    if kind == 'expressions':
        return json.dumps(
            {
                'kind': 'atelierx-prompt-library',
                'schema_version': 1,
                'library': kind,
                'items': {
                    'fixture-smile': {
                        'name': 'Smile',
                        'group': 'happy',
                        'prompt': ['fixture-smile'],
                        'composition': 'fixture-pose',
                    }
                },
                'dependencies': {
                    'compositions': {'fixture-pose': {'name': 'Portrait', 'prompt': ['portrait']}}
                },
            }
        ).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(
            'atelierx-presets.json',
            json.dumps(
                {
                    'kind': 'atelierx-style-presets',
                    'schema_version': 3,
                    'presets': [{'id': 'ink', 'name': 'Ink'}],
                    'common': ['fixture-quality'],
                }
            ),
        )
        archive.writestr(
            'presets/ink.json',
            json.dumps(
                {
                    'schema_version': 4,
                    'name': 'Ink',
                    'service': 'comfyui',
                    'family': 'anima',
                    'settings': {'model': 'old/model.safetensors'},
                    'common': ['fixture-quality'],
                    'resources': [
                        {
                            'kind': 'model',
                            'name': 'old/model.safetensors',
                            'sha256': 'a' * 64,
                            'model_id': 1,
                            'version_id': 2,
                        }
                    ],
                }
            ),
        )
        archive.writestr(
            'common/fixture-quality.json', json.dumps({'name': 'Quality', 'prompt': ['fixture-quality']})
        )
    return buffer.getvalue()


def setup(unlocked, paths, monkeypatch, kind='presets'):
    raw = package(kind)
    pack = {
        'id': 'official-' + kind,
        'kind': kind,
        'version': '2026.11.1',
        'min_app_version': '0.8.0',
        'title': 'Fixture pack',
        'description': 'Test content',
        'author': 'Example',
        'license': 'CC0',
        'url': 'https://content.example.test/pack',
        'size': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
    }
    catalog = {'kind': 'atelierx-default-content', 'schema_version': 1, 'packs': [pack]}
    calls = []

    def fetch(url, limit):
        calls.append(url)
        return json.dumps(catalog).encode() if url == CATALOG else raw

    monkeypatch.setattr(default_content, 'fetch', fetch)
    atomic_json(paths.config / 'image' / 'content-source.json', {'catalog_url': CATALOG})
    manager = unlocked.app.state.app.image.default_content
    return manager, pack, calls


def preview(c, pack):
    response = c.post('/api/image/content/preview', json={'id': pack['id']})
    assert response.status_code == 200, response.text
    return response.json()


def apply(c, look, **overrides):
    choices = {i['key']: 'add' if i['state'] == 'new' else 'skip' for i in look['items']}
    choices.update(overrides)
    return c.post('/api/image/content/import', json={'token': look['token'], 'choices': choices})


@pytest.mark.parametrize('kind', ['presets', 'expressions'])
def test_preview_is_read_only_imports_dependencies_and_reimport_skips_duplicates(
    unlocked, paths, monkeypatch, kind
):
    manager, pack, _ = setup(unlocked, paths, monkeypatch, kind)
    before = {p.relative_to(paths.data): p.read_bytes() for p in paths.data.rglob('*') if p.is_file()}
    look = preview(unlocked, pack)
    assert not manager.receipts.exists()
    assert before == {p.relative_to(paths.data): p.read_bytes() for p in paths.data.rglob('*') if p.is_file()}
    assert all(i['state'] == 'new' for i in look['items'])
    response = apply(unlocked, look)
    assert response.status_code == 200, response.text
    ident = response.json()['written'][0]
    doc = manager._current(kind, ident)
    if kind == 'presets':
        assert doc['resources'][0]['sha256'] == 'a' * 64
        assert manager._current('common', doc['common'][0])['prompt'] == ['fixture-quality']
    else:
        assert manager._current('compositions', doc['composition'])['prompt'] == ['portrait']
    again = preview(unlocked, pack)
    assert all(i['state'] == 'same' for i in again['items'])
    assert apply(unlocked, again).status_code == 400
    assert manager.status()['installed'][0]['items'] == [ident]


def test_user_edits_survive_copy_and_source_version_updates_are_visible(unlocked, paths, monkeypatch):
    manager, pack, _ = setup(unlocked, paths, monkeypatch)
    look = preview(unlocked, pack)
    original = apply(unlocked, look).json()['written'][0]
    doc = manager._current('presets', original)
    doc['name'] = 'My edited ink'
    library.save_preset(paths, original, doc)
    look = preview(unlocked, pack)
    assert look['items'][0]['state'] == 'modified'
    assert apply(unlocked, look).status_code == 400
    result = apply(unlocked, look, **{'presets:ink': 'copy'})
    assert result.status_code == 200, result.text
    copy_id = result.json()['written'][0]
    assert original != copy_id and manager._current('presets', original)['name'] == 'My edited ink'
    assert manager._current('presets', copy_id)['name'] == 'Ink'
    assert preview(unlocked, pack)['items'][0]['state'] == 'same'
    documents, images = manager._read_pack(pack, package('presets'))
    documents['presets']['ink']['name'] = 'Ink revision 2'
    newer = manager._preview({**pack, 'version': '2026.11.2'}, documents, images)
    assert newer['items'][0]['state'] == 'update'
    result = apply(unlocked, newer, **{'presets:ink': 'replace'})
    assert result.status_code == 200
    assert result.json()['written'] == [copy_id]
    assert manager._current('presets', original)['name'] == 'My edited ink'
    assert manager._current('presets', copy_id)['name'] == 'Ink revision 2'
    assert manager.status()['installed'][0]['version'] == '2026.11.2'


def test_dependency_keep_and_copy_preserve_other_users_of_the_common_prompt(unlocked, paths, monkeypatch):
    manager, pack, _ = setup(unlocked, paths, monkeypatch)
    ident = apply(unlocked, preview(unlocked, pack)).json()['written'][0]
    common_id = manager._current('presets', ident)['common'][0]
    library.save_item(
        paths, None, 'common', 'global', common_id, {'name': 'Personal', 'prompt': ['personal']}
    )
    look = preview(unlocked, pack)
    assert {i['key']: i['state'] for i in look['items']} == {
        'presets:ink': 'update',
        'common:fixture-quality': 'modified',
    }
    result = apply(unlocked, look, **{'presets:ink': 'replace', 'common:fixture-quality': 'skip'})
    assert result.status_code == 200
    assert manager._current('common', common_id)['prompt'] == ['personal']
    result = apply(
        unlocked, preview(unlocked, pack), **{'presets:ink': 'replace', 'common:fixture-quality': 'copy'}
    )
    assert result.status_code == 200
    changed_id = manager._current('presets', ident)['common'][0]
    assert changed_id != common_id
    assert manager._current('common', common_id)['prompt'] == ['personal']
    assert manager._current('common', changed_id)['prompt'] == ['fixture-quality']


def test_stale_preview_refuses_overwriting_a_later_edit(unlocked, paths, monkeypatch):
    manager, pack, _ = setup(unlocked, paths, monkeypatch)
    ident = apply(unlocked, preview(unlocked, pack)).json()['written'][0]
    look = preview(unlocked, pack)
    doc = manager._current('presets', ident)
    doc['name'] = 'Edited in another window'
    library.save_preset(paths, ident, doc)
    response = apply(unlocked, look, **{'presets:ink': 'replace'})
    assert response.status_code == 409
    assert manager._current('presets', ident)['name'] == 'Edited in another window'


def test_failed_receipt_write_rolls_back_all_imported_documents(unlocked, paths, monkeypatch):
    manager, pack, _ = setup(unlocked, paths, monkeypatch)
    look = preview(unlocked, pack)
    before = {p.relative_to(paths.data): p.read_bytes() for p in paths.data.rglob('*') if p.is_file()}

    def fail_receipt(path, doc):
        if path == manager.receipts:
            raise OSError('injected write failure')
        atomic_json(path, doc)

    monkeypatch.setattr(default_content, 'atomic_json', fail_receipt)
    with pytest.raises(OSError):
        manager.apply(look['token'], {i['key']: 'add' for i in look['items']})
    assert before == {p.relative_to(paths.data): p.read_bytes() for p in paths.data.rglob('*') if p.is_file()}


def test_corrupt_hash_and_newer_app_requirement_never_change_existing_content(unlocked, paths, monkeypatch):
    manager, pack, calls = setup(unlocked, paths, monkeypatch)
    pack['sha256'] = '0' * 64
    response = unlocked.post('/api/image/content/preview', json={'id': pack['id']})
    assert response.status_code == 400 and response.json()['error']['key'] == 'server.content.hash'
    pack['min_app_version'] = '99.0.0'
    calls.clear()
    response = unlocked.post('/api/image/content/preview', json={'id': pack['id']})
    assert response.status_code == 400 and response.json()['error']['key'] == 'server.content.version'
    assert calls == [CATALOG] and not manager.receipts.exists()


def test_disconnected_source_is_explicit_and_external_pack_urls_are_rejected(unlocked, paths, monkeypatch):
    assert unlocked.get('/api/image/content/status').json()['configured'] is False
    assert unlocked.get('/api/image/content/catalog').json()['error']['key'] == 'server.content.unconfigured'
    manager, pack, _ = setup(unlocked, paths, monkeypatch)
    pack['url'] = 'https://other.example.test/file'
    assert unlocked.get('/api/image/content/catalog').status_code == 400
    assert not manager.receipts.exists()


def test_download_reconnection_is_not_misreported_as_a_user_edit(unlocked, paths, monkeypatch):
    manager, pack, _ = setup(unlocked, paths, monkeypatch)
    ident = apply(unlocked, preview(unlocked, pack)).json()['written'][0]
    doc = manager._current('presets', ident)
    doc['settings']['model'] = 'local/model.safetensors'
    doc['resources'][0]['name'] = 'local/model.safetensors'
    library.save_preset(paths, ident, doc)
    assert preview(unlocked, pack)['items'][0]['state'] == 'same'
    assert read_json(manager.receipts)['schema_version'] == 1


def test_unselected_content_and_its_dependencies_are_not_written(unlocked, paths, monkeypatch):
    manager, pack, _ = setup(unlocked, paths, monkeypatch, 'expressions')
    documents, images = manager._read_pack(pack, package('expressions'))
    documents['expressions']['fixture-sad'] = {
        'name': 'Sad',
        'prompt': ['sad'],
        'composition': 'fixture-wide',
    }
    documents['compositions']['fixture-wide'] = {'name': 'Wide', 'prompt': ['wide']}
    look = manager._preview(pack, documents, images)
    result = apply(unlocked, look, **{'expressions:fixture-sad': 'skip'})
    assert result.status_code == 200
    assert len(result.json()['written']) == 1
    for row in look['items']:
        exists = manager._current(row['kind'], row['target']) is not None
        assert exists == (row['id'] in ('fixture-smile', 'fixture-pose'))


def test_future_preset_format_is_rejected_before_normalization(unlocked, paths, monkeypatch):
    manager, pack, _ = setup(unlocked, paths, monkeypatch)
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package('presets'))) as source, zipfile.ZipFile(output, 'w') as target:
        for name in source.namelist():
            raw = source.read(name)
            if name == 'presets/ink.json':
                doc = json.loads(raw)
                doc['schema_version'] = 99
                raw = json.dumps(doc).encode()
            target.writestr(name, raw)
    raw = output.getvalue()
    pack.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        manager._read_pack(pack, raw)
    assert not manager.receipts.exists()
