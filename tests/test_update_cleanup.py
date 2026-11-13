import threading
from pathlib import Path

import pytest

from atelierx.core import update_cleanup as module
from atelierx.core.fsutil import read_json, write_json
from atelierx.core.updater import Updater, finish_update


def seed(paths):
    folder = paths.state / 'update'
    backup = folder / 'backups' / ('a' * 32)
    backup.mkdir(parents=True)
    for n in range(4):
        (backup / f'{n}.dll').write_bytes(b'old')
    (folder / 'new').mkdir()
    (folder / 'new' / 'temporary').write_bytes(b'new')
    (folder / 'AtelierX-9.9.9-windows-x64.zip').write_bytes(b'package')
    (folder / 'backup-before-v9.9.9.zip').write_bytes(b'user data backup')
    (paths.root / 'personal.old').write_bytes(b'personal')
    write_json(folder / 'pending.json', {'version': 'v9.9.9', 'from': '0.6.0'})
    write_json(folder / 'result.json', {'state': 'ok', 'backup_id': 'a' * 32})
    return folder, backup


def test_cleanup_is_detached_from_startup_and_the_next_preparation(paths):
    folder, backup = seed(paths)
    finish_update(paths)
    assert backup.is_dir() and not (folder / 'new').exists()
    (folder / 'new').mkdir()
    (folder / 'new' / 'next-version').write_bytes(b'next')
    (folder / 'AtelierX-9.9.9-windows-x64.zip').write_bytes(b'next package')
    up = Updater(paths)
    up.forget_result()  # Dismissing the success toast must not lose pending cleanup.
    up.cleanup.run()
    assert not backup.exists()
    assert (folder / 'new' / 'next-version').read_bytes() == b'next'
    assert (folder / 'AtelierX-9.9.9-windows-x64.zip').read_bytes() == b'next package'
    assert (folder / 'backup-before-v9.9.9.zip').read_bytes() == b'user data backup'
    assert (paths.root / 'personal.old').read_bytes() == b'personal'
    assert up.cleanup.status() == {'state': 'done'}
    up.cleanup.run()


def test_failed_or_interrupted_cleanup_retries_without_losing_the_task(paths, monkeypatch):
    folder, backup = seed(paths)
    finish_update(paths)
    original = module.remove_tree

    def locked(path, stop):
        if path == backup:
            raise PermissionError('file in use')
        return original(path, stop)

    monkeypatch.setattr(module, 'remove_tree', locked)
    up = Updater(paths)
    up.cleanup.run()
    assert up.cleanup.status()['state'] == 'failed'
    assert list((folder / 'cleanup').glob('*/manifest.json'))
    monkeypatch.setattr(module, 'remove_tree', original)
    up.cleanup.stop_event.set()
    up.cleanup.run()
    assert backup.exists()
    # A new process uses the durable manifest even after pending.json and result.json are gone.
    Updater(paths).cleanup.run()
    assert not backup.exists()


def test_shutdown_waits_for_cleanup_to_stop_and_prevents_late_ready_callback(paths, monkeypatch):
    seed(paths)
    finish_update(paths)
    entered = threading.Event()

    def remove(path, stop):
        entered.set()
        assert stop.wait(2)
        raise module.CleanupStopped

    monkeypatch.setattr(module, 'remove_tree', remove)
    up = Updater(paths)
    up.cleanup.start()
    assert entered.wait(2)
    up.cleanup.stop()
    assert not up.cleanup.thread.is_alive()
    old_thread = up.cleanup.thread
    up.cleanup.start()
    assert up.cleanup.thread is old_thread
    assert up.cleanup.tasks()


def test_interrupted_staging_is_retried_before_new_update_can_start(paths, monkeypatch):
    folder, backup = seed(paths)
    original = Path.rename

    def fail(path, target):
        if path.name == 'new':
            raise PermissionError('locked')
        return original(path, target)

    monkeypatch.setattr(Path, 'rename', fail)
    finish_update(paths)
    assert (folder / 'pending.json').exists()
    up = Updater(paths)
    monkeypatch.setattr(up, 'packaged', lambda: True)
    with pytest.raises(Exception, match='Restart the app'):
        up.start()
    up.forget_result()
    up.cleanup.run()
    assert backup.exists()
    monkeypatch.setattr(Path, 'rename', original)
    finish_update(paths)
    assert not (folder / 'pending.json').exists()
    assert read_json(folder / 'result.json')['state'] == 'ok'
    Updater(paths).cleanup.run()
    assert not backup.exists()


