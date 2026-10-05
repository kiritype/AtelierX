"""Content-addressed snapshots of items and app data (decision 0003, data-model: 스냅샷)."""

import re
import secrets
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from .fsutil import atomic_write_bytes, read_json, sha256_bytes, write_json
from .i18n import AppError, Msg
from .works import APP_DIR, ITEM_SUFFIXES, now_iso

EXCLUDED_APP = ('history', 'trash', 'drafts')
PROTECTED = ('manual', 'before_bulk')
SNAPSHOT_ID = re.compile(r'[0-9A-Za-z-]+')
DIGEST = re.compile(r'[0-9a-f]{64}')


def _bad_path():
    return AppError(Msg('server.works.bad_path', 'This path is not allowed.'))


class Snapshots:
    def __init__(self, work):
        self.work = work
        self.root = work.app / 'history'

    # Paths, ids and digests come from requests and from snapshot files; none may lead outside the work folder or the
    # store, whatever a snapshot file says.
    def path_in_work(self, rel):
        """The file a snapshot path names: relative, '/'-separated, inside the work folder, not the history itself."""
        rel = str(rel or '')
        pieces = rel.split('/')
        if not rel or '\\' in rel or ':' in rel or any(p in ('', '.', '..') for p in pieces):
            raise _bad_path()
        if pieces[0] == APP_DIR and len(pieces) > 1 and pieces[1] in EXCLUDED_APP:
            raise _bad_path()
        path = self.work.folder.joinpath(*PurePosixPath(rel).parts)
        if self.work.folder.resolve() not in path.resolve().parents:
            raise _bad_path()
        return path

    def _object(self, digest):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise AppError(Msg('server.snapshots.damaged', 'This snapshot is damaged.'))
        return self.root / 'objects' / digest[:2] / digest

    def _files(self):
        folder = self.work.folder
        for path in sorted(folder.rglob('*')):
            if not path.is_file():
                continue
            parts = path.relative_to(folder).parts
            if parts[0] == APP_DIR:
                if len(parts) > 1 and (parts[1] in EXCLUDED_APP or parts[1:3] == ('tests', 'runs')):
                    continue
                yield path
            elif path.suffix in ITEM_SUFFIXES:
                yield path

    def current(self):
        out = {}
        for path in self._files():
            data = path.read_bytes()
            digest = sha256_bytes(data)
            obj = self.root / 'objects' / digest[:2] / digest
            if not obj.exists():
                atomic_write_bytes(obj, data)
            out[path.relative_to(self.work.folder).as_posix()] = digest
        return out

    def list(self):
        folder = self.root / 'snapshots'
        out = []
        if folder.is_dir():
            for path in sorted(folder.glob('*.json'), reverse=True):
                doc = read_json(path)
                out.append(
                    {
                        'id': path.stem,
                        **{k: v for k, v in doc.items() if k != 'files'},
                        'file_count': len(doc.get('files', {})),
                    }
                )
        return out

    def get(self, snapshot_id):
        if not SNAPSHOT_ID.fullmatch(str(snapshot_id or '')):
            raise AppError(Msg('server.snapshots.missing', 'This snapshot does not exist.'), 404)
        doc = read_json(self.root / 'snapshots' / f'{snapshot_id}.json')
        if doc is None:
            raise AppError(Msg('server.snapshots.missing', 'This snapshot does not exist.'), 404)
        return doc

    def create(self, reason='manual', label=None, force=False):
        files = self.current()
        latest = self.list()
        if latest and not force and self.get(latest[0]['id']).get('files') == files:
            return None
        # Milliseconds keep snapshots made within one second in order (ids sort by time; older ids lack them).
        now = datetime.now().astimezone()
        snapshot_id = f'{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}-{secrets.token_hex(2)}'
        doc = {
            'schema_version': 1,
            'parent': latest[0]['id'] if latest else None,
            'created_at': now_iso(),
            'reason': reason,
            'label': label,
            'release': None,
            'files': files,
        }
        write_json(self.root / 'snapshots' / f'{snapshot_id}.json', doc)
        return {'id': snapshot_id, **doc}

    def diff(self, snapshot_id, against='current'):
        old = self.get(snapshot_id)['files']
        if against == 'current':
            new = self.current()
        elif against == 'parent':
            parent = self.get(snapshot_id).get('parent')
            new, old = old, (self.get(parent)['files'] if parent else {})
        else:
            new = self.get(against)['files']
        changes = []
        for path in sorted(set(old) | set(new)):
            if path not in old:
                changes.append({'path': path, 'change': 'added'})
            elif path not in new:
                changes.append({'path': path, 'change': 'deleted'})
            elif old[path] != new[path]:
                changes.append({'path': path, 'change': 'modified'})
        return changes

    def file_text(self, snapshot_id, path):
        digest = self.get(snapshot_id)['files'].get(path)
        if not digest:
            return None
        return self._object(digest).read_bytes().decode('utf-8', errors='replace')

    def restore(self, snapshot_id, paths=None):
        target = self.get(snapshot_id)['files']
        # Check everything first: a bad path or digest stops the restore before any file is written.
        for path, digest in target.items():
            self.path_in_work(path)
            self._object(digest)
        for path in paths or ():
            self.path_in_work(path)
        self.create('before_restore', force=True)
        current = self.current()
        chosen = paths or sorted(set(target) | set(current))
        restored = []
        for path in chosen:
            dest = self.path_in_work(path)
            if path in target:
                data = self._object(target[path]).read_bytes()
                atomic_write_bytes(dest, data)
                restored.append(path)
            elif path in current and not paths:
                # Items created after the snapshot go to the trash; app files are simply removed.
                if path.startswith(APP_DIR):
                    dest.unlink()
                else:
                    self.work.delete(path)
        return restored

    def mark_release(self, snapshot_id, note):
        path = self.root / 'snapshots' / f'{snapshot_id}.json'
        doc = self.get(snapshot_id)
        doc['release'] = {'note': note, 'at': now_iso()} if note else None
        write_json(path, doc)
        return doc

    # --- automatic save points and pruning (09-snapshots: 만드는 때, 정리) ------------------------------------------
    def save_point(self, interval_minutes, force=False):
        """A `save` snapshot when there are saved changes and the last one is older than the interval."""
        saves = [s for s in self.list() if s.get('reason') == 'save']
        if saves and not force:
            last = datetime.fromisoformat(saves[0]['created_at'])
            if datetime.now().astimezone() - last < timedelta(minutes=interval_minutes or 10):
                return None
        return self.create('save')

    def prune(self, keep_recent=200, daily_days=30):
        """Drop old `save` snapshots: keep the newest ones, then one a day for some days. Others are never pruned."""
        snaps = self.list()
        saves = [s for s in snaps if s.get('reason') == 'save' and not s.get('release')]
        cutoff = datetime.now().astimezone() - timedelta(days=daily_days)
        days, remove = set(), []
        for snap in saves[keep_recent:]:
            created = datetime.fromisoformat(snap['created_at'])
            if created < cutoff or created.date() in days:
                remove.append(snap['id'])
            else:
                days.add(created.date())
        if not remove:
            return 0
        removed = set(remove)
        parent_of = {s['id']: s.get('parent') for s in snaps}

        def surviving(parent):
            while parent in removed:
                parent = parent_of.get(parent)
            return parent

        folder = self.root / 'snapshots'
        for snap in snaps:
            if snap['id'] in removed:
                (folder / f'{snap["id"]}.json').unlink(missing_ok=True)
            elif snap.get('parent') in removed:
                doc = self.get(snap['id'])
                doc['parent'] = surviving(snap['parent'])
                write_json(folder / f'{snap["id"]}.json', doc)
        # Objects nobody points to any more go too.
        used = set()
        for path in folder.glob('*.json'):
            used.update((read_json(path) or {}).get('files', {}).values())
        for obj in (self.root / 'objects').glob('*/*'):
            if obj.name not in used:
                obj.unlink(missing_ok=True)
        return len(remove)
