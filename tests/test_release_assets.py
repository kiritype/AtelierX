import hashlib
import json
from zipfile import ZipFile

import pytest
from tools import release_assets

from atelierx.core.updater import ASSET

VERSION = '0.8.2'
COMMIT = '1' * 40


def _checksum(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.zip.sha256').write_bytes(f'{digest}  {path.name}\r\n'.encode('ascii'))


@pytest.fixture
def assets(tmp_path, monkeypatch):
    files = {name: f'Original {name}'.encode() for name in release_assets.UPSTREAM}
    monkeypatch.setattr(
        release_assets, 'UPSTREAM', {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    )
    monkeypatch.setattr(
        release_assets.subprocess, 'check_output', lambda args: files[args[-1].split(':', 1)[1]]
    )
    app, adapter = release_assets.archive_names(VERSION)
    with ZipFile(tmp_path / app, 'w') as archive:
        archive.writestr('AtelierX/AtelierX.exe', b'app')
        archive.writestr('AtelierX/BUILD-MANIFEST.json', json.dumps({'version': VERSION, 'commit': COMMIT}))
    _checksum(tmp_path / app)
    assert release_assets.build_adapter(tmp_path, tmp_path, VERSION).name == adapter
    return tmp_path, app, adapter


def test_release_verifies_both_pairs_and_only_app_zip_matches_the_updater(assets):
    folder, app, adapter = assets
    assert set(release_assets.verify_candidate(folder, VERSION, COMMIT)) == {app, adapter}
    assert ASSET.fullmatch(app)
    assert not ASSET.fullmatch(adapter)


def test_release_rejects_checksum_that_names_the_other_asset(assets):
    folder, app, adapter = assets
    (folder / f'{app}.sha256').write_bytes((folder / f'{adapter}.sha256').read_bytes())
    with pytest.raises(ValueError, match='must name its own ZIP'):
        release_assets.verify_candidate(folder, VERSION, COMMIT)


def test_release_rejects_extra_adapter_files_even_with_a_matching_checksum(assets):
    folder, _, adapter = assets
    with ZipFile(folder / adapter, 'a') as archive:
        archive.writestr('ComfyUI-Anima-Ref-Adapter/input.png', b'reference image')
    _checksum(folder / adapter)
    with pytest.raises(ValueError, match='unexpected or duplicate ZIP members'):
        release_assets.verify_candidate(folder, VERSION, COMMIT)


def test_release_rejects_wrong_candidate_commit(assets):
    folder, _, _ = assets
    with pytest.raises(ValueError, match='was not built from'):
        release_assets.verify_candidate(folder, VERSION, '2' * 40)


def test_release_keeps_adapter_source_out_of_the_app_zip(assets):
    folder, app, _ = assets
    with ZipFile(folder / app, 'a') as archive:
        archive.writestr('AtelierX/_internal/comfy_nodes/ComfyUI-Anima-Ref-Adapter/__init__.py', b'node')
    _checksum(folder / app)
    with pytest.raises(ValueError, match='contains the standalone adapter node'):
        release_assets.verify_candidate(folder, VERSION, COMMIT)
