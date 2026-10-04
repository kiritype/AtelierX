"""Review of generated images (21-gallery: 검수). A person's verdict and the VLM's verdict, kept apart.

Records are keyed by path and content hash, so a replaced file starts unreviewed. Passing an image made by
the queue adopts it for its combination (work, character, outfit, expression); the latest pass wins. The
adopted images are what the ZIP export collects. The results are about the images, so they live next to them in
``<output>/reviews.json``; every write keeps the previous copy as ``reviews.json.bak``.
"""

import copy
import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from PIL import Image

from ..core.i18n import Msg
from .deployment_export import plan_paths
from .gallery import combo_of
from .util import atomic_json, now, read_json

VERDICTS = ('pass', 'fail', 'unreviewed')
AUTO = ('pending', 'pass', 'fail', 'uncertain', 'error')
HISTORY_KEPT = 20000
SORTS = ('newest', 'oldest', 'code')


def _identity(path, sha):
    return path + '\0' + sha


def _key(combo):
    return json.dumps(list(combo), ensure_ascii=False, separators=(',', ':'))


def _flag(params, key):
    return str(params.get(key) or '').lower() in ('1', 'true', 'yes')


def _without_metadata(path):
    with Image.open(path) as image:
        image.load()
        clean = image.copy()
        clean.info = {k: v for k, v in image.info.items() if k == 'transparency'}
        output = io.BytesIO()
        clean.save(output, format=image.format or 'PNG')
    return output.getvalue()


def _number(value, default, maximum):
    try:
        return min(max(int(value), 1), maximum)
    except (TypeError, ValueError):
        return default


