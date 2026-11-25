"""In-app update (#48): prepare from a release, refuse what does not check out, and swap program files with the script."""

import asyncio
import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile

import httpx
import pytest

from atelierx.core import updater as updater_module
from atelierx.core.i18n import AppError
from atelierx.core.updater import Updater, finish_update


def _package(extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('AtelierX/AtelierX.exe', b'new exe')
        archive.writestr('AtelierX/_internal/base.dll', b'new dll')
        archive.writestr('AtelierX/manual/index.html', '<html></html>')
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _updater(paths, package, tag='v9.9.9', sha=None):
    sha = sha or hashlib.sha256(package).hexdigest()
    name = 'AtelierX-9.9.9-windows-x64.zip'

    def handler(request):
        url = str(request.url)
        if url.endswith('/latest'):
            return httpx.Response(
                200,
                json={
                    'tag_name': tag,
                    'assets': [
                        {'name': name, 'size': len(package), 'browser_download_url': 'https://x/pkg.zip'},
                        {'name': f'{name}.sha256', 'browser_download_url': 'https://x/pkg.sha256'},
                    ],
                },
            )
        if url.endswith('pkg.sha256'):
            return httpx.Response(200, text=f'{sha}  {name}\n')
        return httpx.Response(200, content=package)

    up = Updater(paths)
    up.transport = httpx.MockTransport(handler)
    up.release_url = 'https://api.example/releases/latest'
    return up


def _params(folder, root, new, result):
    path = folder / 'params.json'
    path.write_text(
        json.dumps(
            {'app_pid': 999999, 'root': str(root), 'new': str(new), 'result': str(result)}, ensure_ascii=False
        ),
        encoding='utf-8',
    )
    return path


def _seed_user_data(paths):
    (paths.config).mkdir(parents=True, exist_ok=True)
    (paths.config / 'settings.json').write_text('{"language": "ko"}', encoding='utf-8')
    (paths.data / 'works' / 'w').mkdir(parents=True, exist_ok=True)
    (paths.data / 'works' / 'w' / '메인.md').write_text('본문', encoding='utf-8')
    (paths.state / 'webview').mkdir(parents=True, exist_ok=True)
    (paths.state / 'webview' / 'cache.bin').write_bytes(b'x' * 10)


def test_an_update_is_prepared_only_when_it_checks_out(paths, monkeypatch):
    _seed_user_data(paths)
    package = _package(
        {'AtelierX/config/settings.json': '{"evil": true}'}
    )  # user data in a package is ignored
    up = _updater(paths, package)
    asyncio.run(up.prepare())
    status = up.status()
    assert status['state'] == 'ready' and status['version'] == 'v9.9.9'
    new = paths.state / 'update' / 'new' / 'AtelierX'
    assert (new / 'AtelierX.exe').read_bytes() == b'new exe' and not (new / 'config').exists()
    with zipfile.ZipFile(paths.state / 'update' / status['backup']) as backup:
        names = backup.namelist()
    assert 'config/settings.json' in names and 'data/works/w/메인.md' in names
    assert not any(n.startswith('state/webview') for n in names)

    bad = _updater(paths, package, sha='0' * 64)
    with pytest.raises(AppError) as caught:
        asyncio.run(bad.prepare(backup=False))
    assert caught.value.msg.key == 'server.update.mismatch'

    same = _updater(paths, package, tag=f'v{updater_module.__version__}')
    with pytest.raises(AppError) as caught:
        asyncio.run(same.prepare())
    assert caught.value.msg.key == 'server.update.none'

    escaping = _updater(paths, _package({'AtelierX/../evil.txt': 'x'}))
    with pytest.raises(AppError) as caught:
        asyncio.run(escaping.prepare())
    assert caught.value.msg.key == 'server.update.bad_package'


@pytest.mark.parametrize('backup', [True, False])
def test_update_preparation_respects_the_selected_backup(paths, monkeypatch, backup):
    _seed_user_data(paths)
    up = _updater(paths, _package())
    monkeypatch.setattr(up, 'packaged', lambda: True)
    prior = up.folder / 'backup-before-v8.8.8.zip'
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b'previous backup')
    phases = []
    set_phase = up._set

    def trace(**values):
        phases.append(values['state'])
        set_phase(**values)

    monkeypatch.setattr(up, '_set', trace)
    if not backup:
        monkeypatch.setattr(up, '_backup', lambda _: pytest.fail('backup must be skipped'))

    async def scenario():
        up.start(backup=backup)
        await up.task

    asyncio.run(scenario())
    assert 'verifying' in phases and 'extracting' in phases
    assert ('backing_up' in phases) is backup
    status = up.status()
    assert status['state'] == 'ready' and status['version'] == 'v9.9.9'
    assert (up.folder / 'new/AtelierX/AtelierX.exe').read_bytes() == b'new exe'
    assert prior.read_bytes() == b'previous backup'
    if backup:
        with zipfile.ZipFile(up.folder / status['backup']) as archive:
            assert archive.read('data/works/w/메인.md').decode('utf-8') == '본문'
    else:
        assert 'backup' not in status
        assert set(up.folder.glob('backup-before-*.zip')) == {prior}


