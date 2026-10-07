"""Bringing single .md and .jsx files into a work (#115, data-model: 낱개 파일 가져오기).

The screen sends the files' text and the user's choices; ``plan`` answers what each file becomes (path, kind, ID,
whether its head was read) and ``apply`` writes them after a snapshot. The app never guesses a kind: a Markdown file
without a metadata head waits until the user picks one. ``_keywords.md`` (this app's export) is read as a table of
keywords, priority and "always", not imported as a file.
"""

import re
from pathlib import PurePosixPath

from . import frontmatter
from .exporter import KEYWORDS_FILE, TABLE_TEXT
from .i18n import AppError, Msg
from .snapshots import Snapshots
from .works import ID_RE, KIND_PREFIX, KINDS, check_name, next_code

MAX_FILES = 200
MAX_BYTES = 2 * 1024 * 1024
SUFFIXES = ('.md', '.jsx')


# --- the keywords table of an export -----------------------------------------------------------------------------
def _cells(line):
    """Cells of a Markdown table row; '\\|' stays a bar inside a cell."""
    parts = re.split(r'(?<!\\)\|', line.strip().strip('|'))
    return [p.strip().replace('\\|', '|') for p in parts]


def _keywords(text):
    out, current, quoted = [], '', False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif ch == ',' and not quoted:
            out.append(current.strip())
            current = ''
        else:
            current += ch
    out.append(current.strip())
    return [k for k in out if k]


def read_table(text):
    """``{path: {id, keywords, priority, always}}`` from a keywords table in Korean or English."""
    heads = {tuple(v['head']): v for v in TABLE_TEXT.values()}
    rows = [line for line in text.replace('\r\n', '\n').split('\n') if line.strip().startswith('|')]
    if len(rows) < 2:
        return {}
    language = heads.get(tuple(_cells(rows[0])))
    if language is None:
        return {}
    yes = {v['yes'] for v in TABLE_TEXT.values()}
    table = {}
    for line in rows[2:]:
        cells = _cells(line)
        if len(cells) < 6 or not cells[0]:
            continue
        priority = cells[4]
        table[cells[0]] = {
            'id': cells[1] if ID_RE.fullmatch(cells[1] or '') else '',
            'keywords': _keywords(cells[3]),
            'priority': int(priority) if re.fullmatch(r'-?\d+', priority) else None,
            'always': cells[5] in yes,
        }
    return table


# --- plan --------------------------------------------------------------------------------------------------------
def _files(files):
    if not isinstance(files, list) or not files:
        raise AppError(Msg('server.import.no_files', 'Choose .md or .jsx files to bring in.'))
    if len(files) > MAX_FILES:
        raise AppError(Msg('server.import.too_many', 'Bring in up to {max} files at a time.', max=MAX_FILES))
    out = []
    for n, entry in enumerate(files):
        name = str((entry or {}).get('name') or '')
        text = (entry or {}).get('text')
        if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
            raise AppError(Msg('server.import.too_big', '{name} is too big (up to 2 MB).', name=name))
        relative = str((entry or {}).get('path') or name).replace('\\', '/').strip('/')
        out.append({'key': f'f{n}', 'name': PurePosixPath(name).name, 'relative': relative, 'text': text})
    return out


def _unique_name(name, taken):
    stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate = f'{stem} ({n}){suffix}'
        n += 1
    taken.add(candidate.lower())
    return candidate


