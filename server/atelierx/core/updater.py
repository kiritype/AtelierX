"""In-app update (#48): download the latest release, check it against its published SHA256, keep a backup of the user
data, then let a small script swap the program files after the app has closed and start the new version.

Only the packaged app updates itself. The program files are the top-level entries of the release ZIP's ``AtelierX/``
folder (the executable, ``_internal``, the manual, notices …); the user data folders beside them (config, state, data,
output) are never touched. The replaced entries stay as ``<name>.old`` until the new version starts and removes them,
so a failed swap can be rolled back.
"""

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

import httpx

from .. import __version__
from .about import LATEST_URL, version_key
from .fsutil import read_json, write_json
from .i18n import AppError, Msg

USER_DATA = ('config', 'state', 'data', 'output')
ASSET = re.compile(r'^AtelierX-(\d+\.\d+\.\d+)-windows-x64\.zip$')
STATE_SKIPPED_IN_BACKUP = ('update', 'packages', 'webview', 'logs')
TIMEOUT = httpx.Timeout(connect=10, read=120, write=30, pool=10)

SCRIPT = r"""param([int]$AppPid, [string]$Root, [string]$New, [string]$Result, [switch]$NoStart)
# AtelierX in-app update: swap the program files once the app has closed, then start the new version.
$ErrorActionPreference = 'Stop'
$keep = @('config', 'state', 'data', 'output')
function Write-Result([string]$State, [string]$Detail) {
  $json = @{ state = $State; detail = $Detail; at = (Get-Date).ToString('o') } | ConvertTo-Json -Compress
  [System.IO.File]::WriteAllText($Result, $json)
}
try { Wait-Process -Id $AppPid -Timeout 120 -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 700
$names = @(Get-ChildItem -LiteralPath $New | ForEach-Object { $_.Name } | Where-Object { $keep -notcontains $_ })
$moved = @(); $placed = @()
try {
  foreach ($n in $names) {
    $target = Join-Path $Root $n
    $old = "$target.old"
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
    if (Test-Path -LiteralPath $target) { Move-Item -LiteralPath $target -Destination $old; $moved += $n }
  }
  foreach ($n in $names) {
    Move-Item -LiteralPath (Join-Path $New $n) -Destination (Join-Path $Root $n)
    $placed += $n
  }
  Write-Result 'ok' ''
} catch {
  $err = $_.Exception.Message
  foreach ($n in $placed) { Remove-Item -LiteralPath (Join-Path $Root $n) -Recurse -Force -ErrorAction SilentlyContinue }
  foreach ($n in $moved) {
    $target = Join-Path $Root $n
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue }
    Move-Item -LiteralPath "$target.old" -Destination $target -ErrorAction SilentlyContinue
  }
  Write-Result 'failed' $err
}
if (-not $NoStart) { Start-Process -FilePath (Join-Path $Root 'AtelierX.exe') -WorkingDirectory $Root }
"""


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Updater:
    def __init__(self, paths, busy=list):
        self.paths = paths
        self.folder = Path(paths.state) / 'update'
        self.busy = busy  # names of work in progress that an update would cut off
        self.lock = threading.Lock()
        self.state = {'state': 'idle'}
        self.transport = None  # tests answer HTTP with httpx.MockTransport
        # The release to update to; a test of the packaged app points this at a local copy.
        self.release_url = os.environ.get('ATELIERX_UPDATE_RELEASE_URL') or LATEST_URL
        self.exit_app = None  # set by the desktop launcher: closes the window (or stops the headless server)
        self.task = None

    # --- status -----------------------------------------------------------------------------------------------------
    def packaged(self):
        return (
            bool(getattr(sys, 'frozen', False)) and (Path(self.paths.root) / 'BUILD-MANIFEST.json').is_file()
        )

    def status(self):
        with self.lock:
            out = dict(self.state)
        out['packaged'] = self.packaged()
        out['current'] = __version__
        result = read_json(self.folder / 'result.json')
        if result:
            out['last_result'] = result
        return out

    def _set(self, **values):
        with self.lock:
            self.state = values

    def forget_result(self):
        (self.folder / 'result.json').unlink(missing_ok=True)

    # --- download and check -----------------------------------------------------------------------------------------
    def start(self):
        """Begin preparing the update in the background; the screen follows ``status``."""
        if not self.packaged():
            raise AppError(Msg('server.update.not_packaged', 'Only the packaged app updates itself.'), 400)
        busy = self.busy()
        if busy:
            raise AppError(
                Msg(
                    'server.update.busy',
                    'Finish or stop first: {what}.',
                    what=', '.join(str(b) for b in busy),
                ),
                409,
            )
        with self.lock:
            if self.state.get('state') in (
                'checking',
                'downloading',
                'verifying',
                'extracting',
                'backing_up',
            ):
                raise AppError(Msg('server.update.running', 'The update is already being prepared.'), 409)
            self.state = {'state': 'checking'}
        self.task = asyncio.get_running_loop().create_task(self._prepare_safely())
        return self.status()

    async def _prepare_safely(self):
        try:
            await self.prepare()
        except AppError as error:
            self._set(state='failed', error=error.msg.as_dict())
        except Exception as error:  # noqa: BLE001 - reported on the screen, the app keeps running
            self._set(
                state='failed',
                error=Msg(
                    'server.update.failed', 'The update could not be prepared: {error}', error=str(error)
                ).as_dict(),
            )

    async def prepare(self):
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, transport=self.transport
        ) as client:
            release = await self._release(client)
            tag = release.get('tag_name') or ''
            if (version_key(tag) or (0, 0, 0)) <= (version_key(__version__) or (0, 0, 0)):
                raise AppError(Msg('server.update.none', 'This is the latest version.'), 400)
            assets = {a.get('name'): a for a in release.get('assets') or []}
            zip_asset = next((a for name, a in assets.items() if ASSET.match(str(name or ''))), None)
            sha_asset = assets.get(f'{zip_asset["name"]}.sha256') if zip_asset else None
            if not zip_asset or not sha_asset:
                raise AppError(
                    Msg('server.update.no_asset', 'The release has no Windows package with its SHA256.'), 502
                )
            expected = (
                (await self._get(client, sha_asset['browser_download_url'])).text.split()[0].strip().lower()
            )
            if not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise AppError(
                    Msg('server.update.no_asset', 'The release has no Windows package with its SHA256.'), 502
                )
            if self.folder.exists():
                shutil.rmtree(self.folder / 'new', ignore_errors=True)
            self.folder.mkdir(parents=True, exist_ok=True)
            target = self.folder / zip_asset['name']
            total = int(zip_asset.get('size') or 0)
            self._set(state='downloading', version=tag, received=0, total=total)
            received = 0
            async with client.stream('GET', zip_asset['browser_download_url']) as response:
                if response.status_code >= 400:
                    raise AppError(
                        Msg(
                            'server.update.download',
                            'The download failed (HTTP {status}).',
                            status=response.status_code,
                        ),
                        502,
                    )
                with target.open('wb') as out:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        out.write(chunk)
                        received += len(chunk)
                        self._set(state='downloading', version=tag, received=received, total=total)
        self._set(state='verifying', version=tag)
        actual = await asyncio.to_thread(_sha256, target)
        if actual != expected:
            target.unlink(missing_ok=True)
            raise AppError(
                Msg(
                    'server.update.mismatch',
                    'The download does not match the published SHA256, so it was not used.',
                ),
                502,
            )
        self._set(state='extracting', version=tag)
        await asyncio.to_thread(self._extract, target)
        self._set(state='backing_up', version=tag)
        backup = await asyncio.to_thread(self._backup, tag)
        self._set(state='ready', version=tag, backup=backup.name)

    async def _release(self, client):
        response = await self._get(client, self.release_url, json=True)
        return response.json()

    async def _get(self, client, url, json=False):
        headers = {'User-Agent': f'AtelierX/{__version__}'}
        if json:
            headers['Accept'] = 'application/vnd.github+json'
        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise AppError(
                Msg('server.about.update_unreachable', 'Could not reach GitHub to check for updates.'), 502
            ) from exc
        if response.status_code >= 400:
            raise AppError(
                Msg(
                    'server.update.download',
                    'The download failed (HTTP {status}).',
                    status=response.status_code,
                ),
                502,
            )
        return response

    def _extract(self, archive_path):
        new = self.folder / 'new'
        shutil.rmtree(new, ignore_errors=True)
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                if name.endswith('/'):
                    continue
                parts = PurePosixPath(name).parts
                if (
                    '\\' in name
                    or ':' in name
                    or name.startswith('/')
                    or not parts
                    or parts[0] != 'AtelierX'
                    or any(p in ('', '.', '..') for p in parts)
                ):
                    raise AppError(
                        Msg(
                            'server.update.bad_package', 'The downloaded package is not laid out as expected.'
                        ),
                        502,
                    )
                if len(parts) > 1 and parts[1] in USER_DATA:
                    continue  # a package never brings user data
                target = new.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out, 1024 * 1024)
        program = new / 'AtelierX'
        if not (program / 'AtelierX.exe').is_file() or not (program / '_internal').is_dir():
            raise AppError(
                Msg('server.update.bad_package', 'The downloaded package is not laid out as expected.'), 502
            )

    def _backup(self, tag):
        root = Path(self.paths.root)
        stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
        target = self.folder / f'backup-before-{tag}-{stamp}.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for name in ('config', 'data', 'state'):
                folder = root / name
                if not folder.is_dir():
                    continue
                for path in folder.rglob('*'):
                    rel = path.relative_to(root)
                    if not path.is_file() or (
                        name == 'state' and len(rel.parts) > 1 and rel.parts[1] in STATE_SKIPPED_IN_BACKUP
                    ):
                        continue
                    if path.name == 'desktop.lock':
                        continue
                    archive.write(path, rel.as_posix())
        return target

    # --- swap -------------------------------------------------------------------------------------------------------
    def script_path(self):
        return self.folder / 'apply.ps1'

    def write_script(self):
        path = self.script_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # PowerShell 5.1 reads a script without a byte order mark in the system code page.
        path.write_text(SCRIPT, encoding='utf-8-sig')
        return path

    def apply(self):
        with self.lock:
            if self.state.get('state') != 'ready':
                raise AppError(Msg('server.update.not_ready', 'Prepare the update first.'), 409)
            version = self.state.get('version')
        if not self.packaged():
            raise AppError(Msg('server.update.not_packaged', 'Only the packaged app updates itself.'), 400)
        script = self.write_script()
        (self.folder / 'result.json').unlink(missing_ok=True)
        write_json(self.folder / 'pending.json', {'version': version, 'from': __version__})
        flags = 0
        if sys.platform == 'win32':
            flags = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        subprocess.Popen(
            [
                'powershell',
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-WindowStyle',
                'Hidden',
                '-File',
                str(script),
                '-AppPid',
                str(os.getpid()),
                '-Root',
                str(Path(self.paths.root)),
                '-New',
                str(self.folder / 'new' / 'AtelierX'),
                '-Result',
                str(self.folder / 'result.json'),
            ],
            creationflags=flags,
            close_fds=True,
        )
        self._set(state='restarting', version=version)
        if self.exit_app:
            threading.Timer(0.8, self.exit_app).start()
        return self.status()


def finish_update(paths):
    """At start: remove what the last update replaced, and note its result for the screen."""
    folder = Path(paths.state) / 'update'
    pending = read_json(folder / 'pending.json')
    if not pending:
        return None
    root = Path(paths.root)
    result = read_json(folder / 'result.json') or {}
    if result.get('state') == 'ok':
        for old in root.glob('*.old'):
            shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
        shutil.rmtree(folder / 'new', ignore_errors=True)
        for archive in folder.glob('AtelierX-*.zip'):
            archive.unlink(missing_ok=True)
    write_json(
        folder / 'result.json', {**result, 'version': pending.get('version'), 'from': pending.get('from')}
    )
    (folder / 'pending.json').unlink(missing_ok=True)
    return result
