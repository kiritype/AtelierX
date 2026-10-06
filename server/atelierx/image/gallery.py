"""Gallery (21-gallery): every image under the output root, read from the files themselves.

The output folder is the authority; records can change or vanish without breaking the list. An image made
by the queue sits at ``<work>/<character>/images/<outfit>/<expression>/NNN.png`` with a JSON record next to
it. Everything else (single generations under ``_lab/``, tool results, copied-in files) is listed by folder.
"""

import hashlib
import io
import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from PIL import Image

from ..core.i18n import Msg
from .util import replace_file, state_file

IMAGE_SUFFIXES = ('.png', '.webp', '.jpg', '.jpeg')
MAX_DEPTH = 8
SCAN_SECONDS = 3.0
COMBO_KEYS = ('work_id', 'character_id', 'outfit_id', 'expression_id')


def is_asset(parts):
    return len(parts) == 6 and parts[2] == 'images' and not parts[0].startswith('_')


def combo_of(item):
    return tuple(str(item.get(k) or '') for k in COMBO_KEYS)


def invalid_path():
    return ValueError(Msg('server.gallery.invalid_path', 'Invalid image path.'))


class Gallery:
    def __init__(self, paths):
        self.root = Path(paths.output)
        self.cache = state_file(paths, 'thumbnails')
        self.lock = threading.RLock()
        self.items = []
        self._signature = ()
        self._meta_cache = {}
        self._last_scan = 0.0
        self.revision = 0

    # --- paths ------------------------------------------------------------------------------------------------------
    def safe_path(self, relative, suffixes=IMAGE_SUFFIXES):
        """An image under the output root, never outside it and never through a link."""
        if not isinstance(relative, str) or not relative or '\\' in relative or '\x00' in relative:
            raise invalid_path()
        parts = PurePosixPath(relative).parts
        if not 1 <= len(parts) <= MAX_DEPTH + 1 or any(p in ('', '.', '..') or ':' in p for p in parts):
            raise invalid_path()
        path = self.root.joinpath(*parts)
        if path.suffix.lower() not in suffixes:
            raise invalid_path()
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise invalid_path()
        current = self.root
        for part in parts:
            current /= part
            if current.is_symlink():
                raise invalid_path()
        return path

    @staticmethod
    def url(relative):
        return '/api/image/files/' + quote(relative, safe='/')

    # --- records ----------------------------------------------------------------------------------------------------
    def _read_meta(self, path):
        key = path.as_posix()
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        cached = self._meta_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
        value = None
        if signature is not None and signature[1] < 16 * 1024 * 1024:
            try:
                parsed = json.loads(path.read_text(encoding='utf-8'))
                value = parsed if isinstance(parsed, dict) else None
            except (OSError, UnicodeError, ValueError):
                value = None
        self._meta_cache[key] = (signature, value)
        return value

    def metadata(self, relative):
        image = self.safe_path(relative)
        if not image.is_file():
            raise ValueError(Msg('server.gallery.not_found', 'The image does not exist.'))
        with self.lock:
            meta = self._read_meta(image.with_suffix('.json'))
        if meta is None:
            raise ValueError(Msg('server.gallery.no_record', 'This image has no record.'))
        return meta

    # --- scanning ---------------------------------------------------------------------------------------------------
    def _discover(self, deadline):
        found = []
        stack = [(self.root, 0)]
        while stack:
            directory, depth = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if time.monotonic() > deadline:
                        return None
                    if entry.is_symlink() or entry.name.startswith('.'):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth < MAX_DEPTH:
                            stack.append((Path(entry.path), depth + 1))
                    elif entry.name.lower().endswith(IMAGE_SUFFIXES) and entry.is_file(follow_symlinks=False):
                        found.append((Path(entry.path), entry.stat(follow_symlinks=False)))
        return found

    def scan(self, force=False):
        """Refresh the index when files changed; at most every 0.75 s unless ``force``."""
        with self.lock:
            moment = time.monotonic()
            if not force and moment - self._last_scan < 0.75:
                return
            self._last_scan = moment
            if not self.root.is_dir():
                if self.items:
                    self.items, self._signature = [], ()
                    self.revision += 1
                return
            try:
                found = self._discover(moment + SCAN_SECONDS)
            except OSError:
                found = None
            if found is None:
                # Keep the last complete index and try again a little later.
                self._last_scan = time.monotonic() + 4
                return
            signature = []
            for path, stat in found:
                sidecar = path.with_suffix('.json')
                try:
                    side = sidecar.stat()
                    side_sig = (side.st_mtime_ns, side.st_size)
                except OSError:
                    side_sig = None
                signature.append((path.as_posix(), stat.st_mtime_ns, stat.st_size, side_sig))
            signature = tuple(sorted(signature))
            if signature == self._signature:
                return
            items, seen = [], set()
            for path, stat in found:
                sidecar = path.with_suffix('.json')
                seen.add(sidecar.as_posix())
                items.append(self._item(path, stat, self._read_meta(sidecar)))
            self._meta_cache = {k: v for k, v in self._meta_cache.items() if k in seen}
            self.items, self._signature = items, signature
            self.revision += 1

    def _item(self, path, stat, meta):
        relative = path.relative_to(self.root).as_posix()
        parts = PurePosixPath(relative).parts
        asset = is_asset(parts)
        meta = meta or {}
        created = meta.get('created_at')
        if not isinstance(created, str):
            created = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
        settings = meta.get('settings') if isinstance(meta.get('settings'), dict) else {}
        if asset:
            kind = 'image'
        elif parts[0] == '_lab':
            kind = 'lab'
        elif parts[0] == '_tools':
            kind = 'tool'
        else:
            kind = 'other'
        return {
            'path': relative,
            'filename': path.name,
            'folder': '/'.join(parts[:-1]),
            'kind': kind,
            'image_url': self.url(relative),
            'thumbnail_url': '/api/image/gallery/thumbnail?path=' + quote(relative, safe=''),
            'has_record': bool(meta),
            'work_id': parts[0] if asset else str(meta.get('work_id') or ''),
            'character_id': parts[1] if asset else str(meta.get('character_id') or ''),
            'outfit_id': parts[3] if asset else str(meta.get('outfit_id') or ''),
            'expression_id': str(meta.get('expression_id') or (parts[4] if asset else '')),
            'outfit_name': str(meta.get('outfit_name') or ''),
            'expression_name': str(meta.get('expression_name') or ''),
            'rating': str(meta.get('rating') or ''),
            'model_family': str(settings.get('family') or ('unknown' if not meta else 'anima')),
            'service': str(meta.get('service') or ('comfyui' if meta else '')),
            'seed': meta.get('seed'),
            'postprocessed': bool((meta.get('postprocessing') or {}).get('applied')),
            'created_at': created,
            'size': list(meta.get('image_size') or []),
            '_mtime_ns': stat.st_mtime_ns,
            '_bytes': stat.st_size,
        }

    @staticmethod
    def public(item):
        return {k: v for k, v in item.items() if not k.startswith('_')}

    def find(self, relative):
        self.safe_path(relative)
        self.scan()
        with self.lock:
            for item in self.items:
                if item['path'] == relative:
                    return dict(item)
        raise ValueError(Msg('server.gallery.not_found', 'The image does not exist.'))

    def snapshot_items(self):
        self.scan()
        with self.lock:
            return [dict(i) for i in self.items]

    # --- listing ----------------------------------------------------------------------------------------------------
    def tree(self):
        """Counts by work → character → outfit, expressions seen, and other folders."""
        works, expressions, folders = {}, {}, {}
        for item in self.snapshot_items():
            if item['kind'] != 'image':
                segments = item['folder'].split('/') if item['folder'] else []
                for depth in range(1, len(segments) + 1):
                    key = '/'.join(segments[:depth])
                    folders[key] = folders.get(key, 0) + 1
                continue
            work = works.setdefault(item['work_id'], {'id': item['work_id'], 'count': 0, 'characters': {}})
            work['count'] += 1
            character = work['characters'].setdefault(
                item['character_id'], {'id': item['character_id'], 'count': 0, 'outfits': {}}
            )
            character['count'] += 1
            outfit = character['outfits'].setdefault(
                item['outfit_id'], {'id': item['outfit_id'], 'name': item['outfit_name'], 'count': 0}
            )
            outfit['count'] += 1
            outfit['name'] = outfit['name'] or item['outfit_name']
            expression = expressions.setdefault(
                item['expression_id'],
                {
                    'id': item['expression_id'],
                    'name': item['expression_name'],
                    'rating': item['rating'],
                    'count': 0,
                },
            )
            expression['count'] += 1
            expression['name'] = expression['name'] or item['expression_name']
        out = []
        for work in sorted(works.values(), key=lambda w: w['id']):
            characters = []
            for character in sorted(work['characters'].values(), key=lambda c: c['id']):
                character['outfits'] = sorted(character['outfits'].values(), key=lambda o: o['id'])
                characters.append(character)
            out.append({**work, 'characters': characters})
        return {
            'works': out,
            'expressions': sorted(expressions.values(), key=lambda e: e['id']),
            'folders': [{'path': k, 'count': v} for k, v in sorted(folders.items())],
            'revision': self.revision,
        }

    def thumbnail(self, relative):
        image = self.safe_path(relative)
        if not image.is_file():
            raise ValueError(Msg('server.gallery.not_found', 'The image does not exist.'))
        stat = image.stat()
        digest = hashlib.sha256(f'{relative}\0{stat.st_mtime_ns}\0{stat.st_size}'.encode()).hexdigest()
        target = self.cache / (digest + '.webp')
        if target.is_file():
            return target.read_bytes()
        with Image.open(image) as source:
            source.thumbnail((320, 320))
            picture = source.convert('RGBA')
            # Transparent images get a white backdrop instead of black.
            backdrop = Image.new('RGBA', picture.size, 'white')
            output = io.BytesIO()
            Image.alpha_composite(backdrop, picture).convert('RGB').save(output, format='WEBP', quality=78)
        data = output.getvalue()
        self.cache.mkdir(parents=True, exist_ok=True)
        temp = self.cache / (digest + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temp.write_bytes(data)
            replace_file(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return data
