import hashlib
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from atelierx.image import installs as installs_module
from atelierx.image import settings as image_settings
from atelierx.image.installs import Installs, apply_patch

ROOT = Path(__file__).resolve().parents[1]


def make_installs(tmp_path):
    runtime = SimpleNamespace(
        paths=SimpleNamespace(root=tmp_path, defaults=tmp_path, config=tmp_path / 'config')
    )
    return Installs(runtime)


def test_tool_validation_skips_broken_path_entry_and_caches(tmp_path, monkeypatch):
    installs = make_installs(tmp_path)
    installs.run = {'log': []}
    broken = tmp_path / 'broken-uv.exe'
    local = installs.bin / 'uv.exe'
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.touch()
    local.parent.mkdir(parents=True)
    local.touch()
    monkeypatch.setattr(installs_module.shutil, 'which', lambda name: str(broken))
    calls = []

    def run(command, **kwargs):
        calls.append(command[0])
        return SimpleNamespace(returncode=1 if command[0] == str(broken) else 0, stdout='uv 0.8', stderr='')

    monkeypatch.setattr(installs_module.subprocess, 'run', run)
    assert installs.uv() == str(local)
    assert installs.uv() == str(local)
    assert calls == [str(broken), str(local)]
    assert installs._valid_tool(str(broken)) is False
    assert calls == [str(broken), str(local)]


def test_partial_tool_install_checks_binary_and_can_retry(tmp_path, monkeypatch):
    installs = make_installs(tmp_path)
    installs.run = {'log': []}
    monkeypatch.setattr(installs_module.shutil, 'which', lambda _name: None)
    valid = {'value': False}
    checked = []

    def download(_url, target, **_kwargs):
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('uv-x86_64-pc-windows-msvc/uv.exe', b'test executable')

    def run(command, **_kwargs):
        checked.append(command[0])
        return SimpleNamespace(
            returncode=0 if valid['value'] else 1, stdout='uv 0.8' if valid['value'] else '', stderr=''
        )

    monkeypatch.setattr(installs, '_download', download)
    monkeypatch.setattr(installs_module.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='Could not install or run uv'):
        installs._install_tools({'items': ['uv']})
    assert not (installs.bin / 'git' / 'cmd' / 'git.exe').exists()

    valid['value'] = True
    installs._install_tools({'items': ['uv']})
    assert installs.uv() == str(installs.bin / 'uv.exe')
    assert len(checked) >= 2


def test_apply_patch_is_idempotent_and_refuses_other_versions():
    patch = (ROOT / 'trainer' / 'anima_lora' / 'preprocess-model-paths.patch').read_text(encoding='utf-8')
    # The file as the patch expects it: every hunk's context and removed lines, in order.
    original, hunk = [], []
    for line in patch.splitlines():
        if line.startswith('@@'):
            original += hunk + ['# between hunks']
            hunk = []
        elif line[:1] in (' ', '-') and not line.startswith('---'):
            hunk.append(line[1:])
    original += hunk
    text = '\r\n'.join(original)
    patched = apply_patch(text, patch)
    assert '# atelierx patch' in patched and '\r\n' in patched
    assert apply_patch(patched, patch) == patched
    with pytest.raises(ValueError):
        apply_patch('something else entirely', patch)


def test_fill_training_models_preserves_individual_custom_and_generation_paths(tmp_path):
    paths = SimpleNamespace(root=tmp_path, defaults=tmp_path, config=tmp_path / 'config')
    installs = Installs(SimpleNamespace(paths=paths))
    installs.run = {'log': []}
    installed = {}
    for key in ('dit', 'text_encoder', 'vae'):
        path = tmp_path / f'{key}.safetensors'
        path.write_bytes(b'model')
        installed[key] = str(path)
    manifest = {
        'groups': [
            {
                'items': [
                    {'id': key, 'file': f'{key}.safetensors', 'folder': key, 'training': key}
                    for key in installed
                ]
            }
        ]
    }
    installs.manifest = lambda: manifest
    installs.model_folders = lambda: {key: [str(tmp_path)] for key in installed}
    image_settings.save(
        paths,
        'training',
        {
            'bases': {
                'official': {'dit': '', 'text_encoder': 'custom encoder.safetensors', 'vae': ''},
                'generation': {
                    'dit': 'generation dit',
                    'text_encoder': 'generation text',
                    'vae': 'generation vae',
                },
            }
        },
    )

    installs._fill_training_models()

    bases = image_settings.get(paths, 'training')['bases']
    assert bases['official'] == {
        'dit': installed['dit'],
        'text_encoder': 'custom encoder.safetensors',
        'vae': installed['vae'],
    }
    assert bases['generation'] == {
        'dit': 'generation dit',
        'text_encoder': 'generation text',
        'vae': 'generation vae',
    }


