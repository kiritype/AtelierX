"""Versioned public content packs, previewed and imported globally by explicit choices (#328)."""

import copy
import hashlib
import io
import json
import re
import secrets
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from urllib.parse import urlsplit

from PIL import Image

from .. import __version__
from ..core import revisions
from ..core.download_http import DownloadRedirect, origin
from ..core.i18n import Msg
from . import library, library_share, preset_share
from .resource_refs import HASH, bind, references
from .util import atomic_json, read_json
from .uuid_migration import FileCheckpoint, resolve

MAX_CATALOG = 1024**2
MAX_PACK = 64 * 1024**2
TTL = 1800


def bad():
    return ValueError(
        Msg('server.content.bad', 'This content pack is damaged or uses an unsupported format.')
    )


def https_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise bad()
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise bad()
        _ = url.port
    except ValueError as error:
        raise bad() from error
    return value


class ContentRedirect(DownloadRedirect):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_url(newurl)
        if origin(req.full_url) != origin(newurl):
            raise urllib.error.URLError('Content redirects must stay on their configured origin')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit):
    https_url(url)
    try:
        request = urllib.request.Request(
            url, headers={'User-Agent': 'AtelierX', 'Accept-Encoding': 'identity'}
        )
        with urllib.request.build_opener(ContentRedirect()).open(request, timeout=30) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise bad()
        return raw
    except (OSError, urllib.error.URLError) as error:
        raise ValueError(
            Msg('server.content.network', 'Could not read the official content. Try again.')
        ) from error


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise bad()
    return tuple(int(n) for n in value.split('.'))


def semantic(kind, doc):
    """Local model path reconnection is not an edit to the distributed preset's identity."""
    value = copy.deepcopy(doc)
    if kind == 'presets':
        value = library.preset_doc(value, '')
        value.pop('preview', None)
        for ref in references(value):
            if ref.get('sha256'):
                bind(value['settings'], ref['slot'], 'sha256:' + ref['sha256'])
        value.pop('resources', None)
    return value


def fingerprint(kind, doc):
    return revisions.of(semantic(kind, doc)) if doc is not None else None


