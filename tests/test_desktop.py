import socket
import sys

import pytest

from atelierx.core.paths import AppPaths
from atelierx.desktop import bind_loopback, check_resources


def test_runtime_paths_separate_frozen_resources_from_executable_root(monkeypatch, tmp_path):
    bundle = tmp_path / 'bundle'
    executable = tmp_path / 'AtelierX.exe'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(sys, 'executable', str(executable))

    paths = AppPaths.for_runtime()

    assert paths.root == tmp_path
    assert paths.defaults == bundle / 'defaults'
    assert paths.samples == bundle / 'samples'
    assert paths.web == bundle / 'web' / 'dist'


def test_runtime_paths_accept_explicit_data_root_when_frozen(monkeypatch, tmp_path):
    bundle = tmp_path / 'bundle'
    data_root = tmp_path / 'portable-data'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'AtelierX.exe'))

    paths = AppPaths.for_runtime(data_root)

    assert paths.root == data_root.resolve()
    assert paths.defaults == bundle / 'defaults'
    assert paths.samples == bundle / 'samples'
    assert paths.web == bundle / 'web' / 'dist'


def test_bind_loopback_returns_live_local_listener():
    listener = bind_loopback(0)
    try:
        assert listener.getsockname()[0] == '127.0.0.1'
        assert listener.getsockname()[1] > 0
        with socket.create_connection(listener.getsockname(), timeout=1):
            pass
    finally:
        listener.close()


def _create_required_resources(paths):
    for resource in (
        paths.web / 'index.html',
        paths.web / 'preview.html',
        paths.defaults / 'guidelines' / 'compression.md',
        paths.defaults.parent / 'comfy_nodes' / 'nodes.json',
        paths.defaults.parent / 'trainer' / 'anima_lora' / 'preprocess-model-paths.patch',
    ):
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text('fixture', encoding='utf-8')
    paths.samples.mkdir(parents=True, exist_ok=True)


def test_check_resources_accepts_complete_resource_tree(tmp_path):
    paths = AppPaths(
        root=tmp_path,
        defaults=tmp_path / 'defaults',
        samples=tmp_path / 'samples',
        web=tmp_path / 'web' / 'dist',
    )
    _create_required_resources(paths)

    check_resources(paths)


def test_check_resources_reports_missing_resources(tmp_path):
    paths = AppPaths(
        root=tmp_path,
        defaults=tmp_path / 'defaults',
        samples=tmp_path / 'samples',
        web=tmp_path / 'web' / 'dist',
    )

    with pytest.raises(RuntimeError, match='Missing packaged resources:') as exc_info:
        check_resources(paths)

    message = str(exc_info.value)
    assert str(paths.web / 'index.html') in message
    assert str(paths.samples) in message
