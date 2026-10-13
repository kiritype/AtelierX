"""Durable bulk tool receipts, separate from the bounded execution queue (#222)."""

import copy
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import uuid

from ...core.i18n import AppError, Msg, message_of, wire
from ...core.lifecycle import FINISHED
from ..job_queue import MAX_QUEUED
from ..util import now, read_json
from . import processors

MAX_TARGETS = 20000
MAX_INFLIGHT = 32
MAX_STORAGE = 1024**3
MIN_FREE = 256 * 1024**2
OPERATIONS = ('gallery', 'tag', 'postprocess', 'censor', 'alpha')


def encoded(value):
    return json.dumps(wire(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def signature(path):
    stat = path.stat()
    return [stat.st_mtime_ns, stat.st_size]


class ToolBatches:
    def __init__(self, runtime):
        self.rt = runtime
        self.lock = runtime.lock
        self.folder = runtime.paths.data / 'image' / 'batches'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / 'batches.sqlite3'
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
            self.db.close()
            raise RuntimeError('Unsupported bulk receipt schema')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                operation TEXT NOT NULL, settings TEXT NOT NULL, created_at TEXT NOT NULL,
                cancelled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS items (
                batch TEXT NOT NULL, ordinal INTEGER NOT NULL, target TEXT NOT NULL,
                status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                job_id TEXT UNIQUE, result TEXT, PRIMARY KEY(batch, ordinal));
            CREATE INDEX IF NOT EXISTS pending_items ON items(status, batch, ordinal);
            CREATE TABLE IF NOT EXISTS history (
                job_id TEXT PRIMARY KEY, batch TEXT NOT NULL, ordinal INTEGER NOT NULL, result TEXT NOT NULL);
            PRAGMA user_version=1;
        """)
        self.cursor = 0
        self.reconcile(restart=True)

    def _batch(self, ident):
        row = self.db.execute('SELECT * FROM batches WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise ValueError(Msg('server.bulk.missing', 'Bulk request not found.'))
        return row

    def _storage(self):
        return sum(p.stat().st_size for p in self.folder.rglob('*') if p.is_file())

    def submit(self, body):
        operation = body.get('operation')
        request_id = body.get('request_id')
        targets = body.get('paths') if operation == 'gallery' else body.get('ids')
        if (
            operation not in OPERATIONS
            or not isinstance(targets, list)
            or not 1 <= len(targets) <= MAX_TARGETS
        ):
            raise ValueError(Msg('server.bulk.targets', 'Choose 1 to {limit} targets.', limit=MAX_TARGETS))
        if not all(isinstance(t, str) and 0 < len(t) <= 1024 for t in targets):
            raise ValueError(Msg('server.bulk.targets_invalid', 'Invalid bulk targets.'))
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', request_id):
            raise ValueError(
                Msg('server.bulk.request_id', 'A request ID is required to prevent duplicate submissions.')
            )
        settings = {
            k: copy.deepcopy(v)
            for k, v in body.items()
            if k not in ('paths', 'ids', 'request_id', 'operation')
        }
        if len(encoded(settings).encode()) > 65536:
            raise ValueError(Msg('server.bulk.settings_large', 'Bulk settings are too large.'))
        fingerprint = hashlib.sha256(
            encoded({'operation': operation, 'targets': targets, 'settings': settings}).encode()
        ).hexdigest()
        with self.lock:
            previous = self.db.execute(
                'SELECT id, fingerprint FROM batches WHERE request_id=?', (request_id,)
            ).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise AppError(
                        Msg(
                            'server.bulk.duplicate_changed',
                            'This request ID was already used with different settings.',
                        ),
                        409,
                    )
                return self.public(previous['id'])
            targets = list(dict.fromkeys(targets))
            waiting = self.db.execute(
                "SELECT count(*) FROM items WHERE status IN ('pending','queued','running','cancelling')"
            ).fetchone()[0]
            if waiting + len(targets) > MAX_TARGETS:
                raise ValueError(
                    Msg(
                        'server.bulk.capacity',
                        '{waiting} targets are unfinished; {adding} would exceed {limit}. Nothing was accepted.',
                        waiting=waiting,
                        adding=len(targets),
                        limit=MAX_TARGETS,
                    )
                )
            storage = self._storage()
            free_space = shutil.disk_usage(self.folder).free
            if storage + len(targets) * 4096 >= MAX_STORAGE or free_space < MIN_FREE + len(targets) * 4096:
                raise ValueError(
                    Msg(
                        'server.bulk.disk',
                        'Not enough space for a durable bulk request. Nothing was accepted.',
                    )
                )
            if operation == 'postprocess':
                info = self.rt.postprocess_info()
                if not info['available']:
                    raise ValueError(info['error'])
                processor = processors.get(settings.get('op'), settings.get('method') or 'local')
                settings['options'] = processor.check(settings.get('options') or {}, info)
                settings['_info'] = info
                if processor.needs_record:
                    settings['_catalog'] = self.rt.comfy.catalog()
                mask_kind = processor.mask_input
            elif operation == 'tag':
                settings['_info'] = self.rt.tagger_info()
                if not settings['_info']['available']:
                    raise ValueError(settings['_info']['error'])
                mask_kind = None
            else:
                mask_kind = operation if operation in ('censor', 'alpha') else None
            ident = uuid.uuid4().hex
            batch_dir = self.folder / ident
            snapshots = []
            mask_bytes = 0
            try:
                for ordinal, target in enumerate(targets):
                    snapshot = {'id': target, 'seed': secrets.randbits(32)}
                    try:
                        item = None if operation == 'gallery' else self.rt.tools.get(target)
                        path = self.rt.gallery.safe_path(target) if item is None else self.rt.tools.file(item)
                        snapshot.update(source=operation == 'gallery', signature=signature(path))
                        sidecar = path.with_suffix('.json')
                        snapshot['sidecar'] = signature(sidecar) if sidecar.is_file() else None
                        if mask_kind:
                            mask = self.rt.tools.mask_path(target, mask_kind)
                            mask_bytes += mask.stat().st_size
                            if (
                                storage + mask_bytes + len(targets) * 4096 > MAX_STORAGE
                                or free_space < MIN_FREE + mask_bytes + len(targets) * 4096
                            ):
                                raise AppError(
                                    Msg(
                                        'server.bulk.disk',
                                        'Not enough space for a durable bulk request. Nothing was accepted.',
                                    ),
                                    400,
                                )
                            batch_dir.mkdir(exist_ok=True)
                            frozen = batch_dir / f'{ordinal}.png'
                            shutil.copyfile(mask, frozen)
                            snapshot['mask'] = frozen.relative_to(self.folder).as_posix()
                    except (OSError, ValueError) as error:
                        snapshot['error'] = str(message_of(error))
                    snapshots.append((ident, ordinal, encoded(snapshot), 'pending'))
                with self.db:
                    self.db.execute(
                        'INSERT INTO batches(id,request_id,fingerprint,operation,settings,created_at) VALUES(?,?,?,?,?,?)',
                        (ident, request_id, fingerprint, operation, encoded(settings), now()),
                    )
                    self.db.executemany(
                        'INSERT INTO items(batch,ordinal,target,status) VALUES(?,?,?,?)', snapshots
                    )
            except Exception:
                # Only this not-yet-accepted request's synthetic mask copies are removed.
                for path in batch_dir.glob('*.png') if batch_dir.exists() else ():
                    path.unlink()
                if batch_dir.exists():
                    batch_dir.rmdir()
                raise
            return self.public(ident)

    def public(self, ident):
        with self.lock:
            batch = self._batch(ident)
            counts = {
                key: 0
                for key in (
                    'pending',
                    'queued',
                    'running',
                    'cancelling',
                    'done',
                    'failed',
                    'cancelled',
                    'interrupted',
                )
            }
            for row in self.db.execute(
                'SELECT status,count(*) AS n FROM items WHERE batch=? GROUP BY status', (ident,)
            ):
                counts[row['status']] = row['n']
            total = sum(counts.values())
            finished = sum(counts[key] for key in FINISHED)
            return {
                'id': ident,
                'operation': batch['operation'],
                'created_at': batch['created_at'],
                'total': total,
                'counts': counts,
                'progress': finished / total if total else 1,
                'cancelled': bool(batch['cancelled']),
                'paused': self.rt.queue.paused,
                'accepted': total,
            }

    def list(self):
        with self.lock:
            return {
                'batches': [
                    self.public(row[0])
                    for row in self.db.execute('SELECT id FROM batches ORDER BY created_at DESC LIMIT 100')
                ]
            }

    def details(self, ident, offset=0, limit=100):
        with self.lock:
            self._batch(ident)
            rows = self.db.execute(
                'SELECT ordinal,target,status,attempt,result FROM items WHERE batch=? ORDER BY ordinal LIMIT ? OFFSET ?',
                (ident, min(max(limit, 1), 500), max(offset, 0)),
            )
            return {
                'items': [
                    {
                        **dict(row),
                        'target': json.loads(row['target']),
                        'result': json.loads(row['result']) if row['result'] else None,
                    }
                    for row in rows
                ]
            }

    def _record(self, row, job):
        result = encoded(job)
        with self.db:
            self.db.execute(
                'UPDATE items SET status=?,result=? WHERE batch=? AND ordinal=?',
                (job['status'], result, row['batch'], row['ordinal']),
            )
            if job['status'] in FINISHED:
                self.db.execute(
                    'INSERT OR REPLACE INTO history VALUES(?,?,?,?)',
                    (job['id'], row['batch'], row['ordinal'], result),
                )

    def reconcile(self, restart=False):
        with self.lock:
            jobs = self.rt.queue.by_id()
            rows = list(
                self.db.execute(
                    "SELECT * FROM items WHERE job_id IS NOT NULL AND status IN ('queued','running','cancelling')"
                )
            )
            recovered = self._outputs({row['job_id'] for row in rows}) if restart else {}
            for row in rows:
                job = jobs.get(row['job_id'])
                if row['job_id'] in recovered:
                    result = recovered[row['job_id']]
                    if job is not None:
                        job.update(status='done', result=result, finished_at=now())
                    else:
                        self._record(row, {'id': row['job_id'], 'status': 'done', 'result': result})
                        continue
                if job is not None:
                    if self._batch(row['batch'])['cancelled'] and job['status'] == 'queued':
                        self.rt.queue.cancel(job['id'])
                    if job['status'] != row['status'] or job['status'] in FINISHED:
                        self._record(row, job)
                elif restart:
                    # Persisted intent without a queue append is still safe to issue under its stable job ID.
                    if self._batch(row['batch'])['cancelled']:
                        self._record(row, {'id': row['job_id'], 'status': 'cancelled'})
                    elif row['status'] == 'queued':
                        with self.db:
                            self.db.execute(
                                "UPDATE items SET status='pending' WHERE batch=? AND ordinal=?",
                                (row['batch'], row['ordinal']),
                            )
                    else:
                        self._record(
                            row,
                            {
                                'id': row['job_id'],
                                'status': 'interrupted',
                                'error': 'Interrupted before a durable result',
                            },
                        )
            # Move complete records only after their full diagnostic payload has committed in this database.
            finished = [job for job in self.rt.queue.jobs if job.get('bulk_id') and job['status'] in FINISHED]
            remove = []
            for job in finished:
                saved = self.db.execute('SELECT status FROM items WHERE job_id=?', (job['id'],)).fetchone()
                if saved and saved[0] in FINISHED:
                    remove.append(job)
            if remove:
                removed_ids = {job['id'] for job in remove}
                self.rt.queue.jobs = [job for job in self.rt.queue.jobs if job['id'] not in removed_ids]
                self.rt.queue.persist()

    def _outputs(self, wanted):
        """Recover an already committed output after a crash before queue.done was saved."""
        if not wanted:
            return {}
        found = {}
        for path in self.rt.paths.output.rglob('*.json'):
            try:
                record = read_json(path) or {}
            except OSError:
                continue
            if not isinstance(record, dict):
                continue
            post = record.get('postprocessing')
            ident = record.get('job_id') or (post.get('job_id') if isinstance(post, dict) else None)
            if not isinstance(ident, str):
                continue
            if ident in wanted and path.with_suffix('.png').is_file():
                relative = path.with_suffix('.png').relative_to(self.rt.paths.output).as_posix()
                found[ident] = {'recovered_output': relative}
                # Repair a crash between the output rename and the tool-list insert.
                try:
                    self.rt.tools.add_gallery([relative])
                except (OSError, ValueError):
                    pass  # The output remains recoverable even when the list is full.
        for item in getattr(getattr(self.rt, 'tools', None), 'items', ()):
            for field in ('tags', 'mask', 'alpha_mask', 'inpaint_mask'):
                ident = (item.get(field) or {}).get('job_id')
                if ident in wanted:
                    found[ident] = {'item_ids': [item['id']], 'field': field}
        return found

    def _source(self, target):
        if target.get('error'):
            raise ValueError(target['error'])
        path = (
            self.rt.gallery.safe_path(target['id'])
            if target['source']
            else self.rt.tools.file(self.rt.tools.get(target['id']))
        )
        sidecar = path.with_suffix('.json')
        current_sidecar = signature(sidecar) if sidecar.is_file() else None
        if signature(path) != target['signature'] or current_sidecar != target.get('sidecar'):
            raise ValueError(
                Msg(
                    'server.bulk.source_changed',
                    'The source changed after this request was accepted. Submit it again with the new source.',
                )
            )

    def check_job(self, job):
        with self.lock:
            row = self.db.execute('SELECT target,batch FROM items WHERE job_id=?', (job['id'],)).fetchone()
            if row:
                if self._batch(row['batch'])['cancelled']:
                    self.rt.queue.update(job, status='cancelled')
                    return False
                target = json.loads(row['target'])
                self._source(target)
                if target.get('mask'):
                    job['bulk_mask'] = str(self.folder / target['mask'])
            return True

    def pump(self):
        with self.lock:
            self.reconcile()
            if self.rt.queue.paused:
                return
            inflight = sum(
                j.get('bulk_id') is not None and j['status'] not in FINISHED for j in self.rt.queue.jobs
            )
            room = min(MAX_INFLIGHT - inflight, MAX_QUEUED - self.rt.queue.queued_count())
            if room <= 0:
                return
            batches = list(
                self.db.execute(
                    "SELECT b.* FROM batches b WHERE cancelled=0 AND EXISTS(SELECT 1 FROM items i WHERE i.batch=b.id AND i.status='pending') ORDER BY created_at"
                )
            )
            if not batches:
                return
            # One target from each batch per turn, always appended behind already-waiting normal jobs.
            for _ in range(room):
                batch = batches[self.cursor % len(batches)]
                self.cursor += 1
                row = self.db.execute(
                    "SELECT * FROM items WHERE batch=? AND status='pending' ORDER BY ordinal LIMIT 1",
                    (batch['id'],),
                ).fetchone()
                if row is None:
                    continue
                target, settings = json.loads(row['target']), json.loads(batch['settings'])
                job_id = f'{batch["id"]}-{row["ordinal"]}-{row["attempt"]}'
                try:
                    self._source(target)
                    operation = batch['operation']
                    mask = str(self.folder / target['mask']) if target.get('mask') else None
                    if operation == 'postprocess':
                        prepared = self.rt.enqueue_postprocess(
                            {**settings, 'ids': [target['id']]},
                            enqueue=False,
                            info=settings['_info'],
                            catalog=settings.get('_catalog'),
                            frozen_mask=mask,
                        )
                        job = prepared[0]
                        if job.get('post_source'):
                            job['post_source']['seed'] = target['seed']
                    elif operation == 'tag':
                        job = self.rt.enqueue_tags(
                            {**settings, 'ids': [target['id']]}, enqueue=False, info=settings['_info']
                        )[0]
                    else:
                        job = {
                            'kind': f'bulk_{operation}',
                            'status': 'queued',
                            'created_at': now(),
                            'tool_item': target['id'],
                            'title': f'{operation} · {target["id"]}',
                            'snapshot': settings,
                            'bulk_mask': mask,
                        }
                    job.update(id=job_id, bulk_id=batch['id'], bulk_ordinal=row['ordinal'])
                    # The receipt of this queue intent commits first; restart reconciles by this stable ID.
                    with self.db:
                        self.db.execute(
                            "UPDATE items SET status='queued',job_id=? WHERE batch=? AND ordinal=?",
                            (job_id, batch['id'], row['ordinal']),
                        )
                    try:
                        self.rt.queue.add([job])
                    except OSError as error:
                        # Keep the committed intent and any in-memory append aligned.
                        # Dispatch must pause; this is not a failed source operation.
                        raise RuntimeError('Could not persist bulk queue admission') from error
                except (OSError, ValueError) as error:
                    self._record(row, {'id': job_id, 'status': 'failed', 'error': message_of(error)})

    def run_cpu(self, job):
        if not self.check_job(job):
            return
        if self.rt.queue.status_of(job) == 'cancelling':
            self.rt.queue.update(job, status='cancelled')
            return
        if job['kind'] == 'bulk_gallery':
            result = self.rt.tools.add_gallery([job['tool_item']])
            result = {'item_ids': [item['id'] for item in result['items']]}
        else:
            body = {**job['snapshot'], 'id': job['tool_item']}
            if job['kind'] == 'bulk_censor':
                result = self.rt.apply_censor(body, frozen_mask=job['bulk_mask'], job_id=job['id'])
            else:
                result = self.rt.apply_alpha(body, frozen_mask=job['bulk_mask'], job_id=job['id'])
        self.rt.queue.update(job, status='done', finished_at=now(), result=result)

    def cancel(self, ident):
        with self.lock:
            self._batch(ident)
            with self.db:
                self.db.execute('UPDATE batches SET cancelled=1 WHERE id=?', (ident,))
                self.db.execute(
                    "UPDATE items SET status='cancelled' WHERE batch=? AND status='pending'", (ident,)
                )
            for job in self.rt.queue.select(
                lambda j: j.get('bulk_id') == ident and j['status'] in ('queued', 'running')
            ):
                self.rt.queue.cancel(job['id'])
            self.reconcile()
            return self.public(ident)

    def retry(self, ident):
        with self.lock:
            self.reconcile()
            self._batch(ident)
            rows = list(
                self.db.execute(
                    "SELECT * FROM items WHERE batch=? AND job_id IS NOT NULL AND status IN ('failed','interrupted','cancelled')",
                    (ident,),
                )
            )
            recovered = self._outputs({row['job_id'] for row in rows})
            for row in rows:
                if row['job_id'] in recovered:
                    self._record(
                        row, {'id': row['job_id'], 'status': 'done', 'result': recovered[row['job_id']]}
                    )
            count = self.db.execute(
                "SELECT count(*) FROM items WHERE batch=? AND status IN ('failed','interrupted','cancelled')",
                (ident,),
            ).fetchone()[0]
            waiting = self.db.execute(
                "SELECT count(*) FROM items WHERE status IN ('pending','queued','running','cancelling')"
            ).fetchone()[0]
            if count + waiting > MAX_TARGETS:
                raise ValueError(
                    Msg(
                        'server.bulk.retry_capacity',
                        'Let unfinished requests finish before retrying this batch.',
                    )
                )
            with self.db:
                self.db.execute('UPDATE batches SET cancelled=0 WHERE id=?', (ident,))
                self.db.execute(
                    "UPDATE items SET status='pending',attempt=attempt+1,job_id=NULL,result=NULL WHERE batch=? AND status IN ('failed','interrupted','cancelled')",
                    (ident,),
                )
            return self.public(ident)