class DefaultContent:
    def __init__(self, runtime):
        self.rt = runtime
        self.paths = runtime.paths
        self.pending = {}
        self.receipts = self.paths.data / 'image' / 'content-imports.json'

    def source(self):
        # Empty until the operator publishes the R2 objects and connects their public HTTPS catalog.
        default = read_json(self.paths.defaults / 'content-source.json', {}) or {}
        config = read_json(self.paths.config / 'image' / 'content-source.json', {}) or {}
        value = config.get('catalog_url', default.get('catalog_url', ''))
        return https_url(value) if value else ''

    def _receipts(self):
        if not self.receipts.exists():
            return {'schema_version': 1, 'packs': {}}
        doc = read_json(self.receipts)
        if (
            not isinstance(doc, dict)
            or doc.get('schema_version') != 1
            or not isinstance(doc.get('packs'), dict)
        ):
            raise bad()
        for pack in doc['packs'].values():
            if (
                not isinstance(pack, dict)
                or pack.get('kind') not in ('presets', 'expressions')
                or not isinstance(pack.get('items'), dict)
            ):
                raise bad()
            if not isinstance(pack.get('version'), str):
                raise bad()
            for entry in pack['items'].values():
                if not isinstance(entry, dict):
                    raise bad()
                try:
                    uuid.UUID(entry.get('target', ''))
                except (ValueError, TypeError, AttributeError):
                    raise bad() from None
                if not all(HASH.fullmatch(str(entry.get(k, ''))) for k in ('source_hash', 'installed_hash')):
                    raise bad()
        return doc

    def status(self):
        receipts = self._receipts()
        return {
            'configured': bool(self.source()),
            'installed': [
                {
                    'id': ident,
                    'kind': p['kind'],
                    'version': p['version'],
                    'items': [
                        v['target']
                        for key, v in p.get('items', {}).items()
                        if key.startswith(p['kind'] + ':')
                        and self._current(p['kind'], v['target']) is not None
                    ],
                }
                for ident, p in receipts['packs'].items()
            ],
        }

    def catalog(self):
        source = self.source()
        if not source:
            raise ValueError(
                Msg(
                    'server.content.unconfigured', 'Official content is not published yet. Check again later.'
                )
            )
        try:
            doc = json.loads(fetch(source, MAX_CATALOG))
            if doc.get('kind') != 'atelierx-default-content' or doc.get('schema_version') != 1:
                raise bad()
            packs = doc['packs']
            if not isinstance(packs, list) or len(packs) > 20:
                raise bad()
            seen = set()
            clean = []
            for entry in packs:
                if not isinstance(entry, dict) or not re.fullmatch(
                    r'[a-zA-Z0-9_-]{1,100}', entry.get('id', '')
                ):
                    raise bad()
                if entry['id'] in seen or entry.get('kind') not in ('presets', 'expressions'):
                    raise bad()
                seen.add(entry['id'])
                if origin(https_url(entry['url'])) != origin(source) or not HASH.fullmatch(entry['sha256']):
                    raise bad()
                if type(entry.get('size')) is not int or not 0 < entry['size'] <= MAX_PACK:
                    raise bad()
                minimum = version(entry['min_app_version'])
                if not isinstance(entry.get('version'), str) or not 0 < len(entry['version']) <= 80:
                    raise bad()
                if not all(
                    isinstance(entry.get(k), str) and len(entry[k]) <= 4000
                    for k in ('title', 'description', 'author', 'license')
                ):
                    raise bad()
                clean.append(
                    {
                        **{
                            k: entry[k]
                            for k in (
                                'id',
                                'kind',
                                'url',
                                'sha256',
                                'size',
                                'version',
                                'min_app_version',
                                'title',
                                'description',
                                'author',
                                'license',
                            )
                        },
                        'compatible': minimum <= version(__version__),
                    }
                )
            return {'packs': clean}
        except (KeyError, TypeError, AttributeError, UnicodeError, json.JSONDecodeError) as error:
            raise bad() from error

    def _read_pack(self, pack, raw):
        if len(raw) != pack['size'] or hashlib.sha256(raw).hexdigest() != pack['sha256'].lower():
            raise ValueError(
                Msg('server.content.hash', 'The content checksum did not match. Nothing was imported.')
            )
        previews = {}
        try:
            if pack['kind'] == 'presets':
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    manifest = json.loads(
                        preset_share._read(
                            archive,
                            preset_share.MANIFEST,
                            preset_share.MAX_MANIFEST,
                            [preset_share.MAX_UNPACKED],
                        )
                    )
                    if manifest.get('schema_version') not in (1, 2, 3):
                        raise bad()
                    entries = manifest.get('presets')
                    if not isinstance(entries, list) or len(entries) > preset_share.MAX_PRESETS:
                        raise bad()
                    budget = [preset_share.MAX_UNPACKED]
                    for entry in entries:
                        ident = entry.get('id')
                        if not isinstance(ident, str) or not library.ITEM_ID.fullmatch(ident):
                            raise bad()
                        source = json.loads(
                            preset_share._read(
                                archive, f'presets/{ident}.json', preset_share.MAX_PRESET_FILE, budget
                            )
                        )
                        if source.get('schema_version', 1) not in (1, 2, 3, 4):
                            raise bad()
                reader = preset_share.PresetImports(self.paths)
                look = reader.preview(raw, {})
                parsed = reader.pending[look['token']]
                if len(parsed['docs']) != len(manifest['presets']):
                    raise bad()
                documents = {'presets': {}, 'common': {}}
                for ident, (doc, preview, _) in parsed['docs'].items():
                    documents['presets'][ident] = doc
                    if preview:
                        with Image.open(io.BytesIO(preview)) as image:
                            if image.format != 'WEBP' or image.width * image.height > 16_000_000:
                                raise bad()
                            image.verify()
                        previews[ident] = preview
                for ident, item in parsed['common'].items():
                    cleaned = library_share._clean(self.paths, 'common', ident, item)
                    if cleaned is None:
                        raise bad()
                    documents['common'][ident] = cleaned
            else:
                doc = json.loads(raw)
                if doc.get('schema_version') != 1:
                    raise bad()
                source = library_share._read('expressions', doc)
                compositions = (doc.get('dependencies') or {}).get('compositions') or {}
                if not isinstance(compositions, dict) or len(compositions) > library_share.MAX_ITEMS:
                    raise bad()
                documents = {'expressions': {}, 'compositions': {}}
                for kind, items in (('expressions', source), ('compositions', compositions)):
                    for ident, item in items.items():
                        cleaned = library_share._clean(self.paths, kind, ident, item)
                        if cleaned is None:
                            raise bad()
                        documents[kind][ident] = cleaned
            for kind, docs in documents.items():
                if any(not library.ITEM_ID.fullmatch(ident) for ident in docs):
                    raise bad()
                if kind not in ('presets', 'expressions'):
                    continue
                for doc in docs.values():
                    for dep_kind, ident in self._dependencies(kind, doc):
                        if ident not in documents.get(dep_kind, {}):
                            raise bad()
            return documents, previews
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OSError,
            zipfile.BadZipFile,
            Image.DecompressionBombError,
        ) as error:
            if isinstance(error, ValueError) and error.args and isinstance(error.args[0], Msg):
                raise
            raise bad() from error

    @staticmethod
    def _dependencies(kind, doc):
        if kind == 'presets':
            return [('common', i) for i in doc.get('common') or []]
        if kind == 'expressions' and doc.get('composition'):
            return [('compositions', doc['composition'])]
        return []

    def _current(self, kind, ident):
        if kind == 'presets':
            path = self.paths.data / 'image' / 'presets' / f'{ident}.json'
            doc = read_json(path) if path.is_file() else None
            return library.preset_doc(doc, ident) if isinstance(doc, dict) else None
        return library_share._stored(self.paths, None, kind, 'global').get(ident)

    @library.locked
    def _preview(self, pack, documents, previews):
        receipts = self._receipts()
        saved = (receipts['packs'].get(pack['id']) or {}).get('items') or {}
        rows = {}
        for kind, docs in documents.items():
            for ident, doc in docs.items():
                key = f'{kind}:{ident}'
                record = saved.get(key) or {}
                target = record.get('target') or resolve(self.paths, kind, ident)
                if not self._current(kind, target):
                    try:
                        target = str(uuid.UUID(target))
                    except ValueError:
                        target = str(uuid.uuid5(uuid.NAMESPACE_URL, f'atelierx-content:{pack["id"]}:{key}'))
                current = self._current(kind, target)
                source_hash = fingerprint(kind, doc)
                current_hash = fingerprint(kind, current)
                if current is None:
                    state = 'new'
                elif record and current_hash != record.get('installed_hash'):
                    state = 'modified'
                elif record and source_hash == record.get('source_hash'):
                    state = 'same'
                elif record:
                    state = 'update'
                elif current_hash == source_hash:
                    state = 'same'
                else:
                    state = 'modified'
                rows[key] = {
                    'key': key,
                    'id': ident,
                    'kind': kind,
                    'target': target,
                    'name': doc.get('name') or ident,
                    'group': doc.get('group') or '',
                    'service': doc.get('service'),
                    'family': doc.get('family'),
                    'state': state,
                    'before': current,
                    'after': doc,
                    'source_hash': source_hash,
                    'current_hash': revisions.of(current),
                    'dependencies': [f'{k}:{i}' for k, i in self._dependencies(kind, doc)],
                }
        # Identical parents may still have updated or edited dependencies to review.
        for row in rows.values():
            if row['state'] == 'same' and any(rows[k]['state'] != 'same' for k in row['dependencies']):
                row['state'] = 'update'
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if now - v['at'] < TTL}
        token = secrets.token_hex(16)
        self.pending[token] = {
            'at': now,
            'pack': pack,
            'rows': rows,
            'previews': previews,
            'receipt_hash': revisions.of(receipts),
        }
        return {
            'token': token,
            'pack': pack,
            'items': [
                {
                    **row,
                    'preview_url': f'/api/image/content/preview/{token}/{row["id"]}.webp'
                    if row['kind'] == 'presets' and row['id'] in previews
                    else None,
                }
                for row in rows.values()
            ],
        }

    def preview(self, pack_id):
        pack = next((p for p in self.catalog()['packs'] if p['id'] == pack_id), None)
        if not pack:
            raise bad()
        if not pack['compatible']:
            raise ValueError(
                Msg(
                    'server.content.version',
                    'Update AtelierX to {version} before importing this pack.',
                    version=pack['min_app_version'],
                )
            )
        documents, previews = self._read_pack(pack, fetch(pack['url'], pack['size']))
        return self._preview(pack, documents, previews)

    def _pending(self, token):
        pending = self.pending.get(token) if isinstance(token, str) else None
        if not pending or time.monotonic() - pending['at'] > TTL:
            raise ValueError(Msg('server.content.expired', 'Read the content pack again before importing.'))
        return pending

    def preview_image(self, token, ident):
        return self._pending(token)['previews'].get(ident)

    @library.locked
    def apply(self, token, choices):
        pending = self._pending(token)
        rows, pack = pending['rows'], pending['pack']
        receipts = self._receipts()
        revisions.check(pending['receipt_hash'], revisions.of(receipts))
        if not isinstance(choices, dict) or any(
            k not in rows or v not in ('add', 'replace', 'copy', 'skip') for k, v in choices.items()
        ):
            raise bad()
        primary = [
            k for k, row in rows.items() if row['kind'] == pack['kind'] and choices.get(k, 'skip') != 'skip'
        ]
        if not primary:
            raise ValueError(Msg('server.content.select', 'Select the content to import.'))
        needed = set(primary)
        for key in primary:
            needed.update(rows[key]['dependencies'])
        targets = {k: row['target'] for k, row in rows.items()}
        plan = {}
        for key in needed:
            row = rows[key]
            choice = choices.get(key, 'add' if row['state'] == 'new' else 'skip')
            current = self._current(row['kind'], row['target'])
            if choice == 'skip':
                if current is None:
                    raise ValueError(
                        Msg(
                            'server.content.dependency', 'Include the required item: {name}', name=row['name']
                        )
                    )
                continue
            revisions.check(row['current_hash'], revisions.of(current))
            if choice == 'add' and current is not None:
                if row['state'] != 'same':
                    raise bad()
                continue
            if choice == 'copy':
                targets[key] = str(uuid.uuid4())
            plan[key] = copy.deepcopy(row['after'])
        for key, doc in plan.items():
            kind = rows[key]['kind']
            if kind == 'presets':
                doc['common'] = [targets[f'common:{i}'] for i in doc.get('common') or []]
            elif kind == 'expressions' and doc.get('composition'):
                doc['composition'] = targets[f'compositions:{doc["composition"]}']
        paths = [self.receipts]
        for key in plan:
            row, ident = rows[key], targets[key]
            if row['kind'] == 'presets':
                paths += [
                    self.paths.data / 'image' / 'presets' / f'{ident}.json',
                    library.preview_file(self.paths, ident),
                ]
            else:
                paths.append(library._file(self.paths, None, row['kind'], 'global'))
        checkpoint = FileCheckpoint(self.paths, paths)
        try:
            for key, doc in plan.items():
                row, ident = rows[key], targets[key]
                if row['kind'] == 'presets':
                    library.save_preset(self.paths, ident, doc)
                    preview = pending['previews'].get(row['id'])
                    image = library.preview_file(self.paths, ident)
                    if preview:
                        image.write_bytes(preview)
                    else:
                        image.unlink(missing_ok=True)
                else:
                    path = library._file(self.paths, None, row['kind'], 'global')
                    stored = read_json(path, {'items': {}})
                    if not isinstance(stored, dict) or not isinstance(stored.get('items'), dict):
                        raise bad()
                    stored['items'][ident] = doc
                    stored['schema_version'] = 3 if row['kind'] == 'compositions' else 2
                    atomic_json(path, stored)
            record = receipts['packs'].setdefault(pack['id'], {'items': {}})
            record.update(kind=pack['kind'], version=pack['version'])
            for key in needed:
                row = rows[key]
                if key not in plan and row['state'] != 'same':
                    continue
                record['items'][key] = {
                    'target': targets[key],
                    'source_hash': row['source_hash'],
                    'installed_hash': fingerprint(row['kind'], self._current(row['kind'], targets[key])),
                }
            atomic_json(self.receipts, receipts)
        except Exception:
            checkpoint.rollback()
            raise
        finally:
            checkpoint.close()
        self.pending.pop(token, None)
        return {
            'written': [targets[k] for k in primary if k in plan],
            'version': pack['version'],
            'kind': pack['kind'],
        }