def test_selected_backup_failure_keeps_the_update_from_being_ready(paths, monkeypatch):
    up = _updater(paths, _package())
    monkeypatch.setattr(up, 'packaged', lambda: True)

    def fail(_):
        raise OSError('disk full')

    monkeypatch.setattr(up, '_backup', fail)

    async def scenario():
        up.start(backup=True)
        await up.task

    asyncio.run(scenario())
    status = up.status()
    assert status['state'] == 'failed'
    assert status['error']['key'] == 'server.update.failed' and 'backup' not in status
    with pytest.raises(AppError) as caught:
        up.apply()
    assert caught.value.msg.key == 'server.update.not_ready'


def test_only_the_packaged_app_starts_an_update_and_never_over_running_work(paths, monkeypatch):
    up = Updater(paths, busy=lambda: ['LoRA training'])
    with pytest.raises(AppError) as caught:
        up.start()
    assert caught.value.msg.key == 'server.update.not_packaged'
    monkeypatch.setattr(Updater, 'packaged', lambda self: True)
    with pytest.raises(AppError) as caught:
        up.start()
    assert caught.value.msg.key == 'server.update.busy' and caught.value.status == 409
    with pytest.raises(AppError):
        up.apply()  # nothing prepared


def test_the_status_api_answers_in_development(unlocked):
    status = unlocked.get('/api/update/status').json()
    assert status['packaged'] is False and status['state'] == 'idle'
    assert unlocked.post('/api/update/start').status_code == 400


@pytest.mark.parametrize(
    ('content', 'expected'),
    [
        ('', True),
        ('{}', True),
        ('{"backup":true}', True),
        ('{"backup":false}', False),
        ('{"backup":0}', None),
        ('{"backup":"false"}', None),
        ('{"backup":null}', None),
        ('[]', None),
        ('null', None),
        ('true', None),
        ('{"backup":', None),
    ],
)
def test_update_start_validates_and_forwards_backup_choice(unlocked, monkeypatch, content, expected):
    up = unlocked.app.state.app.updater
    choices = []

    def start(*, backup=True):
        choices.append(backup)
        return {'state': 'checking'}

    monkeypatch.setattr(up, 'start', start)
    response = unlocked.post(
        '/api/update/start', content=content, headers={'Content-Type': 'application/json'}
    )
    if expected is None:
        assert response.status_code == 400
        assert not choices
    else:
        assert response.status_code == 200
        assert choices == [expected] and choices[0] is expected


