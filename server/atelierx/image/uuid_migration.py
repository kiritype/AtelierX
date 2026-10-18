"""One-time, recoverable UUID conversion of image library and style preset IDs.

Only known structured references are changed. Image file paths and image bytes are
historical artifacts and stay in place; their JSON sidecars carry the new IDs.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from copy import deepcopy
from functools import lru_cache
from pathlib import Path, PurePosixPath

from ..core.works import WorkStore
from . import library
from .util import atomic_json

MAP_NAME = 'uuid-map.json'
JOURNAL_NAME = 'journal.json'
DEFAULT_NAMESPACE = uuid.UUID('49b40af4-7a73-548b-a7d2-737c7d09d84a')


def _uuid(value):
    try:
        return str(uuid.UUID(value)) == value.lower()
    except (AttributeError, TypeError, ValueError):
        return False


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'Cannot migrate malformed image data: {path}') from exc


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _map_path(paths):
    return paths.data / 'image' / MAP_NAME


def mapping(paths):
    path = _map_path(paths)
    if not path.exists():
        return {'schema_version': 1, 'library': {}, 'presets': {}}
    stat = path.stat()
    doc = _cached_map(str(path), stat.st_mtime_ns, stat.st_size)
    if (
        not isinstance(doc, dict)
        or doc.get('schema_version') != 1
        or not isinstance(doc.get('library'), dict)
        or not isinstance(doc.get('presets'), dict)
    ):
        raise ValueError(f'Cannot migrate invalid UUID map: {path}')
    owners = {}
    for table_name in ('library', 'presets'):
        for key, ident in doc[table_name].items():
            if not isinstance(key, str) or not _uuid(ident):
                raise ValueError(f'Cannot migrate invalid UUID map entry: {path}')
            if table_name == 'library':
                parts = key.split('/')
                if (
                    parts[0] not in library.KINDS
                    or len(parts) not in (3, 4)
                    or (len(parts) == 3 and parts[1] != 'global')
                    or (len(parts) == 4 and parts[1] != 'work')
                ):
                    raise ValueError(f'Cannot migrate invalid UUID map key: {path}')
            owner = owners.setdefault(ident, (table_name, key))
            if owner != (table_name, key):
                prior = owner[1]
                same_item = (
                    table_name == owner[0] == 'library'
                    and key.split('/')[0] == prior.split('/')[0]
                    and key.split('/')[-1] == prior.split('/')[-1]
                    and {'global', 'work'} == {key.split('/')[1], prior.split('/')[1]}
                )
                if not same_item:
                    raise ValueError(f'Cannot migrate colliding UUID map entries: {path}')
    return deepcopy(doc)


@lru_cache(maxsize=16)
def _cached_map(path, _mtime, _size):
    return _read(Path(path))


def resolve(paths, kind, ident, work_id=None):
    """Resolve a legacy import or a historical reference without conflating works."""
    if not isinstance(ident, str):
        return ident
    doc = mapping(paths)
    if kind == 'presets':
        return doc['presets'].get(ident, ident)
    keys = doc['library']
    return keys.get(f'{kind}/work/{work_id}/{ident}', keys.get(f'{kind}/global/{ident}', ident))


def preset_common(paths, ident):
    """A global preset may historically select one work-only common prompt."""
    if _uuid(ident):
        return ident
    doc = mapping(paths)['library']
    global_id = doc.get(f'common/global/{ident}')
    if global_id:
        return global_id
    matches = {
        value for key, value in doc.items() if key.startswith('common/work/') and key.endswith('/' + ident)
    }
    if len(matches) == 1:
        return matches.pop()
    if len(matches) > 1:
        raise ValueError(
            f'Preset common prompt {ident} differs between works; choose it in the work instead.'
        )
    return canonical_for_save(paths, 'common', ident)


@library.locked
def canonical_for_save(paths, kind, ident, scope='global', work_id=None):
    """Normalize a legacy API/import ID once, before it enters an active file."""
    if not isinstance(ident, str) or not library.ITEM_ID.fullmatch(ident):
        raise ValueError(f'Invalid image library ID: {ident}')
    if _uuid(ident):
        return ident
    doc = mapping(paths)
    if kind == 'presets':
        table = doc['presets']
        key = ident
        existing = table.get(key)
    else:
        table = doc['library']
        key = f'{kind}/work/{work_id}/{ident}' if scope == 'work' else f'{kind}/global/{ident}'
        existing = table.get(key) or (table.get(f'{kind}/global/{ident}') if scope == 'work' else None)
    if existing is None:
        used = set(doc['presets'].values()) | set(doc['library'].values())
        existing = _default_uuid(paths, kind, ident) if kind != 'presets' and scope == 'global' else None
        existing = existing or _new_id(used)
    if table.get(key) != existing:
        table[key] = existing
        atomic_json(_map_path(paths), doc)
    return existing


def _new_id(used):
    while True:
        ident = str(uuid.uuid4())
        if ident not in used:
            used.add(ident)
            return ident


def _default_uuid(paths, kind, ident):
    path = paths.defaults / 'image' / f'{kind}.json'
    if not path.is_file():
        return None
    defaults = _read(path)
    if ident in (defaults.get('items') or {}):
        return str(uuid.uuid5(DEFAULT_NAMESPACE, f'image-library/{kind}/{ident}'))
    return None


def _journal_dir(paths):
    return paths.state / 'image' / 'uuid-migration'


def recover(paths):
    """An interrupted commit is rolled back before the app exposes its data."""
    journal = _journal_dir(paths) / JOURNAL_NAME
    if not journal.exists():
        return
    doc = _read(journal)
    if (
        not isinstance(doc, dict)
        or not isinstance(doc.get('backup'), str)
        or len(doc['backup']) != 32
        or any(c not in '0123456789abcdef' for c in doc['backup'])
        or not isinstance(doc.get('files'), list)
    ):
        raise ValueError(f'UUID migration journal is invalid: {journal}')
    backup = _journal_dir(paths) / doc['backup']
    checked = []
    for entry in doc['files']:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise ValueError(f'UUID migration journal has an invalid path: {journal}')
        relative = PurePosixPath(entry['path'])
        if (
            not relative.parts
            or relative.is_absolute()
            or any(part in ('', '.', '..') for part in relative.parts)
            or ':' in entry['path']
            or '\\' in entry['path']
        ):
            raise ValueError(f'UUID migration journal has an unsafe path: {journal}')
        target = paths.root.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(paths.root.resolve()) or target.is_symlink():
            raise ValueError(f'UUID migration journal has an unsafe target: {target}')
        if entry['existed']:
            saved = backup.joinpath(*relative.parts)
            if (
                not saved.is_file()
                or saved.is_symlink()
                or hashlib.sha256(saved.read_bytes()).hexdigest() != entry.get('sha256')
            ):
                raise ValueError(f'UUID migration backup is missing: {saved}')
        checked.append((entry, target, saved if entry['existed'] else None))
    for entry, target, saved in checked:
        if entry['existed']:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.uuid-restore')
            shutil.copy2(saved, temp)
            os.replace(temp, target)
        else:
            target.unlink(missing_ok=True)
    journal.unlink()


def _rewrite(value, ids, work_id):
    """Rewrite only typed image-reference fields, leaving prompts, names and paths alone."""
    if isinstance(value, list):
        return [_rewrite(item, ids, work_id) for item in value]
    if not isinstance(value, dict):
        return value
    scope = value.get('work_id', work_id)
    out = {}
    singular = {'expression_id': 'expressions', 'composition_id': 'compositions', 'preset_id': 'presets'}
    plural = {'common_ids': 'common'}
    for key, item in value.items():
        if key in singular and isinstance(item, str):
            out[key] = ids(singular[key], item, scope)
        elif key in plural and isinstance(item, list):
            out[key] = [ids(plural[key], one, scope) for one in item]
        elif (
            key == 'preset_preview'
            and isinstance(item, dict)
            or key == 'generation_preset'
            and isinstance(item, dict)
        ):
            out[key] = {**_rewrite(item, ids, scope), 'id': ids('presets', item.get('id'), scope)}
        elif key == 'combo' and isinstance(item, list) and len(item) == 4:
            out[key] = [*item[:3], ids('expressions', item[3], item[0])]
        else:
            out[key] = _rewrite(item, ids, scope)
    return out


def _plan(paths, works, current):
    changes = {}
    library_map = dict(current['library'])
    preset_map = dict(current['presets'])
    used = set(library_map.values()) | set(preset_map.values())
    sources = []
    for kind in library.KINDS:
        sources.append((kind, 'global', None, paths.data / 'image' / f'{kind}.json'))
        for work in works:
            sources.append((kind, 'work', work.id, work.app / 'image' / f'{kind}.json'))
    documents = []
    for kind, scope, wid, path in sources:
        if not path.is_file():
            continue
        doc = _read(path)
        if not isinstance(doc, dict) or not isinstance(doc.get('items'), dict):
            raise ValueError(f'Cannot migrate invalid library: {path}')
        documents.append((kind, scope, wid, path, doc))
        for old in doc['items']:
            if not isinstance(old, str) or not library.ITEM_ID.fullmatch(old):
                raise ValueError(f'Cannot migrate invalid item ID in {path}: {old}')
            if _uuid(old):
                used.add(old)
                continue
            key = f'{kind}/{scope}/{wid}/' if scope == 'work' else f'{kind}/global/'
            key += old
            if scope == 'work' and f'{kind}/global/{old}' in library_map:
                library_map[key] = library_map[f'{kind}/global/{old}']
            else:
                if key not in library_map:
                    library_map[key] = (
                        _default_uuid(paths, kind, old) if scope == 'global' else None
                    ) or _new_id(used)
            used.add(library_map[key])

    preset_folder = paths.data / 'image' / 'presets'
    preset_docs = []
    for path in sorted(preset_folder.glob('*.json')) if preset_folder.is_dir() else []:
        if not library.ITEM_ID.fullmatch(path.stem):
            raise ValueError(f'Cannot migrate invalid preset ID: {path}')
        doc = _read(path)
        if not isinstance(doc, dict):
            raise ValueError(f'Cannot migrate invalid preset: {path}')
        preset_docs.append((path, doc))
        if _uuid(path.stem):
            used.add(path.stem)
        else:
            preset_map.setdefault(path.stem, _new_id(used))
            used.add(preset_map[path.stem])

    planned_map = {'schema_version': 1, 'complete': True, 'library': library_map, 'presets': preset_map}

    def lookup(kind, ident, wid=None):
        if not isinstance(ident, str):
            return ident
        if kind == 'presets':
            return preset_map.get(ident, ident)
        return library_map.get(f'{kind}/work/{wid}/{ident}', library_map.get(f'{kind}/global/{ident}', ident))

    def preset_ref(ident):
        global_id = library_map.get(f'common/global/{ident}')
        if global_id:
            return global_id
        matches = {
            value
            for key, value in library_map.items()
            if key.startswith('common/work/') and key.endswith('/' + str(ident))
        }
        if len(matches) == 1:
            return matches.pop()
        if len(matches) > 1:
            raise ValueError(
                f'Preset common prompt {ident} differs between works; choose it in the work instead.'
            )
        return ident

    for kind, scope, wid, path, doc in documents:
        renamed = {}
        for old, item in doc['items'].items():
            new = lookup(kind, old, wid if scope == 'work' else None)
            if new in renamed:
                raise ValueError(f'UUID collision in {path}: {new}')
            if not isinstance(item, dict):
                raise ValueError(f'Cannot migrate invalid item in {path}: {old}')
            entry = dict(item)
            if kind == 'expressions' and isinstance(entry.get('composition'), str):
                entry['composition'] = lookup('compositions', entry['composition'], wid)
            renamed[new] = entry
        changes[path] = _bytes({**doc, 'schema_version': 2, 'items': renamed})

    for path, doc in preset_docs:
        new = preset_map.get(path.stem, path.stem)
        revised = {**doc, 'schema_version': 3, 'common': [preset_ref(one) for one in doc.get('common') or []]}
        preview = doc.get('preview')
        if isinstance(preview, dict) and isinstance(preview.get('hash'), str):
            from .settings import get as settings_get

            seed = settings_get(paths, 'presets')['preview_seed']
            if preview['hash'] == library.preview_hash(doc, seed):
                revised['preview'] = {**preview, 'hash': library.preview_hash(revised, seed)}
        changes[preset_folder / f'{new}.json'] = _bytes(revised)
        if new != path.stem:
            changes[path] = None
        preview = path.with_suffix('.webp')
        if preview.is_file() and new != path.stem:
            changes[preset_folder / f'{new}.webp'] = preview.read_bytes()
            changes[preview] = None

    for work in works:
        wid = work.id
        for path in (work.app / 'image' / 'characters').glob('*/design.json'):
            doc = _read(path)
            if not isinstance(doc, dict):
                raise ValueError(f'Cannot migrate invalid design: {path}')
            for outfit in (doc.get('outfits') or {}).values():
                for slot in (outfit.get('slots') or {}).values():
                    ref = slot.get('ref') if isinstance(slot, dict) else None
                    if isinstance(ref, str) and ref.startswith(('global:', 'work:')):
                        prefix, old = ref.split(':', 1)
                        slot['ref'] = (
                            prefix + ':' + lookup('outfits', old, None if prefix == 'global' else wid)
                        )
            changes[path] = _bytes(doc)
        board = work.app / 'image' / 'board.json'
        if board.is_file():
            doc = _read(board)
            if not isinstance(doc, dict):
                raise ValueError(f'Cannot migrate invalid board: {board}')
            for character in (doc.get('characters') or {}).values():
                if isinstance(character, dict):
                    character['excluded'] = [
                        f'{combo.split("/", 1)[0]}/{lookup("expressions", combo.split("/", 1)[1], wid)}'
                        if isinstance(combo, str) and '/' in combo
                        else combo
                        for combo in character.get('excluded') or []
                    ]
            changes[board] = _bytes(doc)
        for pattern in ('*/datasets/*.json', '*/lora/runs/*.json'):
            for path in (work.app / 'image' / 'characters').glob(pattern):
                doc = _read(path)
                if not isinstance(doc, dict):
                    raise ValueError(f'Cannot migrate invalid training record: {path}')
                changes[path] = _bytes(_rewrite(doc, lookup, wid))

    queue = paths.state / 'image' / 'queue.json'
    if queue.is_file():
        changes[queue] = _bytes(_rewrite(_read(queue), lookup, None))
    rounds = paths.state / 'image' / 'review_rounds.json'
    if rounds.is_file():
        changes[rounds] = _bytes(_rewrite(_read(rounds), lookup, None))
    reviews = paths.output / 'reviews.json'
    if reviews.is_file():
        doc = _read(reviews)
        if not isinstance(doc, dict):
            raise ValueError(f'Cannot migrate invalid reviews: {reviews}')
        adopted = {}
        for key, pointer in (doc.get('adopted') or {}).items():
            combo = json.loads(key)
            if isinstance(combo, list) and len(combo) == 4:
                combo[3] = lookup('expressions', combo[3], combo[0])
                key = json.dumps(combo, ensure_ascii=False, separators=(',', ':'))
            adopted[key] = pointer
        doc['adopted'] = adopted
        changes[reviews] = _bytes(_rewrite(doc, lookup, None))
    # Only JSON sidecars beside a known image are generation records. Other JSON
    # under output may belong to external tools or user files and stays untouched.
    if paths.output.is_dir():
        for image in paths.output.rglob('*'):
            if image.suffix.lower() not in ('.png', '.webp', '.jpg', '.jpeg') or image.is_symlink():
                continue
            path = image.with_suffix('.json')
            if path.is_file() and not path.is_symlink():
                try:
                    doc = _read(path)
                except ValueError:
                    continue  # The gallery already treats an unreadable sidecar as absent.
                if isinstance(doc, dict):
                    changes[path] = _bytes(_rewrite(doc, lookup, None))
    changes[_map_path(paths)] = _bytes(planned_map)
    changes = {
        path: data
        for path, data in changes.items()
        if (data is None and path.exists())
        or (data is not None and (not path.is_file() or path.read_bytes() != data))
    }
    return changes, planned_map


def _active_canonical(paths, works):
    """Cheap startup check for restored defaults or externally copied library files."""
    for kind in library.KINDS:
        for path in [
            paths.data / 'image' / f'{kind}.json',
            *(w.app / 'image' / f'{kind}.json' for w in works),
        ]:
            if path.is_file():
                doc = _read(path)
                if (
                    not isinstance(doc, dict)
                    or doc.get('schema_version') != 2
                    or not isinstance(doc.get('items'), dict)
                ):
                    return False
                if any(not _uuid(ident) for ident in doc['items']):
                    return False
    folder = paths.data / 'image' / 'presets'
    for path in folder.glob('*.json') if folder.is_dir() else ():
        if not _uuid(path.stem):
            return False
        doc = _read(path)
        if not isinstance(doc, dict) or doc.get('schema_version') != 3:
            return False
    return True


@library.locked
def migrate(paths, fail_at=None, *, force=False):
    """Convert one app root at startup; test-only ``fail_at`` probes recovery phases."""
    recover(paths)
    current = mapping(paths)
    works = WorkStore(paths).all()
    if current.get('complete') and not force and fail_at is None and _active_canonical(paths, works):
        return current
    changes, planned_map = _plan(paths, works, current)
    if not changes:
        return planned_map
    base = _journal_dir(paths)
    base.mkdir(parents=True, exist_ok=True)
    backup_name = uuid.uuid4().hex
    backup = base / backup_name
    files = []
    for path in changes:
        relative = path.relative_to(paths.root).as_posix()
        existed = path.is_file()
        entry = {'path': relative, 'existed': existed}
        files.append(entry)
        if existed:
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
            entry['sha256'] = hashlib.sha256(saved.read_bytes()).hexdigest()
    if fail_at == 'backup':
        raise RuntimeError('Injected UUID migration backup failure')
    journal = base / JOURNAL_NAME
    atomic_json(journal, {'schema_version': 1, 'backup': backup_name, 'files': files})
    if fail_at == 'journal':
        raise RuntimeError('Injected UUID migration journal failure')
    try:
        for index, (path, data) in enumerate(changes.items()):
            path.parent.mkdir(parents=True, exist_ok=True)
            if data is None:
                path.unlink(missing_ok=True)
            else:
                temp = path.with_name(path.name + '.uuid-write')
                temp.write_bytes(data)
                os.replace(temp, path)
            if fail_at == 'replace' and index == 0:
                raise RuntimeError('Injected UUID migration replace failure')
        if fail_at == 'cleanup':
            raise RuntimeError('Injected UUID migration cleanup failure')
    except Exception:
        recover(paths)
        raise
    journal.unlink()
    return planned_map


def migrate_runtime(runtime):
    """Normalize an imported/restored item while the API admission gate is closed."""
    with runtime.lock, runtime.gallery.lock, runtime.reviews.lock, runtime.rounds.lock:
        after = migrate(runtime.paths, force=True)
        runtime.queue.load()
        review_path = runtime.paths.output / 'reviews.json'
        if review_path.is_file():
            runtime.reviews.state = _read(review_path)
            runtime.reviews._recorded = runtime.reviews._recorded_paths(runtime.reviews.state)
        rounds_path = runtime.paths.state / 'image' / 'review_rounds.json'
        if rounds_path.is_file():
            runtime.rounds.rounds = _read(rounds_path).get('rounds') or []
        runtime.gallery._entries.clear()
        runtime.gallery._meta_cache.clear()
        runtime.gallery.scan(force=True)
    return after


def migrate_runtime_guarded(server):
    """A failed post-import conversion must never reopen requests onto mixed IDs."""
    try:
        return migrate_runtime(server.image)
    except BaseException:
        server.admission.seal()
        raise


class FileCheckpoint:
    """Exact pre-operation copy of known targets, including their absence."""

    def __init__(self, paths, targets):
        self.root = paths.root.resolve()
        self.folder = _journal_dir(paths) / 'operations' / uuid.uuid4().hex
        self.entries = []
        for target in dict.fromkeys(Path(path) for path in targets):
            target = target.resolve()
            if not target.is_relative_to(self.root) or target == self.root:
                raise ValueError(f'Unsafe UUID operation checkpoint: {target}')
            relative = target.relative_to(self.root)
            saved = self.folder / relative
            if target.is_dir():
                shutil.copytree(target, saved)
                kind = 'directory'
            elif target.is_file():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                kind = 'file'
            else:
                kind = 'missing'
            self.entries.append((target, saved, kind))

    def rollback(self):
        for target, saved, kind in reversed(self.entries):
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if kind == 'directory':
                shutil.copytree(saved, target)
            elif kind == 'file':
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, target)

    def close(self):
        if self.folder.exists():
            shutil.rmtree(self.folder)
