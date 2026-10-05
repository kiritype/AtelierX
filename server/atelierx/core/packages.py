"""Work and settings packages (#46, #47): one ZIP file to move works or the app's settings to another PC or keep as a
backup. Not the platform export (02-editor: 내보내기), which writes the chatbot's files for a platform.

Layout of a package::

    atelierx-package.json            kind (works | settings), app version, options, contents
    works/<n>/work/…                 a work folder (with its .atelierx app data, the history only when asked)
    works/<n>/output/…               its images under the output root (adopted only, all, or none)
    works/<n>/reviews.json           review results and adoptions of those images
    works/<n>/lora/<file>            LoRA files its characters refer to (when asked)
    settings/<area>/…                settings files by area (settings package)

Credentials never go in a works package. A settings package holds the vault only when asked, still encrypted with the
exporting app's master password.
"""

import copy
import json
import re
import secrets
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from .. import __version__
from .fsutil import read_json, write_json
from .i18n import AppError, Msg
from .vault import Vault
from .works import APP_DIR, Work

MANIFEST = 'atelierx-package.json'
FORMAT = 'atelierx-package'
IMAGE_CHOICES = ('adopted', 'all', 'none')
TOKEN = re.compile(r'^[0-9a-f]{32}$')
KEEP_UPLOADS_SECONDS = 24 * 3600
# Settings areas: (root attribute of AppPaths, path inside it, folder?)
SETTINGS = {
    'settings': ('config', 'settings.json', False),
    'platforms': ('data', 'platforms', True),
    'guidelines': ('data', 'guidelines', True),
    'providers': ('data', 'providers.json', False),
    'personas': ('data', 'personas.json', False),
    'image_library': (
        'data',
        'image',
        'files',
    ),  # the global library files, not the presets or tool data below
    'image_presets': ('data', 'image/presets', True),
    'image_review': ('config', 'image/review.json', False),
    'image_tags': ('config', 'image/tags.json', False),
    'vault': ('config', 'vault.json', False),
}


def _bad_package():
    return AppError(Msg('server.package.bad', 'This file is not an AtelierX package.'), 400)


def _safe_member(name):
    """A ZIP member name that stays inside where it is extracted."""
    if '\\' in name or name.startswith('/') or ':' in name:
        raise _bad_package()
    parts = PurePosixPath(name).parts
    if not parts or any(p in ('', '.', '..') for p in parts):
        raise _bad_package()
    return parts


