import json
from pathlib import Path

from atelierx.image import comfy_locate


def make_comfy(path: Path):
    path.mkdir(parents=True)
    (path / 'main.py').write_text('', encoding='utf-8')
    (path / 'nodes.py').write_text('', encoding='utf-8')
    (path / 'comfy').mkdir()
    return path


def test_stability_matrix_uses_library_location(tmp_path, monkeypatch):
    package = make_comfy(tmp_path / 'matrix' / 'Packages' / 'ComfyUI')
    (tmp_path / 'matrix' / 'Models').mkdir()
    appdata = tmp_path / 'appdata'
    settings = appdata / 'StabilityMatrix'
    settings.mkdir(parents=True)
    (settings / 'library.json').write_text(
        json.dumps({'LibraryPath': str(package.parent.parent)}), encoding='utf-8'
    )
    monkeypatch.setenv('APPDATA', str(appdata))
    found = comfy_locate._stability_matrix()
    assert package in found
    assert comfy_locate.kind_of(package) == 'stability_matrix'


def test_stability_matrix_default_location_without_library_json(tmp_path, monkeypatch):
    packages = tmp_path / 'StabilityMatrix' / 'Packages'
    package = make_comfy(packages / 'ComfyUI')
    (tmp_path / 'StabilityMatrix' / 'Models').mkdir()
    monkeypatch.delenv('APPDATA', raising=False)
    monkeypatch.setattr(comfy_locate, '_DEFAULT_STABILITY_MATRIX_PACKAGES', packages)
    monkeypatch.setattr(comfy_locate.Path, 'home', lambda: tmp_path / 'home')
    assert package in comfy_locate._stability_matrix()


def test_desktop_venv_and_portable_python_are_detected(tmp_path):
    desktop = make_comfy(tmp_path / 'desktop' / 'ComfyUI')
    desktop_python = desktop.parent / '.venv' / 'Scripts' / 'python.exe'
    desktop_python.parent.mkdir(parents=True)
    desktop_python.touch()
    assert comfy_locate.python_for(desktop) == desktop_python
    assert comfy_locate.kind_of(desktop) == 'desktop'

    portable = make_comfy(tmp_path / 'portable' / 'ComfyUI')
    embedded_python = portable.parent / 'python_embeded' / 'python.exe'
    embedded_python.parent.mkdir(parents=True)
    embedded_python.touch()
    assert comfy_locate.python_for(portable) == embedded_python
    assert comfy_locate.kind_of(portable) == 'portable'


def test_desktop_uses_configured_basepath_python_outside_resources(tmp_path, monkeypatch):
    appdata = tmp_path / 'appdata'
    config = appdata / 'ComfyUI' / 'config.json'
    config.parent.mkdir(parents=True)
    base = tmp_path / 'desktop-base'
    config.write_text(json.dumps({'basePath': str(base)}), encoding='utf-8')
    comfy = make_comfy(tmp_path / 'programs' / '@comfyorgcomfyui-electron' / 'resources' / 'ComfyUI')
    python = base / '.venv' / 'Scripts' / 'python.exe'
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setenv('APPDATA', str(appdata))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert comfy in comfy_locate._desktop()
    assert comfy_locate.python_for(comfy) == python
    assert comfy_locate.kind_of(comfy) == 'desktop'


def test_common_search_is_shallow_and_checks_ai_containers(tmp_path, monkeypatch):
    comfy = make_comfy(tmp_path / 'AI' / 'ComfyUI')
    monkeypatch.setattr(comfy_locate.Path, 'home', lambda: tmp_path)
    assert comfy in comfy_locate._common_places()


def test_candidates_resolve_relative_running_argv_when_install_is_unique(tmp_path, monkeypatch):
    comfy = make_comfy(tmp_path / 'install' / 'ComfyUI')
    monkeypatch.setattr(comfy_locate, '_stability_matrix', lambda: [comfy])
    monkeypatch.setattr(comfy_locate, '_desktop', list)
    monkeypatch.setattr(comfy_locate, '_common_places', list)

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(
                {'system': {'argv': ['main.py', '--listen', '127.0.0.1'], 'comfyui_version': '1.2'}}
            ).encode()

    monkeypatch.setattr(comfy_locate.urllib.request, 'urlopen', lambda *args, **kwargs: Reply())
    found = comfy_locate.candidates()
    assert found[0]['source'] == 'running'
    assert found[0]['comfy_path'] == str(comfy)
    assert found[0]['arguments'] == ['--listen', '127.0.0.1']
    assert len(found) == 1


def test_relative_running_argv_does_not_match_remote_endpoint(tmp_path, monkeypatch):
    comfy = make_comfy(tmp_path / 'install' / 'ComfyUI')
    monkeypatch.setattr(comfy_locate, '_stability_matrix', lambda: [comfy])
    monkeypatch.setattr(comfy_locate, '_desktop', list)
    monkeypatch.setattr(comfy_locate, '_common_places', list)

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({'system': {'argv': ['main.py']}}).encode()

    monkeypatch.setattr(comfy_locate.urllib.request, 'urlopen', lambda *args, **kwargs: Reply())
    found = comfy_locate.candidates('http://remote.example:8188')
    assert len(found) == 1
    assert found[0]['source'] == 'stability_matrix'
