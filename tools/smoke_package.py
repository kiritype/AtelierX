#!/usr/bin/env python3
"""Run an offline integration smoke test against a copied portable AtelierX distribution.

The executable is copied into a fresh Unicode path and launched with an isolated root.
Only Python's standard library is used. The source distribution is never modified.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

STARTUP_TIMEOUT = 90
REQUEST_TIMEOUT = 15


class SmokeFailure(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path: str, method: str = 'GET', data=None, expected=200):
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode('utf-8')
        headers = {'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'
        req = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            response = self.opener.open(req, timeout=REQUEST_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code != expected:
                raise SmokeFailure(f'{method} {path}: expected HTTP {expected}, got {exc.code}') from None
            raw = exc.read()
            return exc.code, raw
        except (OSError, TimeoutError) as exc:
            raise SmokeFailure(f'{method} {path}: request failed ({type(exc).__name__})') from None
        with response:
            status, raw = response.status, response.read()
        if status != expected:
            raise SmokeFailure(f'{method} {path}: expected HTTP {expected}, got {status}')
        return status, raw

    def json(self, path: str, method: str = 'GET', data=None, expected=200):
        _, raw = self.request(path, method, data, expected)
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SmokeFailure(f'{method} {path}: response was not JSON') from None


def check(condition, message):
    if not condition:
        raise SmokeFailure(message)


def safe_env():
    env = os.environ.copy()
    for key in list(env):
        upper = key.upper()
        if upper in {
            'PYTHONPATH',
            'PYTHONHOME',
            'VIRTUAL_ENV',
            'CONDA_PREFIX',
            'CONDA_DEFAULT_ENV',
        } or upper.startswith(('UV_', 'CONDA_', 'VIRTUAL_ENV_')):
            env.pop(key, None)
    system_root = env.get('SystemRoot') or env.get('SYSTEMROOT') or r'C:\Windows'
    env['PATH'] = str(Path(system_root) / 'System32')
    return env


def launch(exe: Path, root: Path | None, ready_file: Path, cwd: Path, log_path: Path):
    flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    log = log_path.open('wb')
    try:
        command = [str(exe), '--headless', '--port', '0']
        if root is not None:
            command.extend(['--root', str(root)])
        command.extend(['--ready-file', str(ready_file)])
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=safe_env(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    except Exception:
        log.close()
        raise
    return process, log


def wait_ready(process, ready_file: Path, expected_root: Path, timeout=STARTUP_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure(f'server exited during startup (exit {process.returncode})')
        try:
            ready = json.loads(ready_file.read_text(encoding='utf-8'))
            if (
                ready.get('url')
                and ready.get('pid') == process.pid
                and Path(ready.get('root', '')).resolve() == expected_root.resolve()
            ):
                return ready
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    raise SmokeFailure(f'server did not become ready within {timeout} seconds')


def stop(process, log):
    if process.poll() is None:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    log.close()


def get_json_url(url: str):
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise SmokeFailure(f'static request failed ({type(exc).__name__})') from None


def run_phase(client: Client, root: Path, password: str, report: dict):
    status = client.json('/api/auth/status')
    check(
        status.get('initialized') is False and status.get('unlocked') is False,
        'fresh root was not reported as uninitialized and locked',
    )
    code, _ = client.request('/api/works', expected=401)
    check(code == 401, 'unauthenticated protected API did not return 401')
    client.json('/api/auth/setup', 'POST', {'password': password, 'language': 'ko'})
    check(
        client.json('/api/auth/status').get('unlocked') is True,
        'master password setup did not unlock session',
    )

    samples = client.json('/api/samples')
    sample_names = (
        [item.get('id') or item.get('name') for item in samples] if isinstance(samples, list) else []
    )
    sample = next((name for name in ('single', *sample_names) if name), None)
    check(sample is not None, 'sample catalog was empty')
    work = client.json(
        f'/api/samples/{urllib.parse.quote(str(sample), safe="")}/install', 'POST', expected=201
    )
    wid = work.get('id')
    check(bool(wid), 'sample installation did not return a work id')

    file_path = 'Characters/Smoke Character.md'
    made = client.json(
        f'/api/works/{wid}/file', 'POST', {'path': file_path, 'kind': 'character'}, expected=201
    )
    check(made.get('path') == file_path, 'character file creation failed')
    item = client.json(f'/api/works/{wid}/file?path={urllib.parse.quote(file_path)}')
    cid = 'C987'
    edited = client.json(
        f'/api/works/{wid}/file?path={urllib.parse.quote(file_path)}',
        'PUT',
        {
            'meta': {'id': cid, 'name': 'Smoke Character', 'keywords': ['smoke']},
            'body': '## Appearance\nA test character.\n',
            'base_hash': item.get('hash'),
        },
    )
    check(edited.get('meta', {}).get('id') == cid, 'character metadata update failed')
    check(
        client.json(f'/api/works/{wid}/file?path={urllib.parse.quote(file_path)}')
        .get('body', '')
        .startswith('## Appearance'),
        'character body did not persist',
    )
    design = client.json(f'/api/works/{wid}/image/characters/{cid}')
    if design.get('design') is None:
        design = client.json(
            f'/api/works/{wid}/image/characters/{cid}',
            'PUT',
            {
                'design': {
                    'schema_version': 1,
                    'appearance': {'prompt': [], 'negative': []},
                    'outfits': {'o01': {'name': 'Smoke', 'slots': {}, 'negative': []}},
                    'default_outfit': 'o01',
                },
                'base_revision': design.get('revision'),
            },
        )
    check(isinstance(design.get('design'), dict), 'image character design endpoint did not return a design')

    preset_id = 'smoke_package'
    preset = client.json(
        '/api/platforms', 'POST', {'id': preset_id, 'name': 'Package Smoke', 'base': 'generic'}
    )
    check(
        preset.get('name') == 'Package Smoke' and preset.get('count') == 'utf8_bytes',
        'platform preset creation failed',
    )
    check(
        client.json(f'/api/platforms/{preset_id}').get('name') == 'Package Smoke',
        'platform preset read failed',
    )
    client.json(f'/api/platforms/{preset_id}', 'PUT', {**preset, 'name': 'Package Smoke Saved'})
    check(
        client.json(f'/api/platforms/{preset_id}').get('name') == 'Package Smoke Saved',
        'platform preset save failed',
    )

    guide = client.json('/api/settings/compression-guideline')
    marker = 'portable smoke guideline'
    saved = client.json(
        '/api/settings/compression-guideline',
        'PUT',
        {'text': marker + '\n', 'base_revision': guide['revision']},
    )
    check(saved.get('text') == marker + '\n', 'compression guideline save failed')
    check(
        client.json('/api/settings/compression-guideline').get('text') == marker + '\n',
        'compression guideline readback failed',
    )

    export_dir = root / 'smoke-export'
    export_dir.mkdir(exist_ok=True)
    queued = client.json(f'/api/works/{wid}/export', 'POST', {'target': str(export_dir), 'overwrite': False})
    job_id = queued.get('id')
    check(bool(job_id), 'work export did not return a job id')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        jobs = client.json('/api/jobs')
        candidates = jobs.get('jobs', jobs) if isinstance(jobs, dict) else jobs
        job = next((entry for entry in candidates if entry.get('id') == job_id), None)
        if job and job.get('status') in ('done', 'failed', 'cancelled'):
            break
        time.sleep(0.2)
    check(job and job.get('status') == 'done', 'work export job did not complete')
    check((export_dir / '_keywords.md').is_file(), 'export output is missing _keywords.md')
    check((export_dir / file_path).is_file(), 'export output is missing the character file')
    # Package the exported work tree as a ZIP so the smoke artifact is self-contained.
    archive = root / 'smoke-export.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in export_dir.rglob('*'):
            if path.is_file():
                zf.write(path, path.relative_to(export_dir).as_posix())
    with zipfile.ZipFile(archive) as zf:
        check(
            '_keywords.md' in zf.namelist() and file_path in zf.namelist(),
            'export ZIP contents are incomplete',
        )

    installs = client.json('/api/image/installs')
    check(isinstance(installs, dict), 'image install status did not return an object')
    model_status = installs.get('models')
    check(
        isinstance(model_status, dict) and isinstance(model_status.get('groups'), list),
        'bundled image resource manifest was not exposed in install status',
    )
    index_status, index_body, index_type = get_json_url(client.base_url + '/')
    check(
        index_status == 200 and 'text/html' in index_type and b'/assets/' in index_body,
        'built SPA entry or hashed assets link was not served',
    )
    html = index_body.decode('utf-8', 'replace')
    assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)', html)
    check(bool(assets), 'SPA entry did not reference a hashed asset')
    asset_status, asset_body, _ = get_json_url(client.base_url + assets[0])
    check(asset_status == 200 and bool(asset_body), 'SPA hashed asset could not be fetched')
    preview_status, preview_body, preview_type = get_json_url(client.base_url + '/preview.html')
    check(
        preview_status == 200 and 'text/html' in preview_type and b'/assets/' in preview_body,
        'preview iframe page or its asset references were not served',
    )
    preview_assets = re.findall(rb'(?:src|href)="(/assets/[^"?#]+)', preview_body)
    check(bool(preview_assets), 'preview iframe page did not reference a bundled asset')
    preview_asset_status, preview_asset_body, _ = get_json_url(
        client.base_url + preview_assets[0].decode('ascii')
    )
    check(
        preview_asset_status == 200 and bool(preview_asset_body), 'preview iframe asset could not be fetched'
    )

    report['first_run'] = 'PASS'
    report['api_create_read_update_and_export'] = 'PASS'
    report['spa_preview_and_image_status'] = 'PASS'
    return {'work_id': wid, 'preset_id': preset_id, 'file_path': file_path, 'guideline': marker + '\n'}


def persist_phase(client: Client, state):
    client.json('/api/auth/lock', 'POST')
    status = client.json('/api/auth/status')
    check(
        status.get('initialized') is True and status.get('unlocked') is False,
        'vault did not remain initialized and lockable',
    )
    return status


def restart_phase(base_url: str, password: str, state, report):
    client = Client(base_url)
    status = client.json('/api/auth/status')
    check(
        status.get('initialized') is True and status.get('unlocked') is False,
        'vault initialization or locked state did not persist after restart',
    )
    client.json('/api/auth/unlock', 'POST', {'password': password})
    check(
        client.json('/api/auth/status').get('unlocked') is True,
        'master password did not unlock after restart',
    )
    work = client.json(f'/api/works/{state["work_id"]}')
    check(work.get('name'), 'saved work did not persist after restart')
    item = client.json(f'/api/works/{state["work_id"]}/file?path={urllib.parse.quote(state["file_path"])}')
    check(item.get('meta', {}).get('id') == 'C987', 'character metadata did not persist after restart')
    check(
        client.json('/api/platforms/smoke_package').get('name') == 'Package Smoke Saved',
        'platform preset did not persist after restart',
    )
    check(
        client.json('/api/settings/compression-guideline').get('text') == state['guideline'],
        'compression guideline did not persist after restart',
    )
    report['restart_persistence'] = 'PASS'


def verify_isolation(package_copy: Path, root: Path, report):
    for name in ('config', 'state', 'data', 'output'):
        candidate = root / name
        check(
            candidate.exists() and candidate.is_dir(), f'runtime {name}/ was not created under isolated root'
        )
        check(
            not candidate.resolve().is_relative_to(package_copy.resolve()),
            f'runtime {name}/ is inside copied package',
        )
    check((root / 'config' / 'vault.json').is_file(), 'vault file was not written in isolated config/')
    report['explicit_root_isolation'] = 'PASS'


def verify_default_root(exe: Path, ready_file: Path, cwd: Path, log_path: Path, report):
    root = exe.parent
    process, log = launch(exe, None, ready_file, cwd, log_path)
    try:
        ready = wait_ready(process, ready_file, root)
        client = Client(ready['url'])
        status = client.json('/api/auth/status')
        check(status.get('initialized') is False, 'default package root was not a fresh environment')
        password = 'AX-smoke-' + secrets.token_urlsafe(24)
        client.json('/api/auth/setup', 'POST', {'password': password, 'language': 'ko'})
        for name in ('config', 'state', 'data', 'output'):
            check((root / name).is_dir(), f'default runtime {name}/ was not created beside the executable')
        check(
            (root / 'config' / 'vault.json').is_file(),
            'default runtime vault was not written beside the executable',
        )
        report['default_root_beside_exe'] = 'PASS'
    finally:
        stop(process, log)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path, help='path to a portable AtelierX.exe')
    parser.add_argument(
        '--workspace',
        type=Path,
        default=Path('notes/packaging/isolated'),
        help='parent directory for the fresh test copy and report',
    )
    args = parser.parse_args(argv)
    source_exe = args.exe.expanduser().resolve()
    workspace = args.workspace.expanduser().resolve()
    report = {
        'status': 'FAIL',
        'checks': {},
        'assumptions': [
            'Launcher accepts --headless --port 0 --ready-file <path>, with --root <dir> optional.',
            'Ready file contains url, pid, and root fields once the HTTP server is ready.',
            'The app bundle serves a built SPA and preview.html, and work export produces files for ZIP packaging.',
        ],
    }
    process = None
    log = None
    try:
        check(
            source_exe.is_file() and source_exe.name.lower() == 'atelierx.exe',
            'input must be an existing AtelierX.exe',
        )
        workspace.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix='package-smoke-', dir=workspace))
        package_copy = run_dir / '한글 경로 [test]'
        package_copy.mkdir()
        shutil.copytree(source_exe.parent, package_copy, dirs_exist_ok=True)
        copied_exe = package_copy / source_exe.name
        check(copied_exe.is_file(), 'copied package did not contain AtelierX.exe')
        runtime_root = run_dir / 'runtime'
        ready_file = run_dir / 'ready.json'
        cwd = run_dir / 'unrelated-cwd'
        cwd.mkdir()
        password = 'AX-smoke-' + secrets.token_urlsafe(24)
        report['package_copy'] = 'PASS'
        report['copy_path'] = str(package_copy)
        report_path = run_dir / 'report.json'

        process, log = launch(copied_exe, runtime_root, ready_file, cwd, run_dir / 'server.log')
        ready = wait_ready(process, ready_file, runtime_root)
        client = Client(ready['url'])
        state = run_phase(client, runtime_root, password, report['checks'])
        persist_phase(client, state)
        stop(process, log)
        process = log = None

        process, log = launch(copied_exe, runtime_root, ready_file, cwd, run_dir / 'server-restart.log')
        ready = wait_ready(process, ready_file, runtime_root)
        restart_phase(ready['url'], password, state, report['checks'])
        verify_isolation(package_copy, runtime_root, report['checks'])

        default_package = run_dir / '한글 경로 [default]'
        default_package.mkdir()
        shutil.copytree(source_exe.parent, default_package, dirs_exist_ok=True)
        verify_default_root(
            default_package / source_exe.name,
            run_dir / 'default-ready.json',
            cwd,
            run_dir / 'default-server.log',
            report['checks'],
        )
        report['status'] = 'PASS'
        report['report'] = str(report_path)
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - Record any smoke failure in the artifact report.
        report['error'] = str(exc) if isinstance(exc, SmokeFailure) else f'{type(exc).__name__}: {exc}'
        return_code = 1
    finally:
        if process is not None:
            stop(process, log)
        if 'run_dir' in locals():
            report_path = run_dir / 'report.json'
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(report, ensure_ascii=True, indent=2))
    return return_code


if __name__ == '__main__':
    raise SystemExit(main())
