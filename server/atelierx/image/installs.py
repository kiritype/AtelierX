"""Settings → Install (decision 0019): what the image features need besides the app, each in its own section.

- tools: uv and Git. Used from PATH when there; otherwise portable copies are downloaded into ``<app>/bin/``.
- nodes: the image server's custom nodes (node_install).
- models: model files from defaults/image/downloads.json, saved into a folder the image server already reads and
  checked against their published sha256. Files only on sites that need an account are listed with a link.
- trainer: the LoRA trainer (anima_lora at the tested commit), its own Python environment (uv sync) and the
  model-path patch; afterwards the training settings are filled in where they are empty.

One install runs at a time in a background thread; its log is kept for the settings screen. Nothing runs unless the
person presses the section's button.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from ..core.i18n import Msg, message_of
from ..core.lifecycle import UNFINISHED
from ..core.proc import NO_WINDOW, stop_tree
from . import comfy_locate, node_install
from . import settings as image_settings
from .lora import setup as trainer_setup
from .util import now, read_json

log = logging.getLogger(__name__)

SECTIONS = ('tools', 'nodes', 'models', 'trainer', 'training')
LOG_LINES = 600
NODES_CHECK_TTL = 60
TOOL_CHECK_TTL = 30.0
TOOL_CHECK_TIMEOUT = 4.0
# Helper tools at a fixed version, checked by size and sha256 like the models (decision 0019). Raise them on purpose,
# with the external components page of the manual.
TOOLS = {
    'uv': {
        'version': '0.12.23',
        'url': 'https://github.com/astral-sh/uv/releases/download/0.12.23/uv-x86_64-pc-windows-msvc.zip',
        'size': 18043715,
        'sha256': '75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90',
    },
    'git': {
        'version': '2.56.0.2',
        'url': 'https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.2/MinGit-2.56.0.2-64-bit.zip',
        'size': 39806486,
        'sha256': 'da35e72aa21c005a5a0d298cfbae110bc1609a815730ea0dde84b01a1b3cd3be',
    },
}
TRAINER = {
    'repo': 'sorryhyun/anima_lora',
    'commit': '69ff96299e895636de39c69263ca63b5d4864917',
    'license': 'MIT (with Apache-2.0 parts)',
}
# anima_lora's lock file also names its companion as a sibling folder, so uv needs it next to the trainer.
COMPANION = {'repo': 'sorryhyun/anime_tools', 'commit': '74aa014ba12db74286b17e634056683f7f2b44d7'}
USER_AGENT = {'User-Agent': 'AtelierX'}


class Cancelled(Exception):
    pass


def apply_patch(text, patch):
    """Apply a unified diff of one file to ``text``; hunks already applied are left as they are."""
    hunks, current = [], None
    for line in patch.splitlines():
        if line.startswith('@@'):
            current = ([], [])
            hunks.append(current)
        elif current is not None and line[:1] in (' ', '-', '+'):
            if line[0] in (' ', '-'):
                current[0].append(line[1:])
            if line[0] in (' ', '+'):
                current[1].append(line[1:])
    newline = '\r\n' if '\r\n' in text else '\n'
    for old, new in hunks:
        before, after = newline.join(old), newline.join(new)
        if before in text:
            text = text.replace(before, after, 1)
        elif after not in text:
            raise ValueError(
                Msg('server.installs.patch_failed', 'The patch does not fit this trainer version.')
            )
    return text


class Installs:
    def __init__(self, runtime):
        self.rt = runtime
        self.paths = runtime.paths
        self.bin = Path(self.paths.root) / 'bin'
        self.lock = threading.Lock()
        self.run = None  # {section, status, log, started_at, finished_at, error}
        self.process = None
        self.cancel_requested = False
        self._tool_cache = {}
        self._tool_lock = threading.Lock()
        # The node check runs git in every custom_nodes folder; the page polls, so it is reused for a while.
        self._nodes_cache = None  # (expires, comfy folder, result)

    # --- helpers --------------------------------------------------------------------------------------------------
    def _valid_tool(self, path):
        """Confirm an executable responds to --version, caching each check briefly."""
        path = str(path)
        try:
            stat = Path(path).stat()
            key = (path.casefold(), stat.st_mtime_ns, stat.st_size)
        except OSError:
            return False
        now = time.monotonic()
        with self._tool_lock:
            cached = self._tool_cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
        try:
            done = subprocess.run(
                [path, '--version'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=TOOL_CHECK_TIMEOUT,
                check=False,
                creationflags=NO_WINDOW,
            )
            valid = done.returncode == 0 and bool((done.stdout or done.stderr).strip())
        except (OSError, subprocess.SubprocessError):
            valid = False
        with self._tool_lock:
            self._tool_cache[key] = (now + TOOL_CHECK_TTL, valid)
            while len(self._tool_cache) > 16:
                self._tool_cache.pop(next(iter(self._tool_cache)))
        return valid

    def _tool(self, name):
        local = self.bin / 'uv.exe' if name == 'uv' else self.bin / 'git' / 'cmd' / 'git.exe'
        candidates = [shutil.which(name)]
        if local.is_file():
            candidates.append(str(local))
        for candidate in candidates:
            if candidate and self._valid_tool(candidate):
                return candidate
        return None

    def uv(self):
        return self._tool('uv')

    def git(self):
        return self._tool('git')

    def env(self):
        """PATH with the app's portable tools first, for child processes that call git or uv themselves."""
        extra = [str(self.bin), str(self.bin / 'git' / 'cmd')]
        return {
            'PATH': os.pathsep.join([*extra, os.environ.get('PATH', '')]),
            'PYTHONIOENCODING': 'utf-8',
            'NO_COLOR': '1',
        }

    def child_env(self):
        # The app's own virtual environment must not leak into the trainer's uv.
        env = {**os.environ, **self.env()}
        env.pop('VIRTUAL_ENV', None)
        return env

    def _say(self, text):
        with self.lock:
            lines = self.run['log']
            lines.append(str(text))
            del lines[:-LOG_LINES]

    def _check(self):
        if self.cancel_requested:
            raise Cancelled

    def _download(self, url, target, size=None, sha256=None):
        """Stream ``url`` into ``target`` through a .part file; checks size and sha256 when known."""
        self._check()
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + '.part')
        digest = hashlib.sha256()
        request = urllib.request.Request(url, headers=USER_AGENT)
        done, shown = 0, -1
        with urllib.request.urlopen(request, timeout=60) as response, part.open('wb') as out:
            total = size or int(response.headers.get('Content-Length') or 0)
            while chunk := response.read(1024 * 1024):
                self._check()
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                percent = int(done * 100 / total) if total else 0
                if percent // 10 != shown // 10:
                    shown = percent
                    self._say(f'  {target.name}: {percent}% ({done // 2**20} / {total // 2**20} MB)')
        if size and done != size:
            part.unlink(missing_ok=True)
            raise RuntimeError(
                Msg('server.installs.size', 'The download is incomplete: {name}', name=target.name)
            )
        if sha256 and digest.hexdigest() != sha256:
            part.unlink(missing_ok=True)
            raise RuntimeError(
                Msg('server.installs.hash', 'The downloaded file does not match: {name}', name=target.name)
            )
        os.replace(part, target)

    def _call(self, cmd, cwd=None):
        """Run a command, streaming its output lines into the log."""
        self._check()
        self._say('$ ' + ' '.join(str(c) for c in cmd))
        with self.lock:
            self.process = subprocess.Popen(
                [str(c) for c in cmd],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self.child_env(),
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=NO_WINDOW,
            )
        for line in self.process.stdout:
            line = line.rstrip()
            if line:
                self._say('  ' + line[-400:])
        code = self.process.wait()
        self._check()
        if code:
            raise RuntimeError(
                Msg(
                    'server.installs.command_failed',
                    '{name} failed (exit {code}).',
                    name=Path(str(cmd[0])).name,
                    code=code,
                )
            )

    # --- status ---------------------------------------------------------------------------------------------------
    def comfy_dirs(self):
        """(ComfyUI folder, its Python) from the connection settings or the running install."""
        config = self.rt.control.config
        if config.get('comfy_path') and comfy_locate.is_comfy_dir(Path(config['comfy_path'])):
            comfy = Path(config['comfy_path'])
            python = (
                Path(config['python_path']) if config.get('python_path') else comfy_locate.python_for(comfy)
            )
            return comfy, python
        found = comfy_locate.candidates(self.rt.comfy.url)
        running = next((c for c in found if c['source'] == 'running'), None)
        if running:
            comfy = Path(running['comfy_path'])
            return comfy, Path(running['python_path']) if running.get(
                'python_path'
            ) else comfy_locate.python_for(comfy)
        return None, None

    def manifest(self):
        return read_json(Path(self.paths.defaults) / 'image' / 'downloads.json') or {'groups': []}

    def model_folders(self):
        return comfy_locate.model_folders(self.rt.comfy.url)

    def _target_folder(self, folders, kind):
        """A folder the image server reads for ``kind``: under the shared models folder when set, never output/."""
        candidates = [
            Path(f) for f in folders.get(kind, []) if 'output' not in (p.lower() for p in Path(f).parts)
        ]
        shared = image_settings.get(self.paths, 'models').get('models_dir')
        if shared:
            preferred = [c for c in candidates if str(c).lower().startswith(str(Path(shared)).lower())]
            candidates = preferred + [c for c in candidates if c not in preferred]
        existing = [c for c in candidates if c.is_dir()]
        return (existing or candidates or [None])[0]

    def _models(self):
        folders = self.model_folders()
        groups = []
        for group in self.manifest()['groups']:
            items = []
            for item in group['items']:
                present = None
                for folder in (folders or {}).get(item['folder'], []):
                    if (Path(folder) / item['file']).is_file():
                        present = str(Path(folder) / item['file'])
                        break
                target = self._target_folder(folders or {}, item['folder']) if folders else None
                items.append({**item, 'installed': present, 'target': str(target) if target else None})
            groups.append({**group, 'items': items})
        return {'connected': folders is not None, 'groups': groups}

    def _trainer(self):
        status = trainer_setup.status(self.paths)
        folder = Path(status['settings']['trainer_dir'])
        return {
            **{k: v for k, v in status.items() if k != 'settings'},
            'folder': str(folder),
            'venv': (folder / '.venv').is_dir(),
            'version': TRAINER,
        }

    def status(self):
        comfy, python = self.comfy_dirs()
        nodes = None
        if comfy:
            cached = self._nodes_cache
            if cached and cached[0] > time.monotonic() and cached[1] == str(comfy):
                plan = cached[2]
            else:
                plan = node_install.plan(self.paths.defaults.parent, comfy, git=self.git() or 'git')
                self._nodes_cache = (time.monotonic() + NODES_CHECK_TTL, str(comfy), plan)
            nodes = {**plan, 'python': str(python) if python else None}
        with self.lock:
            run = dict(self.run, log=list(self.run['log'])) if self.run else None
        return {
            'run': run,
            'tools': {
                'uv': self.uv(),
                'git': self.git(),
                'bin': str(self.bin),
                # What a missing tool would download, shown before an install that needs it.
                'downloads': {
                    name: {'version': t['version'], 'size': t['size']} for name, t in TOOLS.items()
                },
            },
            'nodes': nodes,
            'models': self._models(),
            'trainer': self._trainer(),
        }

    # --- running ---------------------------------------------------------------------------------------------------
    def start(self, section, body=None):
        if section not in SECTIONS:
            raise ValueError(Msg('server.installs.unknown', 'Unknown install section.'))
        with self.lock:
            if self.run and self.run['status'] in UNFINISHED:
                raise ValueError(
                    Msg('server.installs.busy', 'Another install is running. Wait for it to finish.')
                )
            self.run = {
                'section': section,
                'status': 'running',
                'log': [],
                'started_at': now(),
                'error': None,
            }
            self.cancel_requested = False
        work = getattr(self, f'_install_{section}')
        threading.Thread(
            target=self._execute, args=(work, body or {}), daemon=True, name=f'install-{section}'
        ).start()
        return {'ok': True}

    def cancel(self):
        with self.lock:
            self.cancel_requested = True
            if self.run and self.run['status'] == 'running':
                self.run['status'] = 'cancelling'
            stop_tree(self.process)
        return {'ok': True}

    def shutdown(self):
        """The app is closing: an install in progress stops with it."""
        if self.run and self.run['status'] in UNFINISHED:
            self.cancel()

    def _execute(self, work, body):
        try:
            work(body)
            status, error = 'done', None
            self._say('✓ ' + 'done')
        except Cancelled:
            status, error = 'cancelled', None
        except Exception as exc:  # every failure is shown in the section
            log.exception('Install failed')
            status, error = 'failed', message_of(exc)
            self._say('✗ ' + str(error))
        with self.lock:
            self.run.update(status=status, error=error, finished_at=now())
            self.process = None
        self._nodes_cache = None  # an install may have changed custom_nodes

    def _install_tools(self, body):
        wanted = body.get('items') or ['uv', 'git']
        self.bin.mkdir(parents=True, exist_ok=True)
        if 'uv' in wanted and not self.uv():
            archive = self._fetch_tool('uv', self.bin / 'uv.zip')
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    if Path(name).name in ('uv.exe', 'uvx.exe'):
                        (self.bin / Path(name).name).write_bytes(z.read(name))
            archive.unlink(missing_ok=True)
        if 'git' in wanted and not self.git():
            archive = self._fetch_tool('git', self.bin / f'MinGit-{TOOLS["git"]["version"]}-64-bit.zip')
            with zipfile.ZipFile(archive) as z:
                z.extractall(self.bin / 'git')
            archive.unlink(missing_ok=True)
        with self._tool_lock:
            self._tool_cache.clear()
        unavailable = [name for name in wanted if name in ('uv', 'git') and not getattr(self, name)()]
        if unavailable:
            raise RuntimeError(
                Msg(
                    'server.installs.tool_unusable',
                    'Could not install or run {name}. Check the install log and retry.',
                    name=', '.join(unavailable),
                )
            )
        self._say(f'uv: {self.uv()}')
        self._say(f'git: {self.git()}')

    def _fetch_tool(self, name, archive):
        """Download a helper tool at its fixed version; a failed download says which tool and why."""
        tool = TOOLS[name]
        label = 'Git (MinGit)' if name == 'git' else name
        self._say(f'{label} {tool["version"]}: download')
        try:
            self._download(tool['url'], archive, size=tool['size'], sha256=tool['sha256'])
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                Msg(
                    'server.installs.tool_http',
                    'GitHub refused the {name} download (HTTP {status}). Wait a while and retry.',
                    name=label,
                    status=error.code,
                )
            ) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise RuntimeError(
                Msg(
                    'server.installs.tool_offline',
                    'Could not reach GitHub to download {name}. Check the network and retry.',
                    name=label,
                )
            ) from error
        return archive

    def _need_tools(self, *names):
        missing = [n for n in names if not getattr(self, n)()]
        if missing:
            self._install_tools({'items': missing})

    def _install_nodes(self, body):
        comfy, python = self.comfy_dirs()
        if not comfy or not python:
            raise ValueError(
                Msg(
                    'server.installs.no_comfy',
                    'The image server folder was not found. Start it or set its folder in Settings → Image.',
                )
            )
        self._need_tools('git')
        node_install.carry_out(
            self.paths.defaults.parent,
            comfy,
            python,
            body.get('features'),
            log=self._say,
            git=self.git(),
            env=self.env(),
            # Through _call: the process is cancellable and stopped with the app, and no step starts after a cancel.
            run=lambda cmd, _log, cwd=None, env=None: self._call(cmd, cwd=cwd),
        )
        self._say('Restart the image server to load the new nodes.')

    def _install_models(self, body):
        folders = self.model_folders()
        if folders is None:
            raise ValueError(
                Msg(
                    'server.installs.comfy_off',
                    'Start the image server first; models go into the folders it reads.',
                )
            )

        wanted = set(body.get('items') or [])
        models = self._models()
        for group in models['groups']:
            for item in group['items']:
                if (
                    item.get('manual')
                    or item['installed']
                    or (wanted and item['id'] not in wanted and group['id'] not in wanted)
                ):
                    continue
                if not item['target']:
                    raise ValueError(
                        Msg(
                            'server.installs.no_folder',
                            'The image server has no folder for {kind}.',
                            kind=item['folder'],
                        )
                    )
                self._say(f'{item["file"]} → {item["target"]}')
                self._download(
                    item['url'], Path(item['target']) / item['file'], item.get('size'), item.get('sha256')
                )
        self._fill_training_models()

    def _training_items(self):
        """Manifest model entries explicitly marked as training bases."""
        return [
            item for group in self.manifest()['groups'] for item in group['items'] if item.get('training')
        ]

    def _install_training(self, body):
        """Install only tagged training bases and the trainer, after checking model destinations."""
        folders = self.model_folders()
        if folders is None:
            raise ValueError(
                Msg(
                    'server.installs.comfy_off',
                    'Start the image server first; training models go into the folders it reads.',
                )
            )

        settings = trainer_setup.settings(self.paths)
        if not settings.get('lora_dir') and not comfy_locate.suggest_lora_dir(folders):
            raise ValueError(
                Msg(
                    'server.installs.no_lora_folder',
                    'The image server has no usable LoRA output folder. Add a LoRA folder in ComfyUI, or set one in Settings → Image → LoRA training.',
                )
            )

        # Resolve every destination before downloading models or building the trainer environment.
        items = self._training_items()
        planned = []
        for item in items:
            installed = next(
                (
                    Path(folder) / item['file']
                    for folder in folders.get(item['folder'], [])
                    if (Path(folder) / item['file']).is_file()
                ),
                None,
            )
            target = self._target_folder(folders, item['folder'])
            if installed is None and target is None:
                raise ValueError(
                    Msg(
                        'server.installs.no_folder',
                        'The image server has no folder for {kind}.',
                        kind=item['folder'],
                    )
                )
            planned.append((item, installed, target))

        for item, installed, target in planned:
            self._check()
            if installed:
                self._say(f'{item["file"]}: already installed ({installed})')
                continue
            self._say(f'{item["file"]} → {target}')
            self._download(item['url'], target / item['file'], item.get('size'), item.get('sha256'))
        self._fill_training_models()
        self._check()
        self._install_trainer(body)
        status = trainer_setup.status(self.paths)
        incomplete = []
        if not status['trainer_found']:
            incomplete.append('trainer files')
        if not status['python_found']:
            incomplete.append('trainer Python')
        if not status['patched']:
            incomplete.append('model-path patch')
        if not status['lora_dir_found']:
            incomplete.append('LoRA output folder')
        incomplete.extend(
            name for name, ready in status['files'].items() if name.startswith('official.') and not ready
        )
        if incomplete:
            raise RuntimeError(
                Msg(
                    'server.installs.training_incomplete',
                    'The trainer was installed, but setup still needs: {items}. Check Settings → Image → LoRA training; existing custom paths were preserved.',
                    items=', '.join(incomplete),
                )
            )

    def _fill_training_models(self):
        """Put downloaded training-base files into the training settings where those are empty."""
        found = {}
        for group in self._models()['groups']:
            for item in group['items']:
                if item.get('training') and item['installed']:
                    found[item['training']] = item['installed']
        current = image_settings.get(self.paths, 'training')
        official = (current.get('bases') or {}).get('official') or {}
        missing = {key: path for key, path in found.items() if not str(official.get(key) or '').strip()}
        if missing:
            image_settings.save(self.paths, 'training', {'bases': {'official': {**official, **missing}}})
            self._say('Training settings: official Anima base files set.')

    def _fetch_repo(self, source, folder):
        """A repository at one commit, as a zip (no git needed), unpacked into ``folder``."""
        if folder.exists() and any(folder.iterdir()):
            raise ValueError(
                Msg(
                    'server.installs.folder_taken',
                    'The trainer folder is not empty: {path}',
                    path=str(folder),
                )
            )
        self._say(f'{source["repo"]} {source["commit"][:7]} → {folder}')
        folder.parent.mkdir(parents=True, exist_ok=True)
        archive = folder.parent / f'{folder.name}.zip'
        self._download(f'https://codeload.github.com/{source["repo"]}/zip/{source["commit"]}', archive)
        with zipfile.ZipFile(archive) as z:
            root = z.namelist()[0].split('/')[0]
            staging = folder.parent / f'.{root}'
            z.extractall(staging)
        archive.unlink(missing_ok=True)
        if folder.exists():
            folder.rmdir()
        shutil.move(str(staging / root), str(folder))
        shutil.rmtree(staging, ignore_errors=True)

    def _install_trainer(self, body):
        self._need_tools('uv', 'git')
        values = trainer_setup.settings(self.paths)
        folder = Path(values['trainer_dir'])
        if not (folder / 'train.py').is_file():
            self._fetch_repo(TRAINER, folder)
        companion = folder.parent / 'anime_tools'
        if not (companion / 'pyproject.toml').is_file():
            self._fetch_repo(COMPANION, companion)
        self._say('Python environment (uv sync): Python 3.13 and CUDA PyTorch, several GB the first time')
        self._call([self.uv(), 'sync'], cwd=folder)
        preprocess = folder / 'scripts' / 'tasks' / 'preprocess.py'
        patch = (trainer_setup.shipped(self.paths) / 'preprocess-model-paths.patch').read_text(
            encoding='utf-8'
        )
        text = preprocess.read_text(encoding='utf-8')
        patched = apply_patch(text, patch)
        if patched != text:
            preprocess.write_text(patched, encoding='utf-8', newline='')
            self._say('Model-path patch applied.')
        changes = {}
        if not image_settings.get(self.paths, 'training').get('trainer_dir'):
            changes['trainer_dir'] = str(folder)
        if not values.get('lora_dir'):
            suggested = comfy_locate.suggest_lora_dir(self.model_folders())
            if suggested:
                changes['lora_dir'] = suggested
        if changes:
            image_settings.save(self.paths, 'training', changes)
            self._say(f'Training settings: {", ".join(changes)} set.')
        self._fill_training_models()

    # --- image server restart ---------------------------------------------------------------------------------------
    def restart_comfy(self):
        """Restart the image server after new nodes: through this app when it runs it, else through its manager."""
        self._nodes_cache = None
        status = self.rt.control.status()
        if status.get('can_restart'):
            return self.rt.control.control('restart')
        try:
            self.rt.comfy.request('/v2/manager/reboot', {})
        except Exception:  # the connection drops while it restarts; that is expected
            log.info('The image server dropped the connection while restarting.')
        # First it goes away, then it comes back with the new nodes.
        for _ in range(15):
            if not comfy_locate.running(self.rt.comfy.url):
                break
            time.sleep(1)
        for _ in range(90):
            time.sleep(2)
            if comfy_locate.running(self.rt.comfy.url):
                return {'ok': True, 'restarted': True}
        raise RuntimeError(
            Msg('server.installs.restart_failed', 'The image server did not come back. Start it yourself.')
        )