def _write_member(archive, name, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(name) as source, target.open('wb') as out:
        shutil.copyfileobj(source, out, 1024 * 1024)


def _remap(value, old, new):
    """Point output-relative paths and work IDs of a work at its new ID."""
    if isinstance(value, dict):
        return {k: (new if k == 'work_id' and v == old else _remap(v, old, new)) for k, v in value.items()}
    if isinstance(value, list):
        return [_remap(v, old, new) for v in value]
    if isinstance(value, str) and value.startswith(f'{old}/'):
        return new + value[len(old) :]
    return value


class Packages:
    def __init__(self, paths, works, image, vault):
        self.paths, self.works, self.image, self.vault = paths, works, image, vault
        self.folder = Path(paths.state) / 'packages'

    # --- temporary files --------------------------------------------------------------------------------------------
    def _temp(self, suffix='.zip'):
        self.folder.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for old in self.folder.glob('*'):
            if old.is_file() and now - old.stat().st_mtime > KEEP_UPLOADS_SECONDS:
                old.unlink(missing_ok=True)
        token = secrets.token_hex(16)
        return token, self.folder / f'{token}{suffix}'

    def _upload(self, token):
        if not TOKEN.match(str(token or '')):
            raise _bad_package()
        path = self.folder / f'{token}.zip'
        if not path.is_file():
            raise AppError(
                Msg('server.package.expired', 'The uploaded package is gone. Choose the file again.'), 404
            )
        return path

    def new_upload(self):
        """``(token, path)`` for an uploaded package to be written to."""
        return self._temp()

    # --- works: what goes in ----------------------------------------------------------------------------------------
    def _lora_dir(self):
        values = read_json(Path(self.paths.config) / 'image' / 'training.json') or {}
        folder = values.get('lora_dir')
        return Path(folder) if folder and Path(folder).is_dir() else None

    def _work_files(self, work, options):
        """``[(archive name, source path)]`` of one work, and its review subset."""
        files = []
        skip = {'trash'} if options.get('history') else {'trash', 'history'}
        for path in sorted(work.folder.rglob('*')):
            rel = path.relative_to(work.folder)
            if not path.is_file() or (
                rel.parts[0] == APP_DIR and len(rel.parts) > 1 and rel.parts[1] in skip
            ):
                continue
            files.append((f'work/{rel.as_posix()}', path))
        output = Path(self.paths.output)
        choice = options.get('images', 'adopted')
        with self.image.reviews.lock:
            state = copy.deepcopy(self.image.reviews.state)
        mine = {
            key: pointer
            for key, pointer in (state.get('adopted') or {}).items()
            if str(pointer.get('path', '')).startswith(f'{work.id}/')
        }
        images = set()
        if choice == 'all' and (output / work.id).is_dir():
            for path in sorted((output / work.id).rglob('*')):
                if path.is_file():
                    images.add(path.relative_to(output).as_posix())
        elif choice == 'adopted':
            for pointer in mine.values():
                for rel in (pointer['path'], str(PurePosixPath(pointer['path']).with_suffix('.json'))):
                    if (output / rel).is_file():
                        images.add(rel)
        files += [(f'output/{rel}', output / rel) for rel in sorted(images)]
        reviews = {
            'records': {k: v for k, v in (state.get('records') or {}).items() if v.get('path') in images},
            'adopted': {k: v for k, v in mine.items() if v['path'] in images},
        }
        if options.get('lora'):
            lora_dir = self._lora_dir()
            names = set()
            for path in (work.app / 'image' / 'characters').glob('*/lora/**/*.json'):
                _lora_refs(read_json(path), names)
            for name in sorted(names):
                if lora_dir and (lora_dir / name).is_file():
                    files.append((f'lora/{name}', lora_dir / name))
        return files, reviews

    def plan_works(self, ids, options):
        options = _work_options(options)
        out = []
        for work_id in ids or []:
            work = self.works.get(work_id)
            files, _ = self._work_files(work, options)
            out.append(
                {
                    'id': work.id,
                    'name': work.name,
                    'files': len(files),
                    'bytes': sum(p.stat().st_size for _, p in files),
                    'images': sum(1 for n, _ in files if n.startswith('output/') and not n.endswith('.json')),
                    'loras': sum(1 for n, _ in files if n.startswith('lora/')),
                }
            )
        if not out:
            raise AppError(Msg('server.package.no_works', 'Choose the works to pack.'), 400)
        return {
            'works': out,
            'files': sum(w['files'] for w in out),
            'bytes': sum(w['bytes'] for w in out),
        }

    def export_works(self, ids, options):
        options = _work_options(options)
        plan = self.plan_works(ids, options)
        _, path = self._temp()
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for n, work_id in enumerate(ids):
                work = self.works.get(work_id)
                files, reviews = self._work_files(work, options)
                for name, source in files:
                    archive.write(source, f'works/{n}/{name}')
                archive.writestr(f'works/{n}/reviews.json', json.dumps(reviews, ensure_ascii=False))
            archive.writestr(
                MANIFEST,
                json.dumps(
                    {
                        'format': FORMAT,
                        'schema_version': 1,
                        'kind': 'works',
                        'app_version': __version__,
                        'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                        'options': options,
                        'works': plan['works'],
                    },
                    ensure_ascii=False,
                    indent=1,
                ),
            )
        return path

    # --- reading a package ------------------------------------------------------------------------------------------
    def _manifest(self, archive):
        try:
            doc = json.loads(archive.read(MANIFEST))
        except (KeyError, ValueError):
            raise _bad_package() from None
        if doc.get('format') != FORMAT or doc.get('kind') not in ('works', 'settings'):
            raise _bad_package()
        for name in archive.namelist():
            _safe_member(name)
        return doc

    def inspect(self, token):
        path = self._upload(token)
        try:
            with zipfile.ZipFile(path) as archive:
                doc = self._manifest(archive)
                names = archive.namelist()
        except zipfile.BadZipFile:
            raise _bad_package() from None
        out = {
            'token': token,
            'kind': doc['kind'],
            'app_version': doc.get('app_version'),
            'created_at': doc.get('created_at'),
        }
        if doc['kind'] == 'works':
            existing = {w.doc().get('id', '').lower() for w in self.works.all()}
            out['works'] = [
                {
                    **{k: w.get(k) for k in ('id', 'name', 'files', 'bytes', 'images', 'loras')},
                    'index': n,
                    'id_taken': str(w.get('id', '')).lower() in existing,
                    'name_taken': (self.paths.works / str(w.get('name', ''))).exists(),
                }
                for n, w in enumerate(doc.get('works') or [])
            ]
            out['options'] = doc.get('options') or {}
        else:
            present = {
                name.split('/')[1] for name in names if name.startswith('settings/') and name.count('/') >= 2
            }
            out['areas'] = [
                {'area': area, 'exists': _exists(self.paths, area)} for area in SETTINGS if area in present
            ]
        return out

    # --- works: bringing them in ------------------------------------------------------------------------------------
    def import_works(self, token, choices):
        """Bring in the chosen works. A work whose ID is taken comes in under a new ID; its image paths, records and
        reviews follow. Nothing already here is overwritten."""
        path = self._upload(token)
        chosen = {int(c['index']) for c in choices or [] if isinstance(c, dict) and c.get('import', True)}
        imported, skipped_loras = [], []
        with zipfile.ZipFile(path) as archive:
            doc = self._manifest(archive)
            if doc['kind'] != 'works':
                raise _bad_package()
            names = archive.namelist()
            for n, entry in enumerate(doc.get('works') or []):
                if n not in chosen:
                    continue
                result = self._import_one(archive, names, n, entry, skipped_loras)
                imported.append(result)
        path.unlink(missing_ok=True)
        if imported:
            self.image.gallery.scan(force=True)
        return {'imported': imported, 'skipped_loras': skipped_loras}

    def _import_one(self, archive, names, n, entry, skipped_loras):
        prefix = f'works/{n}/'
        old_id = str(entry.get('id') or '')
        taken = {w.doc().get('id', '').lower() for w in self.works.all()}
        new_id = self.works.suggest_id() if old_id.lower() in taken or not old_id else old_id
        base = str(entry.get('name') or new_id)
        name, k = base, 2
        while (self.paths.works / name).exists():
            name, k = f'{base} ({k})', k + 1
        folder = self.paths.works / name
        output = Path(self.paths.output)
        lora_dir = self._lora_dir()
        try:
            for member in names:
                if not member.startswith(prefix) or member.endswith('/'):
                    continue
                parts = _safe_member(member)[2:]
                if parts[0] == 'work':
                    _write_member(archive, member, folder.joinpath(*parts[1:]))
                elif parts[0] == 'output':
                    rel = PurePosixPath(*parts[1:])
                    rel = PurePosixPath(new_id, *rel.parts[1:]) if rel.parts[0] == old_id else rel
                    target = output.joinpath(*rel.parts)
                    if target.exists():
                        continue  # never overwrite an image already here
                    if target.suffix == '.json':
                        record = json.loads(archive.read(member))
                        target.parent.mkdir(parents=True, exist_ok=True)
                        write_json(target, _remap(record, old_id, new_id))
                    else:
                        _write_member(archive, member, target)
                elif parts[0] == 'lora' and len(parts) == 2:
                    if lora_dir is None or (lora_dir / parts[1]).exists():
                        skipped_loras.append(parts[1])
                    else:
                        _write_member(archive, member, lora_dir / parts[1])
            if not (folder / APP_DIR / 'work.json').is_file():
                raise _bad_package()
            work = Work(folder)
            if new_id != old_id:
                work.update_doc({'id': new_id})
                for path in (folder / APP_DIR).rglob('*.json'):
                    if path.name == 'work.json':
                        continue
                    data = read_json(path)
                    if data is not None:
                        changed = _remap(data, old_id, new_id)
                        if changed != data:
                            write_json(path, changed)
            self._merge_reviews(archive, prefix, old_id, new_id)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)  # the folder was made here under a fresh name
            raise
        return {'id': new_id, 'name': name, 'renumbered': new_id != old_id}

    def _merge_reviews(self, archive, prefix, old_id, new_id):
        try:
            reviews = json.loads(archive.read(f'{prefix}reviews.json'))
        except KeyError:
            return
        store = self.image.reviews
        with store.lock:
            state = copy.deepcopy(store.state)
            for value in (reviews.get('records') or {}).values():
                value = _remap(value, old_id, new_id)
                if value.get('path') and value.get('sha256'):
                    state['records'].setdefault(value['path'] + '\0' + value['sha256'], value)
            for key, pointer in (reviews.get('adopted') or {}).items():
                combo = json.loads(key)
                if combo and combo[0] == old_id:
                    combo[0] = new_id
                state['adopted'].setdefault(
                    json.dumps(combo, ensure_ascii=False, separators=(',', ':')),
                    _remap(pointer, old_id, new_id),
                )
            store._save(state)

    # --- settings ---------------------------------------------------------------------------------------------------
    def _area_files(self, area):
        root_name, inner, kind = SETTINGS[area]
        root = getattr(self.paths, root_name)
        target = root / inner
        if kind is True:
            return (
                [(p.relative_to(target).as_posix(), p) for p in sorted(target.rglob('*')) if p.is_file()]
                if target.is_dir()
                else []
            )
        if kind == 'files':
            return (
                [(p.name, p) for p in sorted(target.glob('*.json')) if p.is_file()] if target.is_dir() else []
            )
        return [(target.name, target)] if target.is_file() else []

    def export_settings(self, areas):
        areas = [a for a in areas or [] if a in SETTINGS]
        if not areas:
            raise AppError(Msg('server.package.no_areas', 'Choose what to pack.'), 400)
        _, path = self._temp()
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for area in areas:
                for rel, source in self._area_files(area):
                    archive.write(source, f'settings/{area}/{rel}')
            archive.writestr(
                MANIFEST,
                json.dumps(
                    {
                        'format': FORMAT,
                        'schema_version': 1,
                        'kind': 'settings',
                        'app_version': __version__,
                        'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                        'areas': areas,
                    },
                    ensure_ascii=False,
                    indent=1,
                ),
            )
        return path

    def import_settings(self, token, areas, vault_password=None):
        """Apply the chosen areas. What they replace is kept first in a backup ZIP under state/packages/backups/.
        Folders merge (same names replaced), files are replaced; the vault's entries are added to this app's vault."""
        path = self._upload(token)
        areas = [a for a in areas or [] if a in SETTINGS]
        with zipfile.ZipFile(path) as archive:
            doc = self._manifest(archive)
            if doc['kind'] != 'settings':
                raise _bad_package()
            names = [n for n in archive.namelist() if not n.endswith('/')]
            secrets_in = None
            if 'vault' in areas:
                secrets_in = self._open_vault(archive, vault_password)
            backup = self._backup([a for a in areas if a != 'vault'])
            applied = []
            for area in areas:
                if area == 'vault':
                    continue
                root_name, inner, kind = SETTINGS[area]
                target = getattr(self.paths, root_name) / inner
                members = [n for n in names if n.startswith(f'settings/{area}/')]
                for member in members:
                    rel = _safe_member(member)[2:]
                    if kind is True or kind == 'files':
                        if kind == 'files' and len(rel) != 1:
                            continue
                        _write_member(archive, member, target.joinpath(*rel))
                    else:
                        _write_member(archive, member, target)
                if members:
                    applied.append(area)
            if secrets_in is not None:
                for name, item in sorted(secrets_in.items()):
                    self.vault.put(
                        name, item.get('kind', 'other'), item.get('value', ''), item.get('note', '')
                    )
                applied.append('vault')
        path.unlink(missing_ok=True)
        return {'applied': applied, 'backup': backup.name if backup else None}

    def _open_vault(self, archive, password):
        try:
            data = archive.read('settings/vault/vault.json')
        except KeyError:
            raise AppError(Msg('server.package.no_vault', 'This package has no credentials.'), 400) from None
        _, temp = self._temp('.vault.json')
        try:
            temp.write_bytes(data)
            other = Vault(temp)
            other.unlock(str(password or ''))  # the exporting app's master password
            return copy.deepcopy(other._secrets)
        except AppError as error:
            if error.msg.key == 'server.vault.wrong_password':
                raise AppError(
                    Msg(
                        'server.package.vault_password',
                        'Enter the master password of the app that made this package.',
                    ),
                    401,
                ) from None
            raise
        finally:
            temp.unlink(missing_ok=True)

    def _backup(self, areas):
        files = [(f'{area}/{rel}', source) for area in areas for rel, source in self._area_files(area)]
        if not files:
            return None
        folder = self.folder / 'backups'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'settings-{datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")}.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, source in files:
                archive.write(source, name)
        return target


def _work_options(options):
    options = options if isinstance(options, dict) else {}
    images = options.get('images', 'adopted')
    return {
        'history': bool(options.get('history')),
        'images': images if images in IMAGE_CHOICES else 'adopted',
        'lora': bool(options.get('lora')),
    }


def _lora_refs(value, names):
    if isinstance(value, dict):
        if value.get('root') == 'lora' and isinstance(value.get('path'), str):
            name = PurePosixPath(value['path']).name
            if name and name == value['path']:
                names.add(name)
        for v in value.values():
            _lora_refs(v, names)
    elif isinstance(value, list):
        for v in value:
            _lora_refs(v, names)


def _exists(paths, area):
    root_name, inner, kind = SETTINGS[area]
    target = getattr(paths, root_name) / inner
    if kind is True:
        return target.is_dir() and any(target.rglob('*'))
    if kind == 'files':
        return target.is_dir() and any(target.glob('*.json'))
    return target.is_file()


def download_name(kind, ids=None):
    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M')
    if kind == 'settings':
        return f'AtelierX-settings-{stamp}.zip'
    label = ids[0] if ids and len(ids) == 1 else 'works'
    return f'AtelierX-{label}-{stamp}.zip'
