"""Check portable preset dependencies and enqueue only explicitly selected, verified provider files."""

import copy
import ipaddress
import secrets
import threading
import time
from urllib.parse import urlsplit

from ..core import revisions
from ..core.i18n import Msg, message_of, wire
from . import library
from .model_info import KINDS, _entries
from .resource_refs import HASH, bind, references, safe_name


def local_server(url):
    host = urlsplit(url).hostname
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host or '').is_loopback
    except ValueError:
        return False


def matches(kind, ref):
    return kind == ref.get('model_type', 'diffusion_model') if ref['kind'] == 'model' else kind == ref['kind']


class PresetModels:
    def __init__(self, runtime):
        self.rt = runtime
        self.pending = {}
        self.lock = threading.RLock()

    def _docs(self, ids):
        if not isinstance(ids, list) or len(ids) > 500 or not all(isinstance(i, str) for i in ids):
            raise ValueError(Msg('server.presets.models.choose', 'Choose the presets to check.'))
        docs = {p['id']: p for p in library.presets(self.rt.paths)}
        return [docs[i] for i in dict.fromkeys(ids) if i in docs]

    def reconcile(self):
        """Called after a completed download, including when its dialog has already closed."""
        with self.lock:
            catalog, entries = self._catalog()
            if not catalog.get('connected') or not local_server(self.rt.comfy.url):
                return
            for doc in library.presets(self.rt.paths):
                for ref in references(doc):
                    existing = self._existing(ref, entries, hash_files=False)
                    if existing:
                        self._bind([{'id': doc['id'], 'ref': ref}], existing, ref)

    def _catalog(self):
        catalog = self.rt.comfy.catalog()
        entries = [(k, n, f) for k, n, f in _entries(catalog) if safe_name(f)]
        return catalog, entries

    def validate(self, preset, settings, catalog):
        """Generation never substitutes a same-named file for a pinned dependency."""
        if not preset:
            return
        requested = references({**preset, 'settings': settings})
        entries = [(k, n, f) for k, n, f in _entries(catalog) if safe_name(f)]
        for ref in requested:
            if not ref.get('sha256'):
                continue
            exact = [(k, n, f) for k, n, f in entries if f == ref['name']]
            if not local_server(self.rt.comfy.url) or not self._existing(ref, exact, hash_files=False):
                raise ValueError(
                    Msg(
                        'server.presets.models.not_ready',
                        'Check the required preset models before generating: {name}',
                        name=ref['name'],
                    )
                )

    def _existing(self, ref, entries, *, hash_files):
        model_library = self.rt.model_library
        store = model_library._store()
        for kind, name, filename in entries:
            if not matches(kind, ref):
                continue
            path = model_library.locate(kind, name)
            if not path or not path.is_file():
                continue
            digest = model_library._known_hash(store, path)
            if ref.get('sha256'):
                if (
                    not digest
                    and hash_files
                    and (
                        ref.get('size')
                        and abs(path.stat().st_size - ref['size']) <= 1024
                        or filename == ref['name']
                        or (model_library.describe(kind, name, store).get('info') or {}).get('sha256')
                        == ref['sha256']
                    )
                ):
                    _, digest = model_library.sha256(kind, name)
                if digest == ref['sha256']:
                    return kind, name, digest
            elif filename == ref['name']:
                # A name is only a suggestion until the person explicitly connects it.
                return None
        return None

    def _provider(self, ref, family):
        downloads = self.rt.model_downloads
        model_id, version_id = ref.get('model_id'), ref.get('version_id')
        if not version_id and ref.get('sha256'):
            version = downloads._json(f'https://civitai.com/api/v1/model-versions/by-hash/{ref["sha256"]}')
            model_id, version_id = version.get('modelId'), version.get('id')
        if not model_id or not version_id:
            return None
        found = downloads.read(f'https://civitai.com/models/{model_id}?modelVersionId={version_id}')
        version = next((v for v in found['versions'] if v['id'] == version_id), None)
        if not version or (version.get('family') and version['family'] != family):
            return None
        candidates = [
            f
            for f in version['files']
            if HASH.fullmatch(str(f.get('sha256', '')))
            and (not ref.get('file_id') or f['id'] == ref['file_id'])
            and (not ref.get('sha256') or f['sha256'].lower() == ref['sha256'])
            and any(matches(k, ref) and spec[0] == f['kind'] for k, spec in KINDS.items())
        ]
        # Without either a hash or a file id, version metadata cannot identify the intended file.
        if len(candidates) != 1 or not (ref.get('file_id') or ref.get('sha256')):
            return None
        return {'model': found['model'], 'version': version, 'file': candidates[0]}

    @library.locked
    def _bind(self, uses, local, ref):
        _kind, name, digest = local
        current = {p['id']: p for p in library.presets(self.rt.paths)}
        for use in uses:
            doc = current.get(use['id'])
            if not doc:
                continue
            previous = next((r for r in references(doc) if r['slot'] == use['ref']['slot']), None)
            if previous != use['ref']:
                continue  # An editor changed this field during the download. Never replace that edit.
            updated = copy.deepcopy(doc)
            bind(updated['settings'], previous['slot'], name)
            saved = {
                **previous,
                **ref,
                'slot': previous['slot'],
                'name': name.removeprefix('checkpoint::'),
                'sha256': digest,
            }
            updated['resources'] = [r for r in references(doc) if r['slot'] != previous['slot']] + [saved]
            if library.preset_doc(updated, doc['id']) != library.preset_doc(doc, doc['id']):
                library.save_preset(self.rt.paths, doc['id'], updated)
            use['ref'] = next(r for r in references(updated) if r['slot'] == previous['slot'])

    def check(self, ids):
        with self.lock:
            docs = self._docs(ids)
            catalog, entries = self._catalog()
            local = local_server(self.rt.comfy.url)
            rows = {}
            for doc in docs:
                for ref in references(doc):
                    key = revisions.of(
                        [
                            ref.get('model_type', ref['kind']),
                            ref.get('sha256') or [ref.get('version_id'), ref.get('file_id'), ref['name']],
                            doc['family'],
                        ]
                    )
                    if key not in rows:
                        rows[key] = {'id': key, 'ref': ref, 'family': doc['family'], 'uses': []}
                    rows[key]['uses'].append({'id': doc['id'], 'name': doc['name'], 'ref': ref})
            for row in rows.values():
                ref = row['ref']
                row['status'] = 'unknown'
                if not catalog.get('connected') or not local:
                    continue
                existing = self._existing(ref, entries, hash_files=True)
                if existing:
                    row['status'] = 'ready'
                    self._bind(row['uses'], existing, ref)
                    continue
                row['status'] = 'missing' if ref.get('sha256') else 'unverified'
                try:
                    plan = self._provider(ref, row['family'])
                    if plan:
                        row['plan'] = plan
                        row['ref'] = {
                            **ref,
                            'sha256': plan['file']['sha256'].lower(),
                            'size': plan['file']['size'],
                            'file_id': plan['file']['id'],
                            'model_id': plan['model']['id'],
                            'version_id': plan['version']['id'],
                        }
                        # Validate the destination before offering a download.
                        row['destination'] = str(
                            self.rt.model_downloads.folder_for(
                                plan['file']['kind'], plan['version'].get('family')
                            )
                        )
                    else:
                        row['error'] = wire(
                            Msg(
                                'server.presets.models.manual',
                                'Open the source page or connect a local file.',
                            )
                        )
                except (ValueError, OSError) as error:
                    row['error'] = wire(message_of(error))
                    row.pop('plan', None)
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if now - v['at'] < 1800}
            token = secrets.token_hex(16)
            self.pending[token] = {'at': now, 'rows': rows, 'ids': ids}
            return self.status(token)

    def _pending(self, token):
        pending = self.pending.get(token)
        if not pending or time.monotonic() - pending['at'] > 1800:
            raise ValueError(Msg('server.presets.models.expired', 'Check the required models again.'))
        return pending

    def status(self, token):
        with self.lock:
            pending = self._pending(token)
            catalog, entries = self._catalog()
            available = bool(catalog.get('connected')) and local_server(self.rt.comfy.url)
            jobs = self.rt.model_downloads.public()['jobs']
            result = []
            for row in pending['rows'].values():
                ref = row['ref']
                if available:
                    existing = self._existing(ref, entries, hash_files=False)
                    if existing:
                        self._bind(row['uses'], existing, ref)
                        row['status'] = 'ready'
                    else:
                        row['status'] = 'missing' if ref.get('sha256') else 'unverified'
                job = next(
                    (
                        j
                        for j in jobs
                        if ref.get('sha256')
                        and j.get('sha256') == ref['sha256']
                        and any(matches(k, ref) and v[0] == j['kind'] for k, v in KINDS.items())
                    ),
                    None,
                )
                status = row['status'] if available else 'unknown'
                if status != 'ready' and job and job['status'] != 'done':
                    status = job['status']
                elif status != 'ready' and job and job['status'] == 'done' and available:
                    status = 'unrecognized'
                plan = row.get('plan')
                result.append(
                    {
                        'id': row['id'],
                        'kind': ref['kind'],
                        'name': ref['name'],
                        'sha256': ref.get('sha256'),
                        'size': ref.get('size'),
                        'status': status,
                        'presets': [{'id': u['id'], 'name': u['name']} for u in row['uses']],
                        'downloadable': available
                        and bool(plan)
                        and status in ('missing', 'unverified', 'cancelled'),
                        'civitai': f'https://civitai.com/models/{ref["model_id"]}?modelVersionId={ref.get("version_id", "")}'
                        if ref.get('model_id')
                        else None,
                        'version': plan['version']['name'] if plan else None,
                        'license': plan['model']['license'] if plan else None,
                        'destination': row.get('destination'),
                        'job': job,
                        'error': row.get('error'),
                        'candidates': [{'kind': k, 'name': n} for k, n, _ in entries if matches(k, ref)]
                        if available and status != 'ready'
                        else [],
                    }
                )
            return {
                'token': token,
                'connected': bool(catalog.get('connected')),
                'local': local_server(self.rt.comfy.url),
                'has_key': bool(self.rt.civitai_key()),
                'items': result,
            }

    def download(self, token, selected):
        with self.lock:
            pending = self._pending(token)
            if (
                not isinstance(selected, list)
                or not selected
                or any(i not in pending['rows'] for i in selected)
            ):
                raise ValueError(
                    Msg('server.presets.models.select', 'Select the missing models to download.')
                )
            if not local_server(self.rt.comfy.url) or not self.rt.comfy.catalog().get('connected'):
                raise ValueError(Msg('server.presets.models.local', 'Connect a local ComfyUI server first.'))
            current = {p['id']: p for p in self._docs(pending['ids'])}
            plans = []
            for ident in dict.fromkeys(selected):
                row = pending['rows'][ident]
                for use in row['uses']:
                    actual = next(
                        (
                            r
                            for r in references(current.get(use['id'], {}))
                            if r['slot'] == use['ref']['slot']
                        ),
                        None,
                    )
                    revisions.check(revisions.of(use['ref']), revisions.of(actual))
                plan = row.get('plan')
                if not plan:
                    raise ValueError(
                        Msg('server.presets.models.manual', 'Open the source page or connect a local file.')
                    )
                # Persist provider identity before queueing so a restart can reconnect the finished file.
                for use in row['uses']:
                    self._remember(use, row['ref'])
                plans.append(plan)
            errors = []
            for plan in plans:
                digest = plan['file']['sha256'].lower()
                if any(
                    j.get('sha256') == digest
                    and j['kind'] == plan['file']['kind']
                    and j['status'] in ('queued', 'running', 'paused', 'failed')
                    for j in self.rt.model_downloads.public()['jobs']
                ):
                    continue
                try:
                    self.rt.model_downloads.add(plan)
                except (ValueError, OSError) as error:
                    errors.append(wire(message_of(error)))
            return {**self.status(token), 'errors': errors}

    @library.locked
    def _remember(self, use, ref):
        doc = next((p for p in library.presets(self.rt.paths) if p['id'] == use['id']), None)
        if not doc:
            return
        resources = references(doc)
        current = next((r for r in resources if r['slot'] == use['ref']['slot']), None)
        revisions.check(revisions.of(use['ref']), revisions.of(current))
        saved = {**ref, 'slot': current['slot'], 'name': current['name']}
        doc['resources'] = [r for r in resources if r['slot'] != current['slot']] + [saved]
        library.save_preset(self.rt.paths, doc['id'], doc)
        use['ref'] = next(r for r in references(doc) if r['slot'] == current['slot'])

    def link(self, token, ident, kind, name):
        with self.lock:
            row = self._pending(token)['rows'].get(ident)
            catalog, entries = self._catalog()
            if not row or not catalog.get('connected') or not local_server(self.rt.comfy.url):
                raise ValueError(Msg('server.presets.models.local', 'Connect a local ComfyUI server first.'))
            if not any(k == kind and n == name and matches(k, row['ref']) for k, n, _ in entries):
                raise ValueError(
                    Msg('server.presets.models.manual', 'Open the source page or connect a local file.')
                )
            _, digest = self.rt.model_library.sha256(kind, name)
            if row['ref'].get('sha256') and row['ref']['sha256'] != digest:
                raise ValueError(
                    Msg('server.presets.models.hash', 'This file does not match the required SHA256.')
                )
            self._bind(row['uses'], (kind, name, digest), row['ref'])
            row['ref'] = {**row['ref'], 'sha256': digest}
            row['status'] = 'ready'
            return self.status(token)
