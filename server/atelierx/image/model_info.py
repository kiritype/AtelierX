"""My models (#161): the files the image server offers, where they came from and what Civitai says about them.

Sources, most specific first:

- what the app looked up on Civitai by the file's SHA256 (``data/image/model-info.json``, kept by hash so a renamed or
  moved file keeps its information),
- Stability Matrix's ``<file>.cm-info.json`` next to the file (read only; the app writes nothing into model folders),
- LoRAs trained by the app (``atelierx\\`` folder link, #160).

Hashing a model takes a few seconds per GB, so it happens only when the person asks for a lookup. The hash is remembered
with the file's size and change time.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path, PureWindowsPath

from ..core.i18n import Msg
from .lora.link import LINK_NAME
from .util import atomic_json, read_json

CIVITAI = 'https://civitai.com'
# Catalog list → (kind shown, ComfyUI folder key, Stability Matrix folder names, family kind of ModelProfiles).
KINDS = {
    'checkpoint': ('checkpoints', ('StableDiffusion', 'checkpoints'), 'checkpoints'),
    'diffusion_model': (
        'diffusion_models',
        ('DiffusionModels', 'diffusion_models', 'unet'),
        'diffusion_models',
    ),
    'lora': ('loras', ('Lora', 'loras'), 'loras'),
    'text_encoder': ('text_encoders', ('TextEncoders', 'text_encoders', 'clip'), 'text_encoders'),
    'vae': ('vae', ('VAE', 'vae'), 'vaes'),
    'upscale_model': ('upscale_models', ('ESRGAN', 'upscale_models'), None),
}
LICENSE_KEYS = ('allowNoCredit', 'allowCommercialUse', 'allowDerivatives', 'allowDifferentLicense')


def _entries(catalog):
    """``[(kind, catalog name, file name)]`` of everything the image server offers."""
    out = []
    for ident, entry in (catalog.get('model_entries') or {}).items():
        kind = 'checkpoint' if entry.get('loader') == 'CheckpointLoaderSimple' else 'diffusion_model'
        out.append((kind, ident, entry.get('filename') or ident))
    for kind, key in (
        ('lora', 'loras'),
        ('text_encoder', 'text_encoders'),
        ('vae', 'vaes'),
        ('upscale_model', 'upscale_models'),
    ):
        out.extend((kind, name, name) for name in catalog.get(key) or [])
    return out


def _from_cm_info(doc):
    hashes = doc.get('Hashes') or {}
    return {
        'source': 'civitai',
        'model_id': doc.get('ModelId'),
        'version_id': doc.get('VersionId'),
        'model_name': doc.get('ModelName') or '',
        'version_name': doc.get('VersionName') or '',
        'base_model': doc.get('BaseModel') or '',
        'trained_words': [str(w) for w in doc.get('TrainedWords') or []],
        'author': doc.get('AuthorUsername') or '',
        'nsfw': bool(doc.get('Nsfw')),
        'sha256': str(hashes.get('SHA256') or '').lower(),
        'from': 'cm-info',
    }


def _from_civitai(version, model):
    license_ = {k: model.get(k) for k in LICENSE_KEYS if k in model}
    return {
        'source': 'civitai',
        'model_id': version.get('modelId'),
        'version_id': version.get('id'),
        'model_name': (version.get('model') or {}).get('name') or model.get('name') or '',
        'version_name': version.get('name') or '',
        'base_model': version.get('baseModel') or '',
        'trained_words': [str(w) for w in version.get('trainedWords') or []],
        'author': (model.get('creator') or {}).get('username') or '',
        'nsfw': bool((version.get('model') or {}).get('nsfw') or model.get('nsfw')),
        'license': license_,
        'from': 'lookup',
    }


def civitai_url(info):
    if not info or not info.get('model_id'):
        return None
    version = f'?modelVersionId={info["version_id"]}' if info.get('version_id') else ''
    return f'{CIVITAI}/models/{info["model_id"]}{version}'


class ModelLibrary:
    def __init__(self, paths, profiles, folders, key=None):
        """``folders()``: the image server's model folders by kind; ``key()``: the Civitai API key or None."""
        self.paths = paths
        self.profiles = profiles
        self.folders = folders
        self.key = key or (lambda: None)
        self.path = Path(paths.data) / 'image' / 'model-info.json'
        self.lock = threading.Lock()
        self._folders = (0.0, None)

    def _store(self):
        doc = read_json(self.path, {}) or {}
        return {'schema_version': 1, 'files': doc.get('files') or {}, 'info': doc.get('info') or {}}

    def server_folders(self):
        """The image server's model folders, asked at most every 30 seconds (every file is located through them)."""
        stamp, folders = self._folders
        if folders is None or time.monotonic() - stamp > 30:
            folders = self.folders() or {}
            self._folders = (time.monotonic(), folders)
        return folders

    def locate(self, kind, name):
        """The file behind a catalog name, in the image server's folders (or the shared model folder)."""
        key, shared_names, _ = KINDS[kind]
        folders = self.server_folders().get(key, [])
        for folder in folders:
            candidate = Path(folder) / PureWindowsPath(name)
            if candidate.is_file():
                return candidate
        base = self.profiles.models_dir()
        for folder in shared_names if base else ():
            candidate = base / folder / PureWindowsPath(name)
            if candidate.is_file():
                return candidate
        return None

    def _known_hash(self, store, path):
        stat = path.stat()
        entry = store['files'].get(str(path).lower())
        if entry and entry.get('size') == stat.st_size and entry.get('mtime') == stat.st_mtime_ns:
            return entry.get('sha256')
        return None

    def describe(self, kind, name, store=None):
        store = store or self._store()
        path = self.locate(kind, name)
        family_kind = KINDS[kind][2]
        family, by = (
            self.profiles.detect(family_kind, name.removeprefix('checkpoint::'))
            if family_kind
            else (None, None)
        )
        item = {
            'kind': kind,
            'name': name,
            'file': PureWindowsPath(name.removeprefix('checkpoint::')).name,
            'path': str(path) if path else None,
            'size': path.stat().st_size if path else None,
            'family': family,
            'family_by': by,
            'preview': None,
            'info': None,
            'source': 'unknown',
        }
        if path is None:
            return item
        if kind == 'lora' and PureWindowsPath(name).parts[0].lower() == LINK_NAME:
            item['source'] = 'trained'
        digest = self._known_hash(store, path)
        info = store['info'].get(digest) if digest else None
        if info is None:
            cm = path.with_name(path.stem + '.cm-info.json')
            doc = read_json(cm, None) if cm.is_file() else None
            if isinstance(doc, dict):
                info = _from_cm_info(doc)
        if info:
            item['info'] = {**info, 'url': civitai_url(info)}
            if item['source'] == 'unknown':
                item['source'] = info.get('source', 'civitai')
        for suffix in ('.preview.jpeg', '.preview.jpg', '.preview.png', '.preview.webp'):
            if path.with_name(path.stem + suffix).is_file():
                item['preview'] = suffix
                break
        item['hashed'] = bool(digest)
        return item

    def items(self, catalog):
        store = self._store()
        return [self.describe(kind, name, store) for kind, name, _ in _entries(catalog)]

    def locate_for_family(self, family_kind, name):
        """``locate`` by the family kinds of ModelProfiles (checkpoints, loras …)."""
        kind = next((k for k, v in KINDS.items() if v[2] == family_kind), None)
        return self.locate(kind, name) if kind else None

    def preview_file(self, kind, name):
        path = self.locate(kind, name)
        if path is None:
            return None
        for suffix in ('.preview.jpeg', '.preview.jpg', '.preview.png', '.preview.webp'):
            candidate = path.with_name(path.stem + suffix)
            if candidate.is_file():
                return candidate
        return None

    def sha256(self, kind, name):
        """The file's SHA256, computed once per size and change time."""
        path = self.locate(kind, name)
        if path is None:
            raise ValueError(
                Msg('server.models.file_missing', 'The file of {name} was not found.', name=name)
            )
        with self.lock:
            store = self._store()
            known = self._known_hash(store, path)
        if known:
            return path, known
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(block)
        value = digest.hexdigest()
        stat = path.stat()
        with self.lock:
            store = self._store()
            store['files'][str(path).lower()] = {
                'size': stat.st_size,
                'mtime': stat.st_mtime_ns,
                'sha256': value,
            }
            atomic_json(self.path, store)
        return path, value

    def _get(self, url):
        headers = {'User-Agent': 'AtelierX'}
        key = self.key()
        if key:
            headers['Authorization'] = f'Bearer {key}'
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise ValueError(
                Msg(
                    'server.models.civitai_error',
                    'Civitai answered {code}. Try again later.',
                    code=error.code,
                )
            ) from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ValueError(
                Msg('server.models.civitai_unreachable', 'Civitai could not be reached.')
            ) from error

    def lookup(self, kind, name):
        """Find the file on Civitai by its hash and remember what it says. Returns the item."""
        if kind not in KINDS:
            raise ValueError(
                Msg('server.models.the_model_type_and_name_are', 'The model type and name are required.')
            )
        _, digest = self.sha256(kind, name)
        version = self._get(f'{CIVITAI}/api/v1/model-versions/by-hash/{digest}')
        if version is None:
            info = {'source': 'unknown', 'from': 'lookup', 'sha256': digest, 'not_found': True}
        else:
            model = self._get(f'{CIVITAI}/api/v1/models/{version.get("modelId")}') or {}
            info = {**_from_civitai(version, model), 'sha256': digest}
        with self.lock:
            store = self._store()
            store['info'][digest] = info
            atomic_json(self.path, store)
        return self.describe(kind, name)

    def base_model(self, path):
        """The Civitai base model the app looked up for a file, for the family order (or None)."""
        store = self._store()
        digest = self._known_hash(store, path) if path and path.is_file() else None
        return (store['info'].get(digest) or {}).get('base_model') if digest else None