class ReviewStore:
    def __init__(self, paths, gallery):
        self.gallery = gallery
        self.path = Path(paths.output) / 'reviews.json'
        self.lock = threading.RLock()
        self._hashes = {}
        self.state = read_json(self.path) or {}
        self.state.setdefault('schema_version', 1)
        for key in ('records', 'adopted'):
            self.state.setdefault(key, {})
        self.state.setdefault('history', [])
        self.listeners = []  # called after a person's verdict changes (the review rounds)

    def _save(self, state):
        state['history'] = state['history'][-HISTORY_KEPT:]
        if self.path.is_file():
            shutil.copyfile(self.path, self.path.with_name('reviews.json.bak'))
        atomic_json(self.path, state)
        self.state = state

    def sha256(self, relative, fresh=False):
        path = self.gallery.safe_path(relative)
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self._hashes.get(relative)
        if not fresh and cached and cached[0] == signature:
            return cached[1]
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        value = digest.hexdigest()
        self._hashes[relative] = (signature, value)
        return value

    def annotate(self, item):
        out = self.gallery.public(item)
        try:
            sha = self.sha256(item['path'])
        except (OSError, ValueError):
            sha = ''
        with self.lock:
            record = self.state['records'].get(_identity(item['path'], sha), {})
            adopted = self.state['adopted'].get(_key(combo_of(item)))
        out.update(
            sha256=sha,
            human_status=record.get('human', 'unreviewed'),
            note=record.get('note', ''),
            auto_status=record.get('auto', 'pending'),
            auto_reason=record.get('auto_reason', ''),
            adopted=bool(
                sha and item['kind'] == 'image' and adopted == {'path': item['path'], 'sha256': sha}
            ),
        )
        return out

    # --- listing ----------------------------------------------------------------------------------------------------
    def list(self, params):
        """One page of the gallery with filters, newest first by default."""
        items = self.gallery.snapshot_items()
        page = _number(params.get('page'), 1, 1_000_000)
        size = _number(params.get('page_size'), 60, 200)
        snapshot = params.get('snapshot')
        try:
            cutoff = int(snapshot) if snapshot else time.time_ns()
        except ValueError as error:
            raise ValueError(Msg('server.gallery.invalid_query', 'Invalid gallery query.')) from error
        for key, field in (
            ('work', 'work_id'),
            ('character', 'character_id'),
            ('outfit', 'outfit_id'),
            ('expression', 'expression_id'),
            ('rating', 'rating'),
            ('family', 'model_family'),
            ('kind', 'kind'),
        ):
            if params.get(key):
                items = [i for i in items if i[field] == params[key]]
        folder = params.get('folder')
        if folder:
            items = [i for i in items if i['folder'] == folder or i['folder'].startswith(folder + '/')]
        # Images made after the first page loaded wait for a refresh, so paging stays stable.
        newer = sum(i['_mtime_ns'] > cutoff for i in items)
        items = [i for i in items if i['_mtime_ns'] <= cutoff]
        if _flag(params, 'latest'):
            latest = {}
            for item in items:
                key = combo_of(item) if item['kind'] == 'image' else (item['path'],)
                if key not in latest or (item['_mtime_ns'], item['path']) > (
                    latest[key]['_mtime_ns'],
                    latest[key]['path'],
                ):
                    latest[key] = item
            items = list(latest.values())
        sort = params.get('sort') or 'newest'
        if sort not in SORTS:
            raise ValueError(Msg('server.gallery.invalid_query', 'Invalid gallery query.'))
        if sort == 'code':
            items.sort(key=lambda i: (*combo_of(i), i['path']))
        else:
            items.sort(key=lambda i: (i['_mtime_ns'], i['path']), reverse=sort == 'newest')
        human, auto, adopted_only = (
            params.get('human_status'),
            params.get('auto_status'),
            _flag(params, 'adopted'),
        )
        if human or auto or adopted_only:
            matched = [
                i
                for i in (self.annotate(x) for x in items)
                if (not human or i['human_status'] == human)
                and (not auto or i['auto_status'] == auto)
                and (not adopted_only or i['adopted'])
            ]
            page_items = matched[(page - 1) * size : page * size]
        else:
            matched = items
            page_items = [self.annotate(i) for i in items[(page - 1) * size : page * size]]
        total = len(matched)
        # "Select all filtered" asks for every matching path at once.
        paths = [i['path'] for i in matched][:10000] if _flag(params, 'paths_only') else None
        return {
            'results': page_items,
            'total': total,
            'page': page,
            'page_size': size,
            'pages': (total + size - 1) // size,
            'snapshot': str(cutoff),
            'newer': newer,
            **({'paths': paths} if paths is not None else {}),
        }

    def detail(self, relative):
        item = self.annotate(self.gallery.find(relative))
        try:
            item['record'] = {k: v for k, v in self.gallery.metadata(relative).items() if k != 'workflow'}
        except ValueError:
            item['record'] = None
        with self.lock:
            item['history'] = [h for h in self.state['history'] if h['path'] == relative][-20:]
            pointer = self.state['adopted'].get(_key(combo_of(item))) if item['kind'] == 'image' else None
        item['adopted_path'] = pointer['path'] if pointer else None
        return item

    # --- verdicts ---------------------------------------------------------------------------------------------------
    def review(self, body):
        verdict, items = body.get('verdict'), body.get('items')
        if verdict not in VERDICTS or not isinstance(items, list) or not 1 <= len(items) <= 10000:
            raise ValueError(
                Msg('server.gallery.invalid_review', 'Choose images and pass, fail or unreviewed.')
            )
        note = body.get('note')
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise ValueError(
                Msg('server.gallery.invalid_review', 'Choose images and pass, fail or unreviewed.')
            )
        chosen, seen = [], set()
        for entry in items:
            relative = entry.get('path') if isinstance(entry, dict) else entry
            if not isinstance(relative, str) or relative in seen:
                continue
            seen.add(relative)
            item = self.gallery.find(relative)
            sha = self.sha256(relative, fresh=True)
            expected = entry.get('sha256') if isinstance(entry, dict) else None
            if expected and expected != sha:
                raise ValueError(
                    Msg(
                        'server.gallery.changed',
                        'The image changed after it was shown: {path}',
                        path=relative,
                    )
                )
            chosen.append((item, sha))
        with self.lock:
            state = copy.deepcopy(self.state)
            when = now()
            for item, sha in chosen:
                relative = item['path']
                record = state['records'].setdefault(
                    _identity(relative, sha), {'path': relative, 'sha256': sha}
                )
                old = record.get('human', 'unreviewed')
                key = _key(combo_of(item))
                pointer = {'path': relative, 'sha256': sha}
                if verdict == 'pass' and item['kind'] == 'image':
                    state['adopted'][key] = pointer
                elif state['adopted'].get(key) == pointer:
                    del state['adopted'][key]
                record.update(human=verdict, reviewed_at=when)
                if note is not None:
                    record['note'] = note
                state['history'].append({'at': when, 'path': relative, 'from': old, 'to': verdict})
                record['human_revision'] = state.setdefault('revision', 0) + 1
                state['revision'] = record['human_revision']
            self._save(state)
        for listener in self.listeners:
            listener()
        return {'results': [self.annotate(item) for item, _ in chosen], 'updated': len(chosen)}

    def record_auto(self, relative, verdict, reason='', details=None):
        if verdict not in AUTO:
            raise ValueError('invalid automatic verdict')
        sha = self.sha256(relative, fresh=True)
        with self.lock:
            state = copy.deepcopy(self.state)
            record = state['records'].setdefault(_identity(relative, sha), {'path': relative, 'sha256': sha})
            when = now()
            state['history'].append(
                {
                    'at': when,
                    'path': relative,
                    'source': 'auto',
                    'from': record.get('auto', 'pending'),
                    'to': verdict,
                }
            )
            record.update(auto=verdict, auto_reason=reason, auto_details=details, auto_at=when)
            self._save(state)

    def acceptance_revision(self, combo):
        """The revision of the adopted image's pass while that image is unchanged, else None."""
        with self.lock:
            pointer = self.state['adopted'].get(_key(combo))
            if not pointer:
                return None
            record = self.state['records'].get(_identity(pointer['path'], pointer['sha256']), {})
            revision = record.get('human_revision')
            if record.get('human') != 'pass' or not isinstance(revision, int):
                return None
        try:
            return revision if self.sha256(pointer['path']) == pointer['sha256'] else None
        except (OSError, ValueError):
            return None

    def revision(self):
        with self.lock:
            return self.state.get('revision', 0)

    # --- export -----------------------------------------------------------------------------------------------------
    def plan_export(self, filters):
        """Adopted images in scope, plus the combinations in scope that have images but nothing adopted."""
        filters = filters or {}
        items = [i for i in self.gallery.snapshot_items() if i['kind'] == 'image']
        for key, field in (
            ('work', 'work_id'),
            ('character', 'character_id'),
            ('outfit', 'outfit_id'),
            ('rating', 'rating'),
        ):
            if filters.get(key):
                items = [i for i in items if i[field] == filters[key]]
        by_path = {i['path']: i for i in items}
        with self.lock:
            adopted = copy.deepcopy(self.state['adopted'])
        plan = []
        for key, pointer in adopted.items():
            item = by_path.get(pointer['path'])
            if item is None or _key(combo_of(item)) != key:
                continue
            try:
                if self.sha256(item['path']) != pointer['sha256']:
                    continue
            except (OSError, ValueError):
                continue
            plan.append(item)
        chosen = {combo_of(i) for i in plan}
        missing = sorted({combo_of(i) for i in items} - chosen)
        one_work = bool(filters.get('work'))
        sources, collisions = plan_paths(sorted(plan, key=combo_of), one_work=one_work)
        names = {destination: source for source, destination in sources.items()}
        return {
            'count': len(names),
            'files': names,
            'missing': ['/'.join(m) for m in missing],
            'manifest': sources,
            'collisions': collisions,
        }

    def export_zip(self, body):
        filters = body.get('filters') or {}
        plan = self.plan_export(filters)
        if not plan['files']:
            raise ValueError(Msg('server.gallery.nothing_adopted', 'No adopted images in this scope.'))
        if plan['missing'] and not body.get('allow_partial'):
            raise ValueError(
                Msg(
                    'server.gallery.export_incomplete',
                    '{n} combinations have images but none adopted.',
                    n=len(plan['missing']),
                )
            )
        if plan['collisions']:
            raise ValueError(
                Msg(
                    'server.gallery.export_collision',
                    'Deployment paths collide: {paths}',
                    paths=', '.join(plan['collisions']),
                )
            )
        descriptor, name = tempfile.mkstemp(prefix='atelierx-adopted-', suffix='.zip')
        os.close(descriptor)
        target = Path(name)
        try:
            with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for entry, relative in sorted(plan['files'].items()):
                    source = self.gallery.safe_path(relative)
                    if body.get('strip_metadata'):
                        # For sharing: the pixels only, without prompts, workflow or settings.
                        archive.writestr(entry, _without_metadata(source))
                    else:
                        archive.write(source, entry)
                archive.writestr(
                    'manifest.json',
                    json.dumps({'source_to_export': plan['manifest']}, ensure_ascii=False, indent=2),
                )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        label = '-'.join(filters.get(k) or 'all' for k in ('work', 'character'))
        return target, f'adopted-{label}.zip'
