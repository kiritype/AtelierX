"""Output trash (21-gallery: 지우기). Deleting an image moves it, with its record, to ``<output>/.trash/``.

The gallery skips dot folders, so trashed images disappear from it but can be restored to where they were.
Only emptying the trash deletes files for good. Review results stay keyed by path and hash, so a restored
image comes back with its verdicts.
"""

import shutil
import threading
import uuid
from pathlib import Path, PurePosixPath

from ..core.i18n import Msg
from .util import atomic_json, now, read_json

MAX_BATCH = 1000


class OutputTrash:
    def __init__(self, paths, gallery, tools):
        self.root = Path(paths.output)
        self.folder = self.root / '.trash'
        self.index_path = self.folder / 'index.json'
        self.gallery, self.tools = gallery, tools
        self.lock = threading.RLock()

    def _entries(self):
        return (read_json(self.index_path) or {}).get('entries', [])

    def _save(self, entries):
        atomic_json(self.index_path, {'schema_version': 1, 'entries': entries})

    def list(self):
        with self.lock:
            entries = self._entries()
        out = []
        for entry in reversed(entries):
            image = f'.trash/{entry["id"]}/{PurePosixPath(entry["path"]).name}'
            out.append({**entry, 'image_url': self.gallery.url(image), 'trash_path': image})
        return {'entries': out}

    def delete(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_BATCH:
            raise ValueError(Msg('server.trash.choose', 'Choose 1 to 1,000 images.'))
        moved = []
        with self.lock:
            entries = self._entries()
            for relative in dict.fromkeys(paths):
                image = self.gallery.safe_path(relative)
                if not image.is_file():
                    continue
                entry = {'id': uuid.uuid4().hex[:12], 'path': relative, 'deleted_at': now(), 'files': []}
                target = self.folder / entry['id']
                target.mkdir(parents=True, exist_ok=True)
                # The image and everything named after it (its record) go together.
                for file in (image, image.with_suffix('.json')):
                    if file.is_file():
                        shutil.move(str(file), str(target / file.name))
                        entry['files'].append(file.name)
                entries.append(entry)
                moved.append(relative)
            self._save(entries)
        if moved:
            gone = [
                i['id']
                for i in self.tools.public()['items']
                if i['source'] == 'gallery' and i['path'] in moved
            ]
            if gone:
                self.tools.remove(gone)
            self.gallery.scan(force=True)
        return {'deleted': len(moved)}

    def restore(self, ids):
        restored = []
        with self.lock:
            entries = self._entries()
            keep = []
            for entry in entries:
                if entry['id'] not in (ids or []):
                    keep.append(entry)
                    continue
                destination = self.gallery.safe_path(entry['path'])
                stem, suffix = destination.stem, destination.suffix
                # Something new took the old name: come back beside it instead of replacing it.
                index = 2
                while destination.exists() or destination.with_suffix('.json').exists():
                    destination = destination.with_name(
                        f'{stem}_restored{index if index > 2 else ""}{suffix}'
                    )
                    index += 1
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = self.folder / entry['id']
                for name in entry['files']:
                    target = destination if name.endswith(suffix) else destination.with_suffix('.json')
                    if (source / name).is_file():
                        shutil.move(str(source / name), str(target))
                shutil.rmtree(source, ignore_errors=True)
                restored.append(destination.relative_to(self.root).as_posix())
            self._save(keep)
        self.gallery.scan(force=True)
        return {'restored': restored}

    def purge(self, ids=None):
        """Delete for good: the given entries, or everything when ``ids`` is None."""
        with self.lock:
            entries = self._entries()
            doomed = [e for e in entries if ids is None or e['id'] in ids]
            for entry in doomed:
                shutil.rmtree(self.folder / entry['id'], ignore_errors=True)
            self._save([e for e in entries if e not in doomed])
        return {'purged': len(doomed)}
