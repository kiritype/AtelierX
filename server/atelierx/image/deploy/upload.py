"""Uploading adopted images to a deployment target (decision 0023, features/25-deployment).

A plan names, for each adopted image in the chosen range, the path it gets from the work's or target's path format and
the deployment codes, and compares it with what the bucket already holds: new, overwrite, unchanged (same MD5),
no code, or a clash with another image. An upload runs the new and changed rows in a background thread. Results are
kept in memory only; the next plan compares with the bucket again.
"""

import hashlib
import threading
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from ...core.i18n import AppError, Msg, message_of
from ...core.lifecycle import CANCELLED, CANCELLING, DONE, FAILED, RUNNING
from .. import library
from ..designs import character_design_path
from ..tools.convert import convert
from ..util import now, read_json
from . import targets as deploy_targets

WEBP = {'quality': 95, 'lossless': False, 'keep_metadata': False, 'long_side': 0}
BAD_PART = set('\\:*?"<>|')
MAX_ROWS = 5000
KEEP_RUNS = 20


def render(path_format, values):
    """The path for one image, or None when a code it needs is empty."""
    if any(not values.get(name) for name in deploy_targets.PLACEHOLDERS if '{' + name + '}' in path_format):
        return None
    out = path_format
    for name in deploy_targets.PLACEHOLDERS:
        out = out.replace('{' + name + '}', values.get(name) or '')
    return out + '.webp'


def clean_path(text):
    """A path typed in the preview: '/'-separated non-empty parts without forbidden characters, ending in .webp."""
    text = (text or '').strip().strip('/')
    if not text:
        return None
    if not text.lower().endswith('.webp'):
        text += '.webp'
    parts = text.split('/')
    if any(
        not p.strip() or p in ('.', '..') or set(p) & BAD_PART or any(ord(c) < 32 for c in p) for p in parts
    ):
        raise ValueError(Msg('server.deploy.bad_path', 'This path cannot be used: {path}', path=text[:200]))
    return text


def static_prefix(path_format):
    """The part of the format before its first placeholder, cut back to a folder: the bucket listing's prefix."""
    head = path_format.split('{', 1)[0]
    return head[: head.rfind('/') + 1] if '/' in head else ''