def test_backup_prunes_excluded_trees_and_restores_every_included_byte(paths, monkeypatch):
    import hashlib
    import os
    import zipfile

    folder, _ = seed(paths)
    for name in (
        'config/a.json',
        'data/work.md',
        'data/image.PNG',
        'state/jobs.json',
        'state/desktop.lock',
        'state/logs/a.log',
    ):
        path = paths.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode() * 20)
    walked = []
    scandir = os.scandir

    def observe(path):
        walked.append(Path(path))
        return scandir(path)

    monkeypatch.setattr(os, 'scandir', observe)
    archive = Updater(paths)._backup('v9.9.9')
    assert folder not in walked and paths.state / 'logs' not in walked
    with zipfile.ZipFile(archive) as source:
        assert set(source.namelist()) == {
            'config/a.json',
            'data/work.md',
            'data/image.PNG',
            'state/jobs.json',
        }
        for name in source.namelist():
            assert (
                hashlib.sha256(source.read(name)).digest()
                == hashlib.sha256((paths.root / name).read_bytes()).digest()
            )
        assert source.getinfo('data/image.PNG').compress_type == zipfile.ZIP_STORED
        assert source.getinfo('data/work.md').compress_type == zipfile.ZIP_DEFLATED


@pytest.mark.parametrize(
    'doc', [[], {'schema_version': 1, 'state': 'queued', 'backup_id': '../personal.old'}]
)
def test_invalid_cleanup_manifest_preserves_files_and_does_not_break_status(paths, doc):
    folder, backup = seed(paths)
    finish_update(paths)
    manifest = next((folder / 'cleanup').glob('*/manifest.json'))
    write_json(manifest, doc)
    cleanup = Updater(paths).cleanup
    cleanup.run()
    assert cleanup.status()['state'] == 'failed'
    assert backup.exists() and (paths.root / 'personal.old').read_bytes() == b'personal'


def test_desktop_waits_for_window_load_before_cleanup(paths, monkeypatch):
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock

    from atelierx import desktop

    paths.state.mkdir(parents=True)
    cleanup = Mock()
    callbacks = []

    class Loaded:
        def __iadd__(self, callback):
            callbacks.append(callback)
            return self

    def show(**kwargs):
        cleanup.start.assert_not_called()
        for callback in callbacks:
            callback()
        cleanup.start.assert_called_once()

    fake_webview = SimpleNamespace(
        settings={},
        start=show,
        create_window=lambda *a, **k: SimpleNamespace(events=SimpleNamespace(loaded=Loaded())),
    )
    monkeypatch.setitem(sys.modules, 'webview', fake_webview)
    monkeypatch.setattr(sys, 'argv', ['atelierx'])
    monkeypatch.setattr(desktop.AppPaths, 'for_runtime', lambda root: paths)
    monkeypatch.setattr(desktop, 'configure_logging', lambda root: None)
    monkeypatch.setattr(desktop, 'check_resources', lambda p: None)
    monkeypatch.setattr(
        desktop,
        'build_app',
        lambda *a, **k: SimpleNamespace(
            state=SimpleNamespace(app=SimpleNamespace(updater=SimpleNamespace(cleanup=cleanup)))
        ),
    )
    monkeypatch.setattr(
        desktop.uvicorn, 'Server', lambda config: SimpleNamespace(started=True, run=lambda **k: None)
    )
    monkeypatch.setattr(desktop.uvicorn, 'Config', lambda *a, **k: None)
    monkeypatch.setattr(desktop, 'show_error', lambda message: pytest.fail(message))
    assert desktop.main() == 0
    cleanup.stop.assert_called_once()
