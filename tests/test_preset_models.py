"""Exact dependency identities, opt-in downloads and reconnecting without overwriting edits (#329)."""

import hashlib
import io
import json
import zipfile

from atelierx.image import library
from atelierx.image.resource_refs import references, safe_name

BODY = b'fixture model'
SHA = hashlib.sha256(BODY).hexdigest()


def setup(unlocked, paths, tmp_path, monkeypatch, *, known=True):
    rt = unlocked.app.state.app.image
    folder = tmp_path / 'loras'
    folder.mkdir()
    catalog = {'connected': True, 'loras': [], 'model_entries': {}}
    monkeypatch.setattr(rt.comfy, 'catalog', lambda: catalog)
    monkeypatch.setattr(rt.installs, 'model_folders', lambda: {'loras': [str(folder)]})
    monkeypatch.setattr(rt.model_downloads, 'start', lambda: None)
    plan = {
        'model': {'id': 1, 'name': 'Ink', 'license': {}},
        'versions': [
            {
                'id': 2,
                'name': 'v2',
                'family': 'anima',
                'files': [
                    {
                        'id': 3,
                        'name': 'ink.safetensors',
                        'sha256': SHA,
                        'size': len(BODY),
                        'kind': 'loras',
                        'url': 'https://civitai.com/api/download/models/2',
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(rt.model_downloads, 'read', lambda _: plan)
    for ident in ('first', 'second'):
        library.save_preset(
            paths,
            ident,
            {
                'name': ident,
                'service': 'comfyui',
                'family': 'anima',
                'settings': {'loras': [{'name': 'old/ink.safetensors', 'strength_model': 0.5}]},
                'resources': [
                    {
                        'kind': 'lora',
                        'name': 'old/ink.safetensors',
                        'sha256': SHA,
                        'model_id': 1,
                        'version_id': 2,
                        'file_id': 3,
                        'size': len(BODY),
                    }
                ]
                if known
                else [],
            },
        )
    ids = [p['id'] for p in library.presets(paths)]
    return rt, folder, catalog, ids


def test_downloads_are_explicit_deduplicated_and_survive_dialog_close(unlocked, paths, tmp_path, monkeypatch):
    rt, folder, catalog, ids = setup(unlocked, paths, tmp_path, monkeypatch)
    checked = rt.preset_models.check(ids)
    assert len(checked['items']) == 1
    row = checked['items'][0]
    assert row['downloadable'] and len(row['presets']) == 2 and not rt.model_downloads.jobs
    response = unlocked.post(
        '/api/image/presets/resources/download', json={'token': checked['token'], 'selected': []}
    )
    assert response.status_code == 400 and not rt.model_downloads.jobs
    for _ in range(2):
        rt.preset_models.download(checked['token'], [row['id']])
    assert len(rt.model_downloads.jobs) == 1
    # Completed downloads are remembered by their verified digest. No open dialog is needed to reconnect.
    local = folder / 'renamed.safetensors'
    local.write_bytes(BODY)
    catalog['loras'] = ['renamed.safetensors']
    rt.model_library.remember(local, SHA, {})
    rt.preset_models.pending.clear()
    rt.preset_models.reconcile()
    assert all(p['settings']['loras'][0]['name'] == 'renamed.safetensors' for p in library.presets(paths))


def test_hash_match_reuses_renamed_file_and_preserves_strength(unlocked, paths, tmp_path, monkeypatch):
    rt, folder, catalog, ids = setup(unlocked, paths, tmp_path, monkeypatch)
    (folder / 'different.safetensors').write_bytes(BODY)
    catalog['loras'] = ['different.safetensors']
    result = rt.preset_models.check(ids)
    assert result['items'][0]['status'] == 'ready' and not rt.model_downloads.jobs
    preset = library.presets(paths)[0]
    assert preset['settings']['loras'] == [{'name': 'different.safetensors', 'strength_model': 0.5}]
    assert preset['resources'][0]['sha256'] == SHA


def test_same_name_wrong_hash_is_not_ready_and_manual_link_refuses_it(unlocked, paths, tmp_path, monkeypatch):
    rt, folder, catalog, ids = setup(unlocked, paths, tmp_path, monkeypatch)
    (folder / 'wrong.safetensors').write_bytes(b'wrong content')
    catalog['loras'] = ['wrong.safetensors']
    checked = rt.preset_models.check(ids)
    response = unlocked.post(
        '/api/image/presets/resources/link',
        json={
            'token': checked['token'],
            'id': checked['items'][0]['id'],
            'kind': 'lora',
            'name': 'wrong.safetensors',
        },
    )
    assert response.status_code == 400 and response.json()['error']['key'] == 'server.presets.models.hash'


def test_offline_and_remote_do_not_claim_no_missing_models(unlocked, paths, tmp_path, monkeypatch):
    rt, _, catalog, ids = setup(unlocked, paths, tmp_path, monkeypatch)
    catalog['connected'] = False
    assert rt.preset_models.check(ids)['items'][0]['status'] == 'unknown'
    catalog['connected'] = True
    rt.comfy.url = 'http://192.0.2.3:8188'
    checked = rt.preset_models.check(ids)
    assert not checked['local'] and not checked['items'][0]['downloadable']


def test_changed_reference_refuses_stale_download_and_never_reconnects_over_edit(
    unlocked, paths, tmp_path, monkeypatch
):
    rt, folder, catalog, ids = setup(unlocked, paths, tmp_path, monkeypatch)
    checked = rt.preset_models.check(ids)
    preset = library.presets(paths)[0]
    preset['settings']['loras'][0]['name'] = 'chosen-by-user.safetensors'
    library.save_preset(paths, preset['id'], preset)
    response = unlocked.post(
        '/api/image/presets/resources/download',
        json={'token': checked['token'], 'selected': [checked['items'][0]['id']]},
    )
    assert response.status_code == 409 and not rt.model_downloads.jobs
    local = folder / 'downloaded.safetensors'
    local.write_bytes(BODY)
    rt.model_library.remember(local, SHA, {})
    catalog['loras'] = ['downloaded.safetensors']
    rt.preset_models.status(checked['token'])
    current = next(p for p in library.presets(paths) if p['id'] == preset['id'])
    assert current['settings']['loras'][0]['name'] == 'chosen-by-user.safetensors'


def test_unknown_source_can_be_connected_only_to_a_catalog_file(unlocked, paths, tmp_path, monkeypatch):
    rt, folder, catalog, ids = setup(unlocked, paths, tmp_path, monkeypatch, known=False)
    (folder / 'manual.safetensors').write_bytes(BODY)
    catalog['loras'] = ['manual.safetensors']
    checked = rt.preset_models.check(ids)
    row = checked['items'][0]
    assert row['status'] == 'unverified' and not row['downloadable']
    bad = unlocked.post(
        '/api/image/presets/resources/link',
        json={'token': checked['token'], 'id': row['id'], 'kind': 'lora', 'name': '../outside.safetensors'},
    )
    assert bad.status_code == 400
    result = rt.preset_models.link(checked['token'], row['id'], 'lora', 'manual.safetensors')
    assert result['items'][0]['status'] == 'ready'


def test_resource_identity_survives_zip_and_discards_stale_bindings(unlocked, paths, tmp_path, monkeypatch):
    rt, _, _, ids = setup(unlocked, paths, tmp_path, monkeypatch)
    package = unlocked.get('/api/image/presets/export', params={'ids': ids[0]}).content
    archive = zipfile.ZipFile(io.BytesIO(package))
    assert json.loads(archive.read('atelierx-presets.json'))['schema_version'] == 3
    look = rt.preset_imports.preview(package, {})
    rt.preset_imports.apply(look['token'], {ids[0]: 'copy'})
    assert all(p['resources'][0]['sha256'] == SHA for p in library.presets(paths))
    doc = library.presets(paths)[0]
    doc['settings']['loras'][0]['name'] = 'other.safetensors'
    assert 'sha256' not in references(doc)[0]
    assert not safe_name('../outside') and not safe_name('C:\\outside') and not safe_name('\\\\server\\x')


def test_same_filename_in_another_loader_folder_does_not_satisfy_a_model(
    unlocked, paths, tmp_path, monkeypatch
):
    import pytest

    from atelierx.image.resource_refs import references

    rt, folder, catalog, _ids = setup(unlocked, paths, tmp_path, monkeypatch)
    checkpoints = tmp_path / 'checkpoints'
    checkpoints.mkdir()
    (folder / 'shared.safetensors').write_bytes(b'wrong model')
    good = checkpoints / 'shared.safetensors'
    good.write_bytes(BODY)
    monkeypatch.setattr(
        rt.installs,
        'model_folders',
        lambda: {'diffusion_models': [str(folder)], 'checkpoints': [str(checkpoints)]},
    )
    catalog['model_entries'] = {
        'shared.safetensors': {'filename': 'shared.safetensors', 'loader': 'UNETLoader'},
        'checkpoint::shared.safetensors': {
            'filename': 'shared.safetensors',
            'loader': 'CheckpointLoaderSimple',
        },
    }
    rt.model_library.remember(good, SHA, {})
    doc = {
        'service': 'comfyui',
        'settings': {'model': 'shared.safetensors'},
        'resources': [{'kind': 'model', 'name': 'shared.safetensors', 'sha256': SHA}],
    }
    assert references(doc)[0]['model_type'] == 'diffusion_model'
    with pytest.raises(ValueError):
        rt.preset_models.validate(doc, doc['settings'], catalog)
    doc['settings']['model'] = 'checkpoint::shared.safetensors'
    rt.preset_models.validate(doc, doc['settings'], catalog)