class DeployUploads:
    def __init__(self, runtime):
        self.rt = runtime
        self.cache = Path(runtime.paths.state) / 'deploy' / 'webp'
        self.lock = threading.Lock()
        self.runs = {}
        self.transport = None  # tests answer the bucket with httpx.MockTransport

    # --- plan ------------------------------------------------------------------------------------------------------
    def _settings(self, body):
        work = self.rt.works.get(body.get('work') or '')
        chosen = deploy_targets.work_settings(work)
        target_id = body.get('target') or chosen['target']
        if not target_id:
            raise ValueError(Msg('server.deploy.choose_target', 'Choose a deployment target.'))
        target = self.rt.deploy_targets.get(target_id)
        path_format = deploy_targets.check_format(
            body.get('path_format') or chosen['path_format'] or target['path_format']
        )
        return work, target_id, target, path_format

    def _webp(self, source):
        """WebP bytes of an image without its metadata, cached by the source's content."""
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        cached = self.cache / f'{digest}.webp'
        if cached.is_file():
            return cached.read_bytes()
        data, _ = convert(source, WEBP)
        self.cache.mkdir(parents=True, exist_ok=True)
        part = cached.with_suffix('.part')
        part.write_bytes(data)
        part.replace(cached)
        return data

    def plan(self, body):
        body = body if isinstance(body, dict) else {}
        work, target_id, target, path_format = self._settings(body)
        filters = {'work': work.id}
        for key in ('character', 'outfit'):
            if body.get(key):
                filters[key] = str(body[key])
        # Left out or null: every rating. A list, even an empty one, is the choice (empty: nothing to upload).
        ratings = body.get('ratings')
        ratings = set(ratings) if isinstance(ratings, list) else None
        overrides = body.get('paths') if isinstance(body.get('paths'), dict) else {}

        export = self.rt.reviews.plan_export(filters)
        by_path = {i['path']: i for i in self.rt.gallery.snapshot_items()}
        expressions = library.items(self.rt.paths, work, 'expressions')
        designs = {}

        def outfit_code(character_id, outfit_id):
            if character_id not in designs:
                try:
                    designs[character_id] = read_json(character_design_path(work, character_id), {}) or {}
                except AppError:
                    designs[character_id] = {}
            return str(((designs[character_id].get('outfits') or {}).get(outfit_id) or {}).get('code') or '')

        rows = []
        for source in sorted(export.get('manifest') or {}):
            item = by_path.get(source)
            if item is None or (ratings is not None and item.get('rating') not in ratings):
                continue
            expression = expressions.get(item['expression_id']) or {}
            values = {
                'work': item['work_id'],
                'character': item['character_id'],
                'outfit': outfit_code(item['character_id'], item['outfit_id']),
                'expression': str(expression.get('code') or ''),
            }
            auto = render(path_format, values)
            dest = clean_path(overrides[source]) if overrides.get(source) else auto
            rows.append(
                {
                    'source': source,
                    'thumbnail_url': item.get('thumbnail_url'),
                    'character_id': item['character_id'],
                    'outfit_id': item['outfit_id'],
                    'outfit_code': values['outfit'],
                    'expression_id': item['expression_id'],
                    'expression_name': item.get('expression_name') or expression.get('name') or '',
                    'expression_code': values['expression'],
                    'rating': item.get('rating') or '',
                    'auto_path': auto,
                    'path': dest,
                    'edited': bool(overrides.get(source)),
                }
            )
        if len(rows) > MAX_ROWS:
            raise ValueError(
                Msg(
                    'server.deploy.too_many',
                    'Choose a smaller range: up to {max} images at a time.',
                    max=MAX_ROWS,
                )
            )

        # The bucket as it is now: what each path would be.
        client = self.rt.deploy_targets.client(target_id, self.transport)
        prefixes = {static_prefix(path_format)} | {
            str(PurePosixPath(r['path']).parent) + '/' for r in rows if r['edited'] and r['path']
        }
        remote = {}
        for prefix in sorted(prefixes):
            remote.update(client.list('' if prefix in ('./', '/') else prefix))
        used = {}
        for row in rows:
            if row['path']:
                used.setdefault(row['path'], []).append(row['source'])
        public = target['public_url']
        for row in rows:
            if not row['path']:
                row['status'] = 'no_code'
                continue
            row['url'] = f'{public}/{quote(row["path"])}' if public else ''
            if len(used[row['path']]) > 1:
                row['status'] = 'clash'
                continue
            data = self._webp(Path(self.rt.paths.output) / row['source'])
            row['bytes'] = len(data)
            etag = remote.get(row['path'])
            row['status'] = (
                'new'
                if etag is None
                else 'unchanged'
                if etag == hashlib.md5(data).hexdigest()
                else 'overwrite'
            )
        counts = {}
        for row in rows:
            counts[row['status']] = counts.get(row['status'], 0) + 1
        return {
            'work': work.id,
            'target': target_id,
            'target_name': target['name'],
            'public_url': public,
            'path_format': path_format,
            'rows': rows,
            'counts': counts,
            'missing': export.get('missing') or [],
        }

    # --- upload ----------------------------------------------------------------------------------------------------
    def start(self, body):
        """Upload the new and changed rows of a fresh plan (or only the paths named in ``only``)."""
        plan = self.plan(body)
        only = set(body.get('only') or []) if isinstance(body.get('only'), list) else None
        todo = [
            r
            for r in plan['rows']
            if r['status'] in ('new', 'overwrite') and (only is None or r['path'] in only)
        ]
        if not todo:
            raise ValueError(
                Msg('server.deploy.nothing', 'Nothing to upload: every image is unchanged or held back.')
            )
        with self.lock:
            if any(r['status'] in (RUNNING, CANCELLING) for r in self.runs.values()):
                raise ValueError(Msg('server.deploy.busy', 'An upload is already running.'))
            run_id = uuid.uuid4().hex[:12]
            self.runs[run_id] = {
                'id': run_id,
                'status': RUNNING,
                'work': plan['work'],
                'target': plan['target'],
                'target_name': plan['target_name'],
                'total': len(todo),
                'done': 0,
                'results': [],
                'started_at': now(),
                'finished_at': None,
            }
            for old in sorted(self.runs, key=lambda k: self.runs[k]['started_at'])[:-KEEP_RUNS]:
                self.runs.pop(old, None)
        client = self.rt.deploy_targets.client(plan['target'], self.transport)
        threading.Thread(
            target=self._run, args=(run_id, client, todo), name='deploy-upload', daemon=True
        ).start()
        return self.public(run_id)

    def _run(self, run_id, client, todo):
        run = self.runs[run_id]
        for row in todo:
            if run['status'] == CANCELLING:
                break
            result = {
                'path': row['path'],
                'source': row['source'],
                'url': row.get('url', ''),
                'overwrote': row['status'] == 'overwrite',
            }
            try:
                data = self._webp(Path(self.rt.paths.output) / row['source'])
                client.put(row['path'], data, 'image/webp')
                result['ok'] = True
            except Exception as error:  # one file failing does not stop the others
                result.update(ok=False, error=message_of(error))
            with self.lock:
                run['results'].append(result)
                run['done'] += 1
        with self.lock:
            failed = sum(1 for r in run['results'] if not r['ok'])
            if run['status'] == CANCELLING:
                run['status'] = CANCELLED
            else:
                run['status'] = FAILED if failed == len(run['results']) else DONE
            run['finished_at'] = now()

    def public(self, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if run is None:
                raise AppError(Msg('server.deploy.no_run', 'This upload is no longer listed.'), 404)
            return {**run, 'results': list(run['results'])}

    def cancel(self, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if run and run['status'] == RUNNING:
                run['status'] = CANCELLING
        return self.public(run_id)

    def active(self):
        with self.lock:
            return [dict(r, results=None) for r in self.runs.values() if r['status'] in (RUNNING, CANCELLING)]