@pytest.mark.skipif(sys.platform != 'win32', reason='the swap script is PowerShell on Windows')
def test_the_swap_script_replaces_program_files_and_keeps_user_data(paths, tmp_path):
    root = tmp_path / '한글 앱 [test]'
    (root / '_internal').mkdir(parents=True)
    (root / '_internal' / 'old.dll').write_bytes(b'old')
    (root / 'AtelierX.exe').write_bytes(b'old exe')
    (root / 'config').mkdir()
    (root / 'config' / 'settings.json').write_text('{}', encoding='utf-8')
    (root / '_internal.old').mkdir()
    (root / '_internal.old' / 'personal.dll').write_bytes(b'personal')
    (root / 'AtelierX.exe.old').write_bytes(b'personal exe')
    (root / 'personal-notes.old').write_bytes(b'notes')
    new = tmp_path / 'new' / 'AtelierX'
    (new / '_internal').mkdir(parents=True)
    (new / '_internal' / 'new.dll').write_bytes(b'new')
    (new / 'AtelierX.exe').write_bytes(b'new exe')
    (new / 'manual').mkdir()
    (new / 'manual' / 'index.html').write_text('m', encoding='utf-8')
    script = Updater(paths).write_script()
    result = paths.state / 'update' / 'result.json'
    unrelated_backup = result.parent / 'backups' / ('f' * 32)
    unrelated_backup.mkdir(parents=True)
    (unrelated_backup / 'personal.txt').write_bytes(b'personal backup')
    done = subprocess.run(
        [
            'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
            '-Params', str(_params(tmp_path, root, new, result)), '-NoStart',
        ],
        capture_output=True, timeout=120, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode(errors='replace')
    swap_result = json.loads(result.read_text(encoding='utf-8'))
    assert swap_result['state'] == 'ok'
    backup = result.parent / 'backups' / swap_result['backup_id']
    assert (root / 'AtelierX.exe').read_bytes() == b'new exe' and (root / '_internal' / 'new.dll').is_file()
    assert (backup / '_internal' / 'old.dll').read_bytes() == b'old'
    assert (backup / 'AtelierX.exe').read_bytes() == b'old exe'
    assert (root / '_internal.old' / 'personal.dll').read_bytes() == b'personal'
    assert (root / 'AtelierX.exe.old').read_bytes() == b'personal exe'
    assert (root / 'personal-notes.old').read_bytes() == b'notes'
    assert (root / 'config' / 'settings.json').is_file() and (root / 'manual' / 'index.html').is_file()

    # The new version starts: the replaced files go, the result stays for the screen.
    (paths.state / 'update' / 'pending.json').write_text(
        '{"version": "v9.9.9", "from": "0.0.6"}', encoding='utf-8'
    )
    fake = type('P', (), {'state': paths.state, 'root': root})()
    assert finish_update(fake)['state'] == 'ok'
    assert backup.exists()  # Startup only detaches temporary files; DOM readiness starts deletion.
    Updater(fake).cleanup.run()
    assert not backup.exists()
    assert (unrelated_backup / 'personal.txt').read_bytes() == b'personal backup'
    assert (root / '_internal.old' / 'personal.dll').read_bytes() == b'personal'
    assert (root / 'AtelierX.exe.old').read_bytes() == b'personal exe'
    assert (root / 'personal-notes.old').read_bytes() == b'notes'
    assert finish_update(fake) is None
    assert (root / 'personal-notes.old').read_bytes() == b'notes'
    assert (
        json.loads((paths.state / 'update' / 'result.json').read_text(encoding='utf-8'))['version']
        == 'v9.9.9'
    )


@pytest.mark.skipif(sys.platform != 'win32', reason='the swap script is PowerShell on Windows')
def test_the_swap_script_rolls_back_when_a_file_is_in_use(paths, tmp_path):
    root = tmp_path / 'app'
    (root / '_internal').mkdir(parents=True)
    (root / '_internal' / 'old.dll').write_bytes(b'old')
    (root / 'AtelierX.exe').write_bytes(b'old exe')
    (root / 'AtelierX.exe.old').write_bytes(b'personal exe')
    new = tmp_path / 'new' / 'AtelierX'
    (new / '_internal').mkdir(parents=True)
    (new / '_internal' / 'new.dll').write_bytes(b'new')
    (new / 'AtelierX.exe').write_bytes(b'new exe')
    script = Updater(paths).write_script()
    result = paths.state / 'update' / 'result.json'
    with (root / '_internal' / 'old.dll').open('rb'):  # still loaded: the folder cannot move
        done = subprocess.run(
            [
                'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                '-Params', str(_params(tmp_path, root, new, result)), '-NoStart',
            ],
            capture_output=True, timeout=120, check=False,
        )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode(errors='replace')
    assert json.loads(result.read_text(encoding='utf-8'))['state'] == 'failed'
    assert (root / 'AtelierX.exe').read_bytes() == b'old exe' and (root / '_internal' / 'old.dll').is_file()
    assert (root / 'AtelierX.exe.old').read_bytes() == b'personal exe'
    (result.parent / 'pending.json').write_text('{"version": "v9.9.9"}', encoding='utf-8')
    fake = type('P', (), {'state': paths.state, 'root': root})()
    assert finish_update(fake)['state'] == 'failed'
    assert finish_update(fake) is None
    assert (root / 'AtelierX.exe.old').read_bytes() == b'personal exe'


def test_legacy_update_result_does_not_claim_old_files(paths):
    root = paths.root
    (root / '_internal.old').mkdir()
    (root / '_internal.old' / 'backup.dll').write_bytes(b'legacy or personal')
    (root / 'personal-notes.old').write_bytes(b'personal')
    update = paths.state / 'update'
    update.mkdir(parents=True)
    (update / 'pending.json').write_text('{"version": "v0.4.1", "from": "0.4.0"}', encoding='utf-8')
    (update / 'result.json').write_text('{"state": "ok"}', encoding='utf-8')

    assert finish_update(paths)['state'] == 'ok'
    assert (root / '_internal.old' / 'backup.dll').read_bytes() == b'legacy or personal'
    assert (root / 'personal-notes.old').read_bytes() == b'personal'
    assert finish_update(paths) is None


@pytest.mark.skipif(sys.platform != 'win32', reason='the swap script is PowerShell on Windows')
def test_the_script_is_launched_so_that_it_outlives_the_app(tmp_path):
    folder = tmp_path / "한글 [x] it's"
    folder.mkdir()
    marker = folder / 'ran.txt'
    script = folder / 'apply.ps1'
    quoted = str(marker).replace("'", "''")
    script.write_text(f"Set-Content -LiteralPath '{quoted}' -Value ok", encoding='utf-8-sig')
    updater_module.launch(script).wait(30)  # the launcher ends at once; the script runs on its own
    for _ in range(60):
        if marker.is_file():
            break
        time.sleep(0.25)
    assert marker.is_file()
