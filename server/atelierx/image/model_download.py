"""Getting models (#161): from a Civitai page, address or id, or from a file the person downloaded themselves.

- **Read an address**: a model page (``/models/<id>?modelVersionId=<v>``), a download address (``/api/download/models/<v>``)
  or a bare model id. Its versions and files are shown with size, base model, trigger words and license before anything
  is fetched.
- **Get**: one file at a time, through ``<name>.part`` so a broken download continues from where it stopped (HTTP Range),
  after checking the free disk space; the SHA256 Civitai gives is checked at the end. The Civitai key, when set, is sent;
  many files need it. The file lands in the folder the image server reads for its kind, below a family folder
  (``anima/``, ``sdxl/``) unless the person chooses otherwise. What Civitai said is kept by hash (model-info.json).
- **Place a file**: a ``.safetensors`` the person downloaded with a browser is hashed, looked up, and moved to the
  folder for its kind.

The queue is kept in ``state/model-downloads.json`` so an app restart shows what was left and can resume it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path, PureWindowsPath

from ..core.i18n import Msg, message_of, wire
from .model_info import CIVITAI, LICENSE_KEYS, _from_civitai
from .models import family_from_base_model
from .util import atomic_json, now, read_json

KIND_OF_TYPE = {
    'checkpoint': 'checkpoints',
    'lora': 'loras',
    'locon': 'loras',
    'dora': 'loras',
    'lycoris': 'loras',
    'vae': 'vae',
    'textualinversion': 'embeddings',
    'upscaler': 'upscale_models',
}
FILE_KIND = {'text encoder': 'text_encoders', 'vae': 'vae'}
FOLDER_KEYS = (
    'checkpoints',
    'diffusion_models',
    'loras',
    'text_encoders',
    'vae',
    'embeddings',
    'upscale_models',
)
SAFE_NAME = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,200}$')
MODEL_EXT = ('.safetensors', '.ckpt', '.pt', '.pth', '.bin', '.gguf')
CHUNK = 1024 * 1024


def parse_address(text):
    """``(model_id, version_id)`` from a Civitai address or id (either may be None)."""
    text = str(text or '').strip()
    if re.fullmatch(r'\d{1,12}', text):
        return int(text), None
    version = re.search(r'modelVersionId=(\d+)', text) or re.search(r'/api/download/models/(\d+)', text)
    model = re.search(r'/models/(\d+)', text)
    if not model and not version:
        raise ValueError(
            Msg('server.models.bad_address', 'Paste a Civitai model page, download address or model id.')
        )
    if model and '/api/download/models/' in text:
        model = None
    return (int(model.group(1)) if model else None), (int(version.group(1)) if version else None)


def kind_for(model_type, file_type, base_model):
    """The image server folder a Civitai file belongs in."""
    file_kind = FILE_KIND.get(str(file_type or '').lower())
    if file_kind:
        return file_kind
    kind = KIND_OF_TYPE.get(str(model_type or '').lower().replace(' ', ''), 'checkpoints')
    # Anima models load with the diffusion-model loader, not as checkpoints.
    if kind == 'checkpoints' and 'anima' in str(base_model or '').lower():
        return 'diffusion_models'
    return kind


class ModelDownloads:
    def __init__(self, paths, library, folders, key):
        """``folders()``: the image server's model folders by kind (or None); ``key()``: the Civitai key or None."""
        self.paths = paths
        self.library = library
        self.folders = folders
        self.key = key
        self.file = Path(paths.state) / 'model-downloads.json'
        self.lock = threading.Lock()
        self.thread = None
        self.cancel = set()
        jobs = (read_json(self.file, {}) or {}).get('jobs') or []
        # A download running when the app stopped is waiting to resume.
        for job in jobs:
            if job.get('status') == 'running':
                job['status'] = 'paused'
        self.jobs = jobs

    # --- Civitai ----------------------------------------------------------------------------------------------------
    def _request(self, url, headers=None):
        headers = {'User-Agent': 'AtelierX', **(headers or {})}
        key = self.key()
        if key and url.startswith(CIVITAI):
            headers['Authorization'] = f'Bearer {key}'
        return urllib.request.Request(url, headers=headers)

    def _json(self, url):
        try:
            with urllib.request.urlopen(self._request(url), timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise ValueError(Msg('server.models.not_on_civitai', 'Civitai has no such model.')) from error
            raise ValueError(
                Msg(
                    'server.models.civitai_error',
                    'Civitai answered {code}. Try again later.',
                    code=error.code,
                )
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ValueError(
                Msg('server.models.civitai_unreachable', 'Civitai could not be reached.')
            ) from error

    def read(self, address):
        """What a Civitai address offers: the model, its versions and their files."""
        model_id, version_id = parse_address(address)
        if model_id is None:
            version = self._json(f'{CIVITAI}/api/v1/model-versions/{version_id}')
            model_id = version.get('modelId')
        model = self._json(f'{CIVITAI}/api/v1/models/{model_id}')
        versions = []
        for v in model.get('modelVersions') or []:
            files = [
                {
                    'id': f.get('id'),
                    'name': f.get('name'),
                    'size': int((f.get('sizeKB') or 0) * 1024),
                    'type': f.get('type'),
                    'primary': bool(f.get('primary')),
                    'sha256': str((f.get('hashes') or {}).get('SHA256') or '').lower(),
                    'url': f.get('downloadUrl'),
                    'kind': kind_for(model.get('type'), f.get('type'), v.get('baseModel')),
                }
                for f in v.get('files') or []
                if str(f.get('name', '')).lower().endswith(MODEL_EXT)
            ]
            versions.append(
                {
                    'id': v.get('id'),
                    'name': v.get('name'),
                    'base_model': v.get('baseModel') or '',
                    'family': family_from_base_model(v.get('baseModel')),
                    'trained_words': v.get('trainedWords') or [],
                    'files': files,
                }
            )
        return {
            'model': {
                'id': model.get('id'),
                'name': model.get('name'),
                'type': model.get('type'),
                'nsfw': bool(model.get('nsfw')),
                'creator': (model.get('creator') or {}).get('username') or '',
                'license': {k: model.get(k) for k in LICENSE_KEYS if k in model},
                'url': f'{CIVITAI}/models/{model.get("id")}',
            },
            'versions': versions,
            'chosen_version': version_id,
            'has_key': bool(self.key()),
        }

    # --- where files go -----------------------------------------------------------------------------------------------
    def folder_for(self, kind, family=None, subfolder=None):
        """The folder of ``kind`` the image server reads (the shared model folder first), plus a family sub-folder."""
        folders = self.folders() or {}
        candidates = [
            Path(f) for f in folders.get(kind, []) if 'output' not in (p.lower() for p in Path(f).parts)
        ]
        shared = self.library.profiles.models_dir()
        if shared:
            preferred = [c for c in candidates if str(c).lower().startswith(str(shared).lower())]
            candidates = preferred + [c for c in candidates if c not in preferred]
        existing = [c for c in candidates if c.is_dir()]
        base = (existing or candidates or [None])[0]
        if base is None:
            raise ValueError(
                Msg('server.installs.no_folder', 'The image server has no folder for {kind}.', kind=kind)
            )
        sub = family if subfolder is None else subfolder
        if sub:
            if not re.fullmatch(r'[A-Za-z0-9_.\- ]{1,60}', sub) or sub in ('.', '..'):
                raise ValueError(
                    Msg('server.models.bad_subfolder', 'Use letters, digits, _ - . for the sub-folder.')
                )
            return base / sub
        return base

    # --- queue ------------------------------------------------------------------------------------------------------
    def _save(self):
        atomic_json(self.file, {'schema_version': 1, 'jobs': self.jobs[-200:]})

    def public(self):
        with self.lock:
            return {'jobs': list(reversed(self.jobs)), 'has_key': bool(self.key())}

    def add(self, body):
        """Queue one file of a version read from Civitai: ``{model, version, file, subfolder?}``."""
        model, version, chosen = body.get('model') or {}, body.get('version') or {}, body.get('file') or {}
        name = str(chosen.get('name') or '')
        if not SAFE_NAME.match(name) or not name.lower().endswith(MODEL_EXT) or not chosen.get('url'):
            raise ValueError(Msg('server.models.bad_file', 'Choose a model file of the version.'))
        if not str(chosen['url']).startswith(f'{CIVITAI}/api/download/models/'):
            raise ValueError(Msg('server.models.bad_file', 'Choose a model file of the version.'))
        kind = chosen.get('kind') if chosen.get('kind') in FOLDER_KEYS else 'checkpoints'
        folder = self.folder_for(kind, version.get('family'), body.get('subfolder'))
        target = folder / name
        if target.exists():
            raise ValueError(
                Msg('server.models.exists', '{name} is already in {folder}.', name=name, folder=str(folder))
            )
        job = {
            'id': uuid.uuid4().hex[:12],
            'status': 'queued',
            'name': name,
            'kind': kind,
            'target': str(target),
            'url': chosen['url'],
            'size': int(chosen.get('size') or 0),
            'sha256': str(chosen.get('sha256') or '').lower(),
            'received': 0,
            'model': {k: model.get(k) for k in ('id', 'name', 'type', 'nsfw', 'creator', 'license')},
            'version': {k: version.get(k) for k in ('id', 'name', 'base_model', 'trained_words')},
            'created_at': now(),
        }
        with self.lock:
            if any(
                j['target'].lower() == job['target'].lower()
                and j['status'] in ('queued', 'running', 'paused')
                for j in self.jobs
            ):
                raise ValueError(
                    Msg('server.models.already_queued', '{name} is already being downloaded.', name=name)
                )
            self.jobs.append(job)
            self._save()
        self.start()
        return self.public()

    def act(self, job_id, action):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == job_id), None)
            if job is None:
                raise ValueError(Msg('server.models.no_job', 'That download is not in the list.'))
            if action == 'cancel' and job['status'] in ('queued', 'running', 'paused'):
                self.cancel.add(job_id)
                if job['status'] != 'running':
                    job['status'] = 'cancelled'
                    Path(job['target'] + '.part').unlink(missing_ok=True)
            elif action == 'resume' and job['status'] in ('paused', 'failed'):
                job['status'], job['error'] = 'queued', None
            elif action == 'remove' and job['status'] not in ('queued', 'running'):
                self.jobs.remove(job)
            self._save()
        self.start()
        return self.public()

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            if not any(j['status'] == 'queued' for j in self.jobs):
                return
            self.thread = threading.Thread(target=self._worker, name='model-downloads', daemon=True)
            self.thread.start()

    def _worker(self):
        while True:
            with self.lock:
                job = next((j for j in self.jobs if j['status'] == 'queued'), None)
                if job is None:
                    return
                job['status'], job['started_at'] = 'running', now()
                self._save()
            try:
                self._fetch(job)
                with self.lock:
                    job['status'], job['finished_at'] = 'done', now()
            except _Cancelled:
                with self.lock:
                    job['status'] = 'cancelled'
                    Path(job['target'] + '.part').unlink(missing_ok=True)
            except Exception as error:
                with self.lock:
                    job['status'], job['error'] = 'failed', wire(message_of(error))
            with self.lock:
                self.cancel.discard(job['id'])
                self._save()

    def _fetch(self, job):
        target = Path(job['target'])
        part = Path(job['target'] + '.part')
        target.parent.mkdir(parents=True, exist_ok=True)
        have = part.stat().st_size if part.exists() else 0
        need = max(job['size'] - have, 0)
        free = shutil.disk_usage(target.parent).free
        if need and free < need + 512 * 1024**2:
            raise ValueError(
                Msg(
                    'server.models.no_space',
                    'Not enough disk space: {need} MB needed, {free} MB free.',
                    need=need // 2**20,
                    free=free // 2**20,
                )
            )
        headers = {'Range': f'bytes={have}-'} if have else {}
        try:
            response = urllib.request.urlopen(self._request(job['url'], headers), timeout=60)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise ValueError(
                    Msg(
                        'server.models.needs_key',
                        'Civitai wants an API key for this file. Add it in Settings → Image → Getting models.',
                    )
                ) from error
            if error.code == 416 and have:
                response = None
            else:
                raise ValueError(
                    Msg(
                        'server.models.civitai_error',
                        'Civitai answered {code}. Try again later.',
                        code=error.code,
                    )
                ) from error
        if response is not None:
            with response:
                resumed = have and response.status == 206
                if not resumed:
                    have = 0
                if 'text/html' in (response.headers.get('Content-Type') or ''):
                    raise ValueError(
                        Msg(
                            'server.models.needs_key',
                            'Civitai wants an API key for this file. Add it in Settings → Image → Getting models.',
                        )
                    )
                total = job['size'] or (have + int(response.headers.get('Content-Length') or 0))
                with part.open('ab' if resumed else 'wb') as out:
                    last = 0.0
                    while chunk := response.read(CHUNK):
                        if job['id'] in self.cancel:
                            raise _Cancelled
                        out.write(chunk)
                        have += len(chunk)
                        if time.monotonic() - last > 1:
                            last = time.monotonic()
                            with self.lock:
                                job['received'], job['size'] = have, total
        digest = hashlib.sha256()
        with part.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * CHUNK), b''):
                digest.update(block)
        value = digest.hexdigest()
        if job['sha256'] and value != job['sha256']:
            part.unlink(missing_ok=True)
            raise ValueError(
                Msg('server.installs.hash', 'The downloaded file does not match: {name}', name=job['name'])
            )
        os.replace(part, target)
        with self.lock:
            job['received'] = target.stat().st_size
        self.library.remember(target, value, _info_of(job))

    # --- a file the person downloaded -----------------------------------------------------------------------------------
    def candidates(self, folder):
        """Model files in a folder (the person's downloads by default), newest first."""
        base = Path(folder) if folder else Path.home() / 'Downloads'
        if not base.is_dir():
            raise ValueError(
                Msg('server.models.no_folder', 'The folder {folder} does not exist.', folder=str(base))
            )
        files = sorted(
            (p for p in base.iterdir() if p.is_file() and p.suffix.lower() in MODEL_EXT),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return {
            'folder': str(base),
            'files': [{'path': str(p), 'name': p.name, 'size': p.stat().st_size} for p in files[:200]],
        }

    def inspect(self, path):
        """Hash a downloaded file and ask Civitai what it is: where it would go."""
        file = self._downloaded(path)
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * CHUNK), b''):
                digest.update(block)
        value = digest.hexdigest()
        info, kind, family = None, None, None
        try:
            version = self._json(f'{CIVITAI}/api/v1/model-versions/by-hash/{value}')
            model = self._json(f'{CIVITAI}/api/v1/models/{version.get("modelId")}')
            info = _from_civitai(version, model)
            hit = next(
                (
                    f
                    for f in version.get('files') or []
                    if str((f.get('hashes') or {}).get('SHA256') or '').lower() == value
                ),
                {},
            )
            kind = kind_for(model.get('type'), hit.get('type'), version.get('baseModel'))
            family = family_from_base_model(version.get('baseModel'))
        except ValueError:
            info = None
        return {
            'path': str(file),
            'name': file.name,
            'size': file.stat().st_size,
            'sha256': value,
            'info': info,
            'kind': kind,
            'family': family,
        }

    def place(self, body):
        """Move a downloaded file into the folder for its kind: ``{path, kind, subfolder?, sha256?, info?}``."""
        file = self._downloaded(body.get('path'))
        kind = body.get('kind')
        if kind not in FOLDER_KEYS:
            raise ValueError(Msg('server.models.choose_kind', 'Choose what kind of model this is.'))
        folder = self.folder_for(kind, None, body.get('subfolder') or '')
        target = folder / file.name
        if target.exists():
            raise ValueError(
                Msg(
                    'server.models.exists',
                    '{name} is already in {folder}.',
                    name=file.name,
                    folder=str(folder),
                )
            )
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(file), str(target))
        if body.get('sha256') and isinstance(body.get('info'), dict):
            self.library.remember(target, str(body['sha256']).lower(), body['info'])
        return {'target': str(target)}

    @staticmethod
    def _downloaded(path):
        file = Path(str(path or ''))
        if not file.is_file() or file.suffix.lower() not in MODEL_EXT:
            raise ValueError(Msg('server.models.bad_file', 'Choose a model file of the version.'))
        return file


class _Cancelled(Exception):
    pass


def _info_of(job):
    model, version = job.get('model') or {}, job.get('version') or {}
    return {
        'source': 'civitai',
        'model_id': model.get('id'),
        'version_id': version.get('id'),
        'model_name': model.get('name') or '',
        'version_name': version.get('name') or '',
        'base_model': version.get('base_model') or '',
        'trained_words': list(version.get('trained_words') or []),
        'author': model.get('creator') or '',
        'nsfw': bool(model.get('nsfw')),
        'license': model.get('license') or {},
        'from': 'download',
    }


def file_name_ok(name):
    return bool(SAFE_NAME.match(name)) and PureWindowsPath(name).name == name
