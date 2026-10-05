"""Works and their items (data-model: 작품 폴더, 항목, ID, 휴지통).

A work is a folder under ``data/works/`` that contains ``.atelierx/work.json``. Everything else in the folder is the
user's tree; ``.md`` and ``.jsx`` files in it are items whose kind lives in their metadata head.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import frontmatter
from .fsutil import atomic_write_text, read_json, sha256_text, write_json
from .i18n import AppError, Msg

APP_DIR = '.atelierx'
KINDS = ('main', 'start', 'lorebook', 'character', 'jsx', 'note')
KIND_PREFIX = {'main': 'M', 'start': 'S', 'lorebook': 'L', 'character': 'C', 'jsx': 'J'}
# Names used by earlier development builds, read as their current kind.
OLD_KINDS = {'greeting': 'start'}
ITEM_SUFFIXES = ('.md', '.jsx')
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
BAD_NAME = re.compile(r'[\\/:*?"<>|]')
SECTION_DEFAULTS = {
    'ko': {'identity': '식별', 'appearance': '외모', 'outfit': '의상'},
    'en': {'identity': 'Identity', 'appearance': 'Appearance', 'outfit': 'Outfit'},
}
RESERVED_REFS = ('{{user}}', '{{char}}')


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def stamp():
    return datetime.now().astimezone().strftime('%Y%m%dT%H%M%S')


def check_name(name):
    if not name or name.strip() != name or BAD_NAME.search(name) or name in ('.', '..') or name == APP_DIR:
        raise AppError(Msg('server.works.bad_name', 'This name cannot be used: {name}', name=name))
    return name


def check_id(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise AppError(
            Msg('server.works.bad_id', "Use only letters, digits, '_' and '-' (1-32 characters) for an ID.")
        )
    return value


def trash_bundle(folder, bundle_id):
    """The trash bundle a request names: one folder directly inside ``folder``, never a path that steps out of it."""
    name = str(bundle_id or '')
    path = Path(folder) / name
    if (
        not name
        or any(c in name for c in '/\\:\x00')
        or not name.strip('. ')
        or path.resolve().parent != Path(folder).resolve()
        or not path.is_dir()
    ):
        raise AppError(Msg('server.trash.missing', 'This trash entry does not exist.'), 404)
    return path


def restore_name(dest, is_dir):
    """``dest``, or the first free "(되살림)", "(되살림 2)" … name next to it. An existing file is never replaced."""
    if not dest.exists():
        return dest
    stem, suffix = (dest.name, '') if is_dir else (dest.stem, dest.suffix)
    n = 1
    while True:
        candidate = dest.with_name(f'{stem} (되살림{"" if n == 1 else f" {n}"}){suffix}')
        if not candidate.exists():
            return candidate
        n += 1


def next_code(prefix, used, width=3):
    used = {u.lower() for u in used}
    n = 1
    while f'{prefix}{n:0{width}d}'.lower() in used:
        n += 1
    return f'{prefix}{n:0{width}d}'


class Work:
    def __init__(self, folder):
        self.folder = Path(folder)

    # --- work.json -------------------------------------------------------------------------------------------
    @property
    def app(self):
        return self.folder / APP_DIR

    @property
    def doc_path(self):
        return self.app / 'work.json'

    def doc(self):
        doc = read_json(self.doc_path)
        if doc is None:
            raise AppError(Msg('server.works.not_a_work', 'This folder is not an AtelierX work.'), 404)
        return doc

    def update_doc(self, changes):
        doc = self.doc()
        doc.update(changes)
        doc['updated_at'] = now_iso()
        write_json(self.doc_path, doc)
        return doc

    @property
    def id(self):
        return self.doc()['id']

    @property
    def name(self):
        return self.folder.name

    # --- paths -----------------------------------------------------------------------------------------------
    def resolve(self, rel):
        """A path inside the user tree. ``rel`` uses '/' and never reaches ``.atelierx``."""
        rel = str(rel or '').strip('/')
        parts = PurePosixPath(rel).parts if rel else ()
        # Windows also splits on '\', ignores case and drops trailing dots and spaces, so `.ATELIERX\x` or `.atelierx.`
        # would name the app folder; ':' would name a drive or a data stream.
        if (
            '\\' in rel
            or ':' in rel
            or any(p in ('..', '') or p != p.rstrip('. ') for p in parts)
            or (parts and parts[0].casefold() == APP_DIR)
        ):
            raise AppError(Msg('server.works.bad_path', 'This path is not allowed.'))
        path = self.folder.joinpath(*parts)
        folder, resolved, app = self.folder.resolve(), path.resolve(), self.app.resolve()
        if (
            (folder not in resolved.parents and resolved != folder)
            or resolved == app
            or app in resolved.parents
        ):
            raise AppError(Msg('server.works.bad_path', 'This path is not allowed.'))
        return path

    def rel(self, path):
        return Path(path).relative_to(self.folder).as_posix()

    # --- items -----------------------------------------------------------------------------------------------
    def item_paths(self):
        for path in sorted(self.folder.rglob('*')):
            if APP_DIR in path.relative_to(self.folder).parts:
                continue
            if path.is_file() and path.suffix in ITEM_SUFFIXES:
                yield path

    def read_item(self, path):
        text = path.read_text(encoding='utf-8')
        try:
            meta, body, _ = frontmatter.split(text, path.suffix)
            error = None
        except frontmatter.MetaError as exc:
            meta, body, error = None, text, str(exc)
        kind = None
        if meta is not None:
            kind = meta.get('kind')
            kind = OLD_KINDS.get(kind, kind)
        if not kind:
            kind = 'jsx' if path.suffix == '.jsx' else 'lorebook'
        return {
            'path': self.rel(path),
            'name': path.stem,
            'meta': frontmatter.to_plain(meta) or {},
            'kind': kind,
            'body': body,
            'hash': sha256_text(text),
            'meta_error': error,
            'size': len(body.encode('utf-8')),
        }

    def index(self):
        """Every item with its id, kind and size (no bodies)."""
        out = []
        for path in self.item_paths():
            item = self.read_item(path)
            item.pop('body')
            out.append(item)
        return out

    def index_with_bodies(self):
        """Every item including its body."""
        return [self.read_item(path) for path in self.item_paths()]

    def used_ids(self):
        return [item['meta'].get('id') for item in self.index() if item['meta'].get('id')]

    def suggest_id(self, kind):
        prefix = KIND_PREFIX.get(kind)
        return next_code(prefix, self.used_ids()) if prefix else ''

    def tree(self):
        order = self.doc().get('order', {})
        index = {item['path']: item for item in self.index()}

        def walk(folder, rel):
            entries = []
            for child in folder.iterdir():
                if child.name == APP_DIR or child.name.startswith('.tmp-'):
                    continue
                child_rel = f'{rel}/{child.name}' if rel else child.name
                if child.is_dir():
                    entries.append(
                        {
                            'type': 'folder',
                            'name': child.name,
                            'path': child_rel,
                            'children': walk(child, child_rel),
                        }
                    )
                else:
                    item = index.get(child_rel)
                    entries.append(
                        {
                            'type': 'item' if item else 'file',
                            'name': child.name,
                            'path': child_rel,
                            'kind': item['kind'] if item else None,
                            'id': item['meta'].get('id') if item else None,
                            'enabled': item['meta'].get('enabled', True) if item else None,
                            'meta_error': item['meta_error'] if item else None,
                        }
                    )
            preferred = order.get(rel, [])
            rank = {name: i for i, name in enumerate(preferred)}
            entries.sort(
                key=lambda e: (rank.get(e['name'], len(rank)), e['type'] != 'folder', e['name'].lower())
            )
            return entries

        return walk(self.folder, '')

    def get_item(self, rel):
        path = self.resolve(rel)
        if not path.is_file():
            raise AppError(Msg('server.works.item_missing', 'The file does not exist: {path}', path=rel), 404)
        return self.read_item(path)

    # --- ID links (data-model: ID 바꾸기) ---------------------------------------------------------------------------
    def id_links(self, item_id):
        """Where an item ID is used besides the item: image data, JSX examples, the chat partner, the relation map."""
        key = str(item_id or '').casefold()
        if not key:
            return []
        places = []
        for folder, place in ((self.app / 'image' / 'characters', 'image'), (self.app / 'jsx', 'jsx')):
            if folder.is_dir() and any(p.name.casefold() == key for p in folder.iterdir()):
                places.append(place)
        if str((read_json(self.doc_path) or {}).get('char') or '').casefold() == key:
            places.append('char')
        relations = read_json(self.app / 'relations.json') or {}
        named = [p.get('id') for p in relations.get('people', [])]
        named += [v for r in relations.get('relations', []) for v in (r.get('from'), r.get('to'))]
        named += [f.get('subject') for f in relations.get('facts', [])]
        if any(str(v or '').casefold() == key for v in named):
            places.append('relations')
        return places

    def _check_id_change(self, rel, old, new):
        """An ID may be set freely while nothing refers to it; it must stay unique in the work (case ignored).

        A change of case alone is a change too: references are matched exactly, so ``C001`` → ``c001`` would break them.
        """
        old_key, new_key = str(old or '').casefold(), str(new or '').casefold()
        if str(old or '') == str(new or ''):
            return
        this = self.rel(self.resolve(rel))
        if new_key and any(
            str(i['meta'].get('id') or '').casefold() == new_key and i['path'] != this for i in self.index()
        ):
            raise AppError(
                Msg('server.works.id_taken', 'Another item already uses the ID {id}.', id=new), 409
            )
        if old_key and self.id_links(old):
            raise AppError(
                Msg(
                    'server.works.id_linked',
                    'The ID {id} is used by linked data (image data, JSX examples, the chat partner or the relation map),'
                    ' so it cannot be changed here.',
                    id=old,
                ),
                409,
            )

    def save_item(self, rel, meta_changes, body, base_hash):
        path = self.resolve(rel)
        text = path.read_text(encoding='utf-8') if path.is_file() else ''
        if base_hash and path.is_file() and sha256_text(text) != base_hash:
            raise AppError(
                Msg('server.works.changed_on_disk', 'The file changed on disk since it was opened.'), 409
            )
        try:
            meta, old_body, _ = frontmatter.split(text, path.suffix) if text else (None, '', '')
        except frontmatter.MetaError:
            meta, old_body = None, text
        if meta_changes is not None:
            if meta_changes.get('id'):
                check_id(meta_changes['id'])
            if 'id' in meta_changes:
                self._check_id_change(rel, (meta or {}).get('id'), meta_changes['id'])
            meta = frontmatter.apply_changes(meta, meta_changes)
            if 'schema_version' not in meta:
                meta.insert(0, 'schema_version', 1)
        new_body = old_body if body is None else body
        atomic_write_text(path, frontmatter.join(meta, new_body, path.suffix))
        return self.read_item(path)

    def create_file(self, rel, kind=None):
        path = self.resolve(rel)
        if path.suffix not in ITEM_SUFFIXES:
            path = path.with_name(path.name + '.md')
        check_name(path.name)
        if path.exists():
            raise AppError(Msg('server.works.exists', 'Something with this name already exists.'), 409)
        kind = kind or ('jsx' if path.suffix == '.jsx' else 'lorebook')
        meta = {'schema_version': 1, 'kind': kind}
        body = ''
        if kind == 'jsx':
            name = path.stem if re.fullmatch(r'[A-Za-z_$][\w$]*', path.stem) else 'Component'
            body = f'function {name}(props) {{\n  return <div>{name}</div>;\n}}\n'
        atomic_write_text(path, frontmatter.join(meta, body, path.suffix))
        return self.read_item(path)

    def create_folder(self, rel):
        path = self.resolve(rel)
        check_name(path.name)
        if path.exists():
            raise AppError(Msg('server.works.exists', 'Something with this name already exists.'), 409)
        path.mkdir(parents=True)
        return {'path': self.rel(path)}

    def move(self, src, dst):
        source, target = self.resolve(src), self.resolve(dst)
        check_name(target.name)
        if not source.exists():
            raise AppError(Msg('server.works.item_missing', 'The file does not exist: {path}', path=src), 404)
        if target.exists() and target.resolve() != source.resolve():
            raise AppError(Msg('server.works.exists', 'Something with this name already exists.'), 409)
        if source.is_dir() and target.resolve().is_relative_to(source.resolve()) and target != source:
            raise AppError(Msg('server.works.move_into_self', 'A folder cannot be moved into itself.'))
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return {'path': self.rel(target)}

    def change_kind(self, rel, kind):
        if kind not in KINDS:
            raise AppError(Msg('server.works.bad_kind', 'Unknown kind: {kind}', kind=kind))
        path = self.resolve(rel)
        item = self.read_item(path)
        want_suffix = '.jsx' if kind == 'jsx' else '.md'
        if path.suffix != want_suffix:
            target = path.with_suffix(want_suffix)
            if target.exists():
                raise AppError(Msg('server.works.exists', 'Something with this name already exists.'), 409)
            text = path.read_text(encoding='utf-8')
            meta, body, _ = frontmatter.split(text, path.suffix)
            meta = frontmatter.apply_changes(meta, {'kind': kind})
            atomic_write_text(target, frontmatter.join(meta, body, want_suffix))
            path.unlink()
            return self.read_item(target)
        return self.save_item(rel, {'kind': kind}, None, item['hash'])

    # --- trash -----------------------------------------------------------------------------------------------
    def delete(self, rel, with_extras=False):
        path = self.resolve(rel)
        if not path.exists():
            raise AppError(Msg('server.works.item_missing', 'The file does not exist: {path}', path=rel), 404)
        ids = []
        targets = [path]
        items = [path] if path.is_file() else [p for p in path.rglob('*') if p.suffix in ITEM_SUFFIXES]
        for item_path in items:
            meta = self.read_item(item_path)['meta']
            if meta.get('id'):
                ids.append(meta['id'])
                if with_extras:
                    for extra in (
                        self.app / 'image' / 'characters' / meta['id'],
                        self.app / 'jsx' / meta['id'],
                    ):
                        if extra.exists():
                            targets.append(extra)
        bundle = self.app / 'trash' / f'{stamp()}-{len(list((self.app / "trash").glob("*"))) + 1:03d}'
        size = 0
        moved = []
        for target in targets:
            rel_target = target.relative_to(self.folder).as_posix()
            dest = bundle / 'files' / rel_target
            dest.parent.mkdir(parents=True, exist_ok=True)
            size += sum(
                f.stat().st_size for f in ([target] if target.is_file() else target.rglob('*')) if f.is_file()
            )
            shutil.move(str(target), str(dest))
            moved.append(rel_target + ('/' if dest.is_dir() else ''))
        kind = 'folder' if path.is_dir() or not moved[0].endswith(ITEM_SUFFIXES) else 'item'
        write_json(
            bundle / 'entry.json',
            {
                'schema_version': 1,
                'kind': kind,
                'deleted_at': now_iso(),
                'paths': moved,
                'ids': ids,
                'size': size,
            },
        )
        return {'bundle': bundle.name, 'paths': moved}

    def trash(self):
        out = []
        folder = self.app / 'trash'
        if folder.is_dir():
            for bundle in sorted(folder.iterdir(), reverse=True):
                entry = read_json(bundle / 'entry.json')
                if entry:
                    out.append({'id': bundle.name, **entry})
        return out

    def _trash_target(self, rel):
        """Where a trash entry path goes back to: inside the work, never into the trash or the history."""
        rel = str(rel or '').rstrip('/')
        parts = rel.split('/')
        if (
            not rel
            or '\\' in rel
            or ':' in rel
            or any(not p.strip('. ') or p != p.rstrip('. ') for p in parts)
        ):
            raise AppError(Msg('server.trash.damaged', 'This trash entry is damaged.'))
        dest = self.folder.joinpath(*parts)
        resolved = dest.resolve()
        if self.folder.resolve() not in resolved.parents:
            raise AppError(Msg('server.trash.damaged', 'This trash entry is damaged.'))
        for kept in (self.app / 'trash', self.app / 'history'):
            if resolved == kept.resolve() or kept.resolve() in resolved.parents:
                raise AppError(Msg('server.trash.damaged', 'This trash entry is damaged.'))
        return rel, dest

    def restore_trash(self, bundle_id):
        bundle = trash_bundle(self.app / 'trash', bundle_id)
        entry = read_json(bundle / 'entry.json')
        if entry is None:
            raise AppError(Msg('server.trash.missing', 'This trash entry does not exist.'), 404)
        # Check every path before moving anything, so a damaged entry changes nothing.
        moves = []
        for rel, dest in (self._trash_target(rel) for rel in entry.get('paths', [])):
            source = bundle / 'files' / rel
            if not source.exists():
                raise AppError(Msg('server.trash.damaged', 'This trash entry is damaged.'))
            moves.append((source, dest))
        for source, dest in moves:
            dest = restore_name(dest, source.is_dir())
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
        shutil.rmtree(bundle)
        return entry

    def purge_trash(self, bundle_id=None):
        folder = self.app / 'trash'
        if bundle_id:
            shutil.rmtree(trash_bundle(folder, bundle_id))
            return
        targets = list(folder.iterdir()) if folder.is_dir() else []
        for target in targets:
            if target.is_dir():
                shutil.rmtree(target)

    # --- sections (characters) ---------------------------------------------------------------------------------
    def section_titles(self):
        doc = self.doc()
        titles = dict(SECTION_DEFAULTS.get(doc.get('language', 'ko'), SECTION_DEFAULTS['en']))
        titles.update(doc.get('character_sections') or {})
        return titles

    def section_text(self, body, key, heading=None):
        title = self.section_titles().get(key)
        if not title:
            return None
        lines = body.splitlines()
        start = next((i for i, line in enumerate(lines) if line.strip() == f'## {title}'), None)
        if start is None:
            return None
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
        part = lines[start + 1 : end]
        if heading:
            sub = next((i for i, line in enumerate(part) if line.strip() == f'### {heading}'), None)
            if sub is None:
                return None
            sub_end = next((i for i in range(sub + 1, len(part)) if part[i].startswith('### ')), len(part))
            part = part[sub + 1 : sub_end]
        return '\n'.join(part).strip()


class WorkStore:
    def __init__(self, paths):
        self.paths = paths

    def all(self):
        works = []
        if self.paths.works.is_dir():
            for folder in sorted(self.paths.works.iterdir()):
                if (folder / APP_DIR / 'work.json').is_file():
                    works.append(Work(folder))
        return works

    def get(self, work_id):
        for work in self.all():
            if work.doc().get('id', '').lower() == str(work_id).lower():
                return work
        raise AppError(Msg('server.works.not_found', 'Work {id} was not found.', id=work_id), 404)

    def card(self, work):
        doc = work.doc()
        index = work.index()
        used = [i for i in index if i['kind'] != 'note' and i['meta'].get('enabled', True)]
        return {
            'id': doc['id'],
            'name': work.name,
            'tags': doc.get('tags', []),
            'scale': doc.get('scale'),
            'language': doc.get('language'),
            'items': len(index),
            'size': sum(i['size'] for i in used),
            'updated_at': doc.get('updated_at'),
        }

    def suggest_id(self):
        return next_code('W', [w.doc().get('id', '') for w in self.all()])

    def _check_new(self, name, work_id):
        check_name(name)
        check_id(work_id)
        if (self.paths.works / name).exists():
            raise AppError(Msg('server.works.name_taken', 'A work with this name already exists.'), 409)
        if any(w.doc().get('id', '').lower() == work_id.lower() for w in self.all()):
            raise AppError(
                Msg('server.works.id_taken', 'This ID is already used. Try {id}.', id=self.suggest_id()), 409
            )

    def create(self, name, work_id=None, tags=None, scale='single', language='ko'):
        work_id = work_id or self.suggest_id()
        self._check_new(name, work_id)
        folder = self.paths.works / name
        doc = {
            'schema_version': 1,
            'layout_version': 1,
            'id': work_id,
            'tags': tags or [],
            'scale': scale,
            'language': language,
            'overrides': {},
            'character_sections': {},
            'char': None,
            'llm_consent': [],
            'order': {},
            'created_at': now_iso(),
            'updated_at': now_iso(),
        }
        write_json(folder / APP_DIR / 'work.json', doc)
        return Work(folder)

    def samples(self):
        out = []
        if self.paths.samples.is_dir():
            for folder in sorted(self.paths.samples.iterdir()):
                doc = read_json(folder / APP_DIR / 'work.json')
                if doc:
                    out.append({'name': folder.name, 'scale': doc.get('scale'), 'tags': doc.get('tags', [])})
        return out

    def install_sample(self, sample, name=None):
        source = self.paths.samples / sample
        if not (source / APP_DIR / 'work.json').is_file():
            raise AppError(
                Msg('server.works.sample_missing', 'Sample {name} was not found.', name=sample), 404
            )
        name = name or f'샘플 {sample}'
        work_id = self.suggest_id()
        self._check_new(name, work_id)
        folder = self.paths.works / name
        shutil.copytree(source, folder)
        work = Work(folder)
        work.update_doc({'id': work_id, 'created_at': now_iso()})
        refresh_unknown_hashes(work)
        return work

    def duplicate(self, work_id, name, new_id=None):
        work = self.get(work_id)
        new_id = new_id or self.suggest_id()
        self._check_new(name, new_id)
        skip = {'history', 'drafts', 'trash'}

        def ignore(folder, names):
            if Path(folder).name == APP_DIR:
                return [n for n in names if n in skip]
            if Path(folder).name == 'tests':
                return [n for n in names if n == 'runs']
            return []

        shutil.copytree(work.folder, self.paths.works / name, ignore=ignore)
        copy = Work(self.paths.works / name)
        copy.update_doc({'id': new_id, 'created_at': now_iso()})
        return copy

    def rename(self, work_id, name):
        work = self.get(work_id)
        check_name(name)
        target = self.paths.works / name
        if target.exists():
            raise AppError(Msg('server.works.name_taken', 'A work with this name already exists.'), 409)
        work.folder.rename(target)
        return Work(target)

    def delete(self, work_id):
        work = self.get(work_id)
        bundle = self.paths.data_trash / f'{stamp()}-{work.id}'
        size = sum(f.stat().st_size for f in work.folder.rglob('*') if f.is_file())
        bundle.mkdir(parents=True)
        shutil.move(str(work.folder), str(bundle / 'files' / work.name))
        write_json(
            bundle / 'entry.json',
            {
                'schema_version': 1,
                'kind': 'work',
                'deleted_at': now_iso(),
                'paths': [f'works/{work.name}/'],
                'ids': [work.id],
                'size': size,
            },
        )
        return {'bundle': bundle.name}

    def trash(self):
        out = []
        if self.paths.data_trash.is_dir():
            for bundle in sorted(self.paths.data_trash.iterdir(), reverse=True):
                entry = read_json(bundle / 'entry.json')
                if entry:
                    out.append({'id': bundle.name, **entry})
        return out

    def restore(self, bundle_id):
        bundle = trash_bundle(self.paths.data_trash, bundle_id)
        entry = read_json(bundle / 'entry.json')
        if entry is None:
            raise AppError(Msg('server.trash.missing', 'This trash entry does not exist.'), 404)
        for source in (bundle / 'files').iterdir():
            dest = restore_name(self.paths.works / source.name, True)
            shutil.move(str(source), str(dest))
            work = Work(dest)
            if any(w.folder != dest and w.id.lower() == work.id.lower() for w in self.all()):
                work.update_doc({'id': self.suggest_id()})
        shutil.rmtree(bundle)
        return entry

    def purge(self, bundle_id=None):
        if bundle_id:
            shutil.rmtree(trash_bundle(self.paths.data_trash, bundle_id))
            return
        targets = list(self.paths.data_trash.iterdir()) if self.paths.data_trash.is_dir() else []
        for target in targets:
            if target.is_dir():
                shutil.rmtree(target)


def refresh_unknown_hashes(work):
    """Designs copied from elsewhere (samples) carry placeholder hashes; compute them from the current bodies."""
    chars = {item['meta'].get('id'): item for item in work.index() if item['kind'] == 'character'}
    root = work.app / 'image' / 'characters'
    if not root.is_dir():
        return
    for folder in root.iterdir():
        design_path = folder / 'design.json'
        design = read_json(design_path)
        item = chars.get(folder.name)
        if not design or not item:
            continue
        body = work.get_item(item['path'])['body']
        parts = [design.get('appearance', {})] + list((design.get('outfits') or {}).values())
        for part in parts:
            source = part.get('source') or {}
            if source and not re.fullmatch(r'[0-9a-f]{64}', str(source.get('hash', ''))):
                text = work.section_text(body, source.get('section'), source.get('heading'))
                if text is not None:
                    source['hash'] = sha256_text(text)
        write_json(design_path, design)