def test_training_install_only_uses_tagged_items_reuses_files_and_installs_trainer(tmp_path, monkeypatch):
    paths = SimpleNamespace(root=tmp_path, defaults=tmp_path, config=tmp_path / 'config')
    installs = Installs(SimpleNamespace(paths=paths))
    installs.run = {'log': []}
    model_dir = tmp_path / 'models'
    model_dir.mkdir()
    existing = model_dir / 'dit.safetensors'
    existing.write_bytes(b'existing')
    manifest = {
        'groups': [
            {
                'items': [
                    {
                        'id': 'dit',
                        'file': 'dit.safetensors',
                        'folder': 'diffusion_models',
                        'training': 'dit',
                        'url': 'mock:dit',
                    },
                    {
                        'id': 'encoder',
                        'file': 'encoder.safetensors',
                        'folder': 'text_encoders',
                        'training': 'text_encoder',
                        'url': 'mock:encoder',
                    },
                    {
                        'id': 'vae',
                        'file': 'vae.safetensors',
                        'folder': 'vae',
                        'training': 'vae',
                        'url': 'mock:vae',
                    },
                    {'id': 'unrelated', 'file': 'large.bin', 'folder': 'checkpoints', 'url': 'mock:other'},
                ]
            }
        ]
    }
    installs.manifest = lambda: manifest
    installs.model_folders = lambda: (
        {kind: [str(model_dir)] for kind in ('diffusion_models', 'text_encoders', 'vae')}
        | {'loras': [str(model_dir / 'loras')]}
    )
    (model_dir / 'loras').mkdir()
    downloads = []

    def download(url, target, *_args, **_kwargs):
        downloads.append(url)
        Path(target).write_bytes(url.encode())

    monkeypatch.setattr(installs, '_download', download)
    monkeypatch.setattr(installs, '_fill_training_models', lambda: None)
    trainer_calls = []
    monkeypatch.setattr(installs, '_install_trainer', lambda body: trainer_calls.append(body))
    monkeypatch.setattr(
        installs_module.trainer_setup,
        'status',
        lambda _paths: {
            'trainer_found': True,
            'python_found': True,
            'patched': True,
            'lora_dir_found': True,
            'files': {'official.dit': True, 'official.text_encoder': True, 'official.vae': True},
        },
    )

    installs._install_training({'source': 'test'})

    assert downloads == ['mock:encoder', 'mock:vae']
    assert trainer_calls == [{'source': 'test'}]
    assert (model_dir / 'encoder.safetensors').read_bytes() == b'mock:encoder'
    assert (model_dir / 'vae.safetensors').read_bytes() == b'mock:vae'
    assert not (model_dir / 'large.bin').exists()


def test_training_install_preflights_model_folders_before_trainer(tmp_path, monkeypatch):
    installs = make_installs(tmp_path)
    installs.run = {'log': []}
    loras = tmp_path / 'loras'
    loras.mkdir()
    installs.model_folders = lambda: {'diffusion_models': [], 'loras': [str(loras)]}
    installs.manifest = lambda: {
        'groups': [{'items': [{'file': 'dit.safetensors', 'folder': 'diffusion_models', 'training': 'dit'}]}]
    }
    trainer = []
    monkeypatch.setattr(installs, '_install_trainer', lambda _body: trainer.append(True))
    with pytest.raises(ValueError, match='no folder for diffusion_models'):
        installs._install_training({})
    assert trainer == []