def plan(work, folder, files, choices=None):
    """What each file becomes. ``choices``: per file key, {include, kind, id, enabled, use_table, broken}."""
    choices = choices if isinstance(choices, dict) else {}
    folder = str(folder or '').replace('\\', '/').strip('/')
    if folder:
        for part in folder.split('/'):
            check_name(part)
        target_dir = work.resolve(folder)
        if not target_dir.is_dir():
            raise AppError(Msg('server.import.no_folder', 'The folder does not exist: {path}', path=folder))
    else:
        target_dir = work.folder
    entries = _files(files)

    table = {}
    for entry in entries:
        if entry['name'].lower() == KEYWORDS_FILE:
            table.update(read_table(entry['text']))
    by_name = {}
    for path, row in table.items():
        by_name.setdefault(PurePosixPath(path).name, []).append(row)

    taken_names = {p.name.lower() for p in target_dir.iterdir()} if target_dir.is_dir() else set()
    used_ids = {i.lower() for i in work.used_ids()}
    main_enabled = sum(1 for i in work.index() if i['kind'] == 'main' and i['meta'].get('enabled', True))
    rows = []
    for entry in entries:
        name, choice = entry['name'], choices.get(entry['key']) or {}
        suffix = PurePosixPath(name).suffix.lower()
        if name.lower() == KEYWORDS_FILE:
            rows.append({'key': entry['key'], 'name': name, 'role': 'table', 'matched': len(table)})
            continue
        if suffix not in SUFFIXES:
            rows.append({'key': entry['key'], 'name': name, 'role': 'skip', 'reason': 'not_item'})
            continue
        row = {'key': entry['key'], 'name': name, 'role': 'item', 'suffix': suffix}
        try:
            meta, body, _ = frontmatter.split(entry['text'], suffix)
            row['head'] = 'ok' if meta is not None else 'none'
        except frontmatter.MetaError as error:
            meta, body = None, entry['text']
            row.update(head='broken', error=str(error))
        plain = frontmatter.to_plain(meta) or {}
        found = table.get(entry['relative']) or (
            by_name.get(name, [None])[0] if len(by_name.get(name, [])) == 1 else None
        )
        row['table'] = found

        # The kind: from the head, from the suffix for .jsx, else only what the user picked.
        kind = choice.get('kind') if choice.get('kind') in KINDS else None
        if row['head'] == 'ok':
            kind = kind or plain.get('kind') or ('jsx' if suffix == '.jsx' else 'lorebook')
        elif suffix == '.jsx' and row['head'] == 'none':
            kind = 'jsx'
        if row['head'] == 'broken':
            row['broken'] = choice.get('broken') if choice.get('broken') in ('skip', 'note') else None
            if row['broken'] == 'note':
                kind = 'note'
        if kind and (suffix == '.jsx') != (kind == 'jsx'):
            row['kind_error'] = 'suffix'
        row['kind'] = kind
        row['include'] = bool(choice.get('include', row['head'] != 'broken'))

        # The ID: what the user typed, else the head's, else the table's, else the next free one for the kind.
        original = str(plain.get('id') or (found or {}).get('id') or '')
        wanted = str(choice.get('id') or '').strip()
        row['original_id'] = original
        if not row['include'] or not kind:
            row['id'] = wanted or original
        elif wanted:
            row['id'] = wanted
            if not ID_RE.fullmatch(wanted):
                row['id_error'] = 'format'
            elif wanted.lower() in used_ids:
                row['id_error'] = 'taken'
        elif original and ID_RE.fullmatch(original) and original.lower() not in used_ids:
            row['id'] = original
        elif kind in KIND_PREFIX:
            row['id'] = next_code(KIND_PREFIX[kind], used_ids)
        else:
            row['id'] = ''
        row['id_changed'] = bool(original) and row['id'] != original
        if row['include'] and kind and row['id'] and 'id_error' not in row:
            used_ids.add(row['id'].lower())

        row['enabled'] = bool(choice.get('enabled', plain.get('enabled', True)))
        row['use_table'] = bool(found) and bool(choice.get('use_table', True))
        if row['include']:
            # The file is saved with the suffix checked above, in lower case: "UPPER.MD" → "UPPER.md" (#165).
            stored = PurePosixPath(name).stem + suffix
            row['path'] = (f'{folder}/' if folder else '') + _unique_name(stored, taken_names)
            row['renamed'] = PurePosixPath(row['path']).name != name
            if kind == 'main' and row['enabled']:
                main_enabled += 1
        row['_meta'], row['_body'] = meta, body
        rows.append(row)
    for row in rows:
        if row.get('kind') == 'main' and row.get('include') and row.get('enabled') and main_enabled > 1:
            row['main_warning'] = True
    return rows


def public(rows):
    return {
        'rows': [{k: v for k, v in r.items() if not k.startswith('_')} for r in rows],
        'blocked': [r['key'] for r in rows if _blocked(r)],
    }


def _blocked(row):
    """Why an included file cannot be written yet (no kind, a bad ID, an unchosen broken head), or None."""
    if row.get('role') != 'item' or not row.get('include'):
        return None
    if row.get('head') == 'broken' and row.get('broken') != 'note':
        return 'broken'
    if not row.get('kind'):
        return 'kind'
    if row.get('kind_error') or row.get('id_error'):
        return 'invalid'
    return None


def apply(work, folder, files, choices, settings=None):
    rows = plan(work, folder, files, choices)
    blocked = [r for r in rows if _blocked(r)]
    if blocked:
        raise AppError(
            Msg(
                'server.import.not_ready',
                '{n} files still need a kind, a valid ID or a choice for their broken head.',
                n=len(blocked),
            )
        )
    todo = [r for r in rows if r.get('role') == 'item' and r.get('include')]
    if not todo:
        raise AppError(Msg('server.import.nothing', 'No file is chosen to bring in.'))
    Snapshots(work).create('import', None, force=True)
    prepared = []
    for row in todo:
        suffix = row['suffix']
        if row.get('head') == 'broken':
            meta, body = {}, row['_body']
        else:
            meta, body = row['_meta'] if row['_meta'] is not None else {}, row['_body']
        if 'schema_version' not in meta:
            meta['schema_version'] = 1
        meta['kind'] = row['kind']
        if row['id']:
            meta['id'] = row['id']
        elif 'id' in meta:
            del meta['id']
        if row['kind'] != 'note':
            meta['enabled'] = row['enabled']
        if row.get('use_table') and row['kind'] in ('lorebook', 'character'):
            found = row['table']
            if found['keywords']:
                meta['keywords'] = found['keywords']
            if found['priority'] is not None:
                meta['priority'] = found['priority']
            meta['always'] = found['always']
        prepared.append((row['path'], frontmatter.join(meta, body, suffix)))
    # All or nothing (#165): a file refused half way takes back the ones written before it, so a retry does not
    # leave "name (2)" copies behind.
    created = []
    try:
        for rel, text in prepared:
            work.write_whole(rel, text, new=True)
            created.append(work.rel(work.resolve(rel)))
    except Exception:
        for rel in created:
            work.resolve(rel).unlink(missing_ok=True)
        raise
    return {'created': created}
