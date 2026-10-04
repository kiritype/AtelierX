"""Export: the user tree as the platform will receive it (data-model: 내보내기)."""

from pathlib import Path

from .fsutil import atomic_write_text
from .i18n import AppError, Msg

# Reserved name at the export root; the leading '_' keeps it apart from ordinary item names.
KEYWORDS_FILE = '_keywords.md'

# Column titles follow the work language. The import side (later) reads both.
TABLE_TEXT = {
    'ko': {
        'head': ('경로', 'ID', '이름', '키워드', '우선순위', '항상 넣기'),
        'yes': '예',
        'no': '아니요',
    },
    'en': {
        'head': ('Path', 'ID', 'Name', 'Keywords', 'Priority', 'Always'),
        'yes': 'yes',
        'no': 'no',
    },
}


def plan(work):
    include, skip = [], []
    for path in work.item_paths():
        item = work.read_item(path)
        if item['kind'] == 'note':
            skip.append({'path': item['path'], 'reason': 'note'})
        elif not item['meta'].get('enabled', True):
            skip.append({'path': item['path'], 'reason': 'disabled'})
        else:
            include.append(item)
    return include, skip


def name_clash(items):
    """Path of an exported item that would collide with the keywords table, or None."""
    return next((i['path'] for i in items if i['path'].lower() == KEYWORDS_FILE), None)


def _cell(value):
    return str(value).replace('|', '\\|')


def keywords_table(items, language='ko'):
    text = TABLE_TEXT.get(language, TABLE_TEXT['en'])
    rows = ['| ' + ' | '.join(text['head']) + ' |', '|' + '---|' * len(text['head'])]
    for item in items:
        if item['kind'] not in ('lorebook', 'character'):
            continue
        meta = item['meta']
        keywords = ', '.join(f'"{k}"' if ',' in str(k) else str(k) for k in meta.get('keywords') or [])
        cells = (
            item['path'],
            meta.get('id') or '',
            item['name'],
            keywords,
            meta.get('priority', ''),
            text['yes'] if meta.get('always') else text['no'],
        )
        rows.append('| ' + ' | '.join(_cell(c) for c in cells) + ' |')
    return '\n'.join(rows) + '\n'


def target_state(target_dir, items):
    """What is already in the target folder: whether it has files, and files the export will not write (leftovers)."""
    if not target_dir:
        return None
    target = Path(target_dir)
    if not target.is_absolute() or not target.is_dir():
        return {'exists': target.exists(), 'files': 0, 'leftovers': []}
    written = {i['path'] for i in items} | {KEYWORDS_FILE}
    files = [p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()]
    leftovers = sorted(f for f in files if f not in written)
    return {'exists': True, 'files': len(files), 'leftovers': leftovers[:200]}


def export(work, target_dir, overwrite=False):
    target = Path(target_dir)
    include, skip = plan(work)
    clash = name_clash(include)
    if clash:
        raise AppError(
            Msg(
                'server.export.name_clash',
                '{path} has the reserved export name. Rename it first.',
                path=clash,
            ),
            409,
        )
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise AppError(
            Msg('server.export.not_empty', 'The folder is not empty. Confirm overwriting first.'), 409
        )
    for item in include:
        atomic_write_text(target / item['path'], item['body'])
    atomic_write_text(target / KEYWORDS_FILE, keywords_table(include, work.doc().get('language', 'ko')))
    return {'written': [i['path'] for i in include] + [KEYWORDS_FILE], 'skipped': skip}
