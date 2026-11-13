"""Detach update-owned temporary files cheaply; remove them only after the new app is ready."""

import logging
import re
import threading
import uuid
from pathlib import Path

from .fsutil import read_json, write_json

logger = logging.getLogger(__name__)
IDENT = re.compile(r'[0-9a-f]{32}')
PACKAGE = re.compile(r'AtelierX-\d+\.\d+\.\d+-windows-x64\.zip')


def owned_path(folder, *parts):
    """Do not traverse a redirected cleanup root (including Windows junctions)."""
    target = folder.joinpath(*parts)
    if not target.resolve().is_relative_to(folder.resolve()):
        raise OSError('Update cleanup path leaves its directory')
    current = target
    while current != folder:
        if current.is_symlink() or current.is_junction():
            raise OSError('Update cleanup root is a link')
        current = current.parent
    return target


def stage_cleanup(folder, pending, result):
    """Journal before renaming. A crash resumes the same task before another update can reuse `new`."""
    ident = pending.get('cleanup_id')
    if not isinstance(ident, str) or not IDENT.fullmatch(ident):
        ident = uuid.uuid4().hex
        pending = {**pending, 'cleanup_id': ident, 'result': result}
        write_json(folder / 'pending.json', pending)
    task = owned_path(folder, 'cleanup', ident)
    task.mkdir(parents=True, exist_ok=True)
    manifest = task / 'manifest.json'
    doc = read_json(manifest)
    if not doc:
        backup = result.get('backup_id')
        doc = {
            'schema_version': 1,
            'state': 'staging',
            'backup_id': backup if isinstance(backup, str) and IDENT.fullmatch(backup) else None,
            'temporary': [p.name for p in folder.iterdir() if p.name == 'new' or PACKAGE.fullmatch(p.name)],
        }
        write_json(manifest, doc)
    if not isinstance(doc, dict) or doc.get('schema_version') != 1:
        raise ValueError('Invalid update cleanup manifest')
    for name in doc['temporary']:
        if name != 'new' and not PACKAGE.fullmatch(name):
            raise OSError('Invalid update temporary entry')
        source = owned_path(folder, name)
        target = owned_path(folder, 'cleanup', ident, 'temporary', name)
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise OSError('Update cleanup destination already exists')
            source.rename(target)
    write_json(manifest, {**doc, 'state': 'queued'})


class CleanupStopped(Exception):
    pass


def remove_tree(path, stop):
    """Cancel between entries; leave the journal until the entire task is gone. Never follow links."""
    if stop.is_set():
        raise CleanupStopped
    if path.is_symlink():
        path.unlink()
    elif path.is_junction():
        path.rmdir()
    elif path.is_dir():
        for child in path.iterdir():
            remove_tree(child, stop)
        path.rmdir()
    else:
        path.unlink(missing_ok=True)


class UpdateCleanup:
    def __init__(self, paths):
        self.folder = Path(paths.state) / 'update'
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.failed = False

    def tasks(self):
        folder = owned_path(self.folder, 'cleanup')
        return [p for p in folder.glob('*/manifest.json') if IDENT.fullmatch(p.parent.name)]

    def status(self):
        try:
            tasks = self.tasks()
            docs = [read_json(p) for p in tasks]
            incomplete = any(
                not isinstance(doc, dict)
                or doc.get('schema_version') != 1
                or doc.get('state') not in ('queued', 'failed')
                for doc in docs
            )
        except (OSError, ValueError, TypeError):
            return {'state': 'failed'}
        if self.thread and self.thread.is_alive():
            return {'state': 'running'}
        return {'state': 'failed' if self.failed or incomplete else 'queued' if tasks else 'done'}

    def start(self):
        with self.lock:
            if self.stop_event.is_set() or (self.thread and self.thread.is_alive()):
                return
            self.thread = threading.Thread(target=self.run, name='update-cleanup', daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stop_event.set()
            thread = self.thread
        if thread:
            thread.join()

    def run(self):
        self.failed = False
        try:
            for manifest in self.tasks():
                if self.stop_event.is_set():
                    return
                try:
                    task = owned_path(self.folder, 'cleanup', manifest.parent.name)
                    doc = read_json(manifest) or {}
                    if not isinstance(doc, dict):
                        raise TypeError('Invalid update cleanup manifest')
                    if doc.get('schema_version') != 1 or doc.get('state') not in ('queued', 'failed'):
                        continue
                    backup = doc.get('backup_id')
                    if backup is not None:
                        if not isinstance(backup, str) or not IDENT.fullmatch(backup):
                            raise OSError('Invalid update backup ID')
                        remove_tree(owned_path(self.folder, 'backups', backup), self.stop_event)
                    remove_tree(owned_path(task, 'temporary'), self.stop_event)
                    manifest.unlink()
                    task.rmdir()
                except CleanupStopped:
                    return
                except (OSError, ValueError, TypeError):
                    self.failed = True
                    logger.warning('Update cleanup will retry on next start: %s', manifest, exc_info=True)
        except (OSError, ValueError, TypeError):
            self.failed = True
            logger.warning('Cannot read pending update cleanup', exc_info=True)