def test_model_downloads_check_hashes_and_fill_training_settings(unlocked, tmp_path):
    c = unlocked
    installs = c.app.state.app.image.installs
    source = tmp_path / 'source'
    source.mkdir()
    files = {}
    for name in ('dit.safetensors', 'te.safetensors', 'vae.safetensors', 'bad.pt'):
        data = name.encode() * 10
        (source / name).write_bytes(data)
        files[name] = (len(data), hashlib.sha256(data).hexdigest())
    folders = {
        kind: [str(tmp_path / 'models' / kind)]
        for kind in ('diffusion_models', 'text_encoders', 'vae', 'ultralytics_bbox')
    }

    def item(ident, name, folder, training=None, sha=None):
        size, digest = files[name]
        entry = {
            'id': ident,
            'file': name,
            'folder': folder,
            'url': (source / name).as_uri(),
            'size': size,
            'sha256': sha or digest,
        }
        return {**entry, 'training': training} if training else entry

    manifest = {
        'groups': [
            {
                'id': 'training_base',
                'items': [
                    item('dit', 'dit.safetensors', 'diffusion_models', 'dit'),
                    item('te', 'te.safetensors', 'text_encoders', 'text_encoder'),
                    item('vae', 'vae.safetensors', 'vae', 'vae'),
                ],
            },
            {
                'id': 'detectors',
                'items': [
                    item('bad', 'bad.pt', 'ultralytics_bbox', sha='0' * 64),
                    {
                        'id': 'm',
                        'file': 'm.pt',
                        'folder': 'ultralytics_bbox',
                        'manual': 'https://example.invalid',
                    },
                ],
            },
        ]
    }
    installs.manifest = lambda: manifest
    installs.model_folders = lambda: folders

    status = c.get('/api/image/installs').json()
    assert status['models']['connected'] and status['models']['groups'][0]['items'][0]['installed'] is None

    def wait():
        for _ in range(200):
            run = c.get('/api/image/installs').json()['run']
            if run['status'] != 'running':
                return run
            time.sleep(0.05)
        raise AssertionError('install did not finish')

    assert c.post('/api/image/installs/models', json={'items': ['training_base']}).status_code == 200
    run = wait()
    assert run['status'] == 'done', run
    assert (tmp_path / 'models' / 'vae' / 'vae.safetensors').read_bytes() == b'vae.safetensors' * 10
    training = c.get('/api/image/settings/training').json()
    assert training['bases']['official']['dit'].endswith('dit.safetensors')

    # A file whose hash does not match is not kept.
    c.post('/api/image/installs/models', json={'items': ['detectors']})
    run = wait()
    assert run['status'] == 'failed' and not (tmp_path / 'models' / 'ultralytics_bbox' / 'bad.pt').exists()
    assert not list((tmp_path / 'models' / 'ultralytics_bbox').glob('*.part'))
    assert c.post('/api/image/installs/nope').status_code == 400


def test_tools_download_at_their_pinned_version_and_say_why_a_download_failed(tmp_path, monkeypatch):
    import urllib.error

    installs = make_installs(tmp_path)
    installs.run = {'log': []}
    monkeypatch.setattr(installs_module.shutil, 'which', lambda _name: None)
    asked = []

    def download(url, target, **kwargs):
        asked.append((url, kwargs))
        raise urllib.error.URLError('offline')

    monkeypatch.setattr(installs, '_download', download)
    with pytest.raises(RuntimeError, match='Could not reach GitHub to download Git'):
        installs._install_tools({'items': ['git']})
    url, kwargs = asked[0]
    pinned = installs_module.TOOLS['git']
    assert url == pinned['url'] and kwargs == {'size': pinned['size'], 'sha256': pinned['sha256']}

    def refused(url, target, **kwargs):
        raise urllib.error.HTTPError(url, 403, 'rate limited', {}, None)

    monkeypatch.setattr(installs, '_download', refused)
    with pytest.raises(RuntimeError, match=r'HTTP 403'):
        installs._install_tools({'items': ['uv']})
