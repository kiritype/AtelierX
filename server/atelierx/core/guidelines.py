"""Guidelines with fixed names (data-model: 정해진 이름), looked up work → linked presets in tag order → global → the
app's defaults (a data root made by an older version lacks guidelines added later, e.g. the agent modes).

Settings → 지침 (11-agent) lists and edits the global ones: the data root's copy, or the app default while none is saved.
"""

import re

from . import frontmatter
from .fsutil import atomic_write_text, sha256_text
from .i18n import AppError, Msg

COMPRESSION_GUIDELINE = 'compression.md'
# A guideline name is a file under guidelines/: at most one folder deep, Markdown only.
NAME = re.compile(r'(?:[\w-]+/)?[\w][\w .-]*\.md')
AGENT_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,39}')


def compression_settings(paths):
    """Return the editable global compression guideline and its immutable default."""
    saved = paths.data / 'guidelines' / COMPRESSION_GUIDELINE
    default = paths.defaults / 'guidelines' / COMPRESSION_GUIDELINE
    text = saved.read_text(encoding='utf-8') if saved.is_file() else ''
    default_text = default.read_text(encoding='utf-8') if default.is_file() else ''
    return {'text': text, 'default_text': default_text, 'revision': sha256_text(text)}


def save_compression_settings(paths, data):
    """Save only the fixed global guideline path using optimistic concurrency."""
    if (
        not isinstance(data, dict)
        or not isinstance(data.get('text'), str)
        or not isinstance(data.get('base_revision'), str)
    ):
        raise AppError(Msg('server.guidelines.invalid', 'A text value and base revision are required.'), 400)
    current = compression_settings(paths)
    if data['base_revision'] != current['revision']:
        raise AppError(
            Msg('server.guidelines.stale', 'The compression guideline changed after it was loaded.'), 409
        )
    path = paths.data / 'guidelines' / COMPRESSION_GUIDELINE
    atomic_write_text(path, data['text'])
    return compression_settings(paths)


def _candidates(work, paths, linked, name):
    yield 'work', work.app / 'guidelines' / name
    for preset in linked:
        yield f'preset:{preset}', paths.platforms / preset / 'guidelines' / name
    yield 'global', paths.data / 'guidelines' / name
    yield 'default', paths.defaults / 'guidelines' / name


def locate(work, paths, linked, name):
    """``(text, source)`` of the guideline this work uses; ``('', None)`` when there is none."""
    for source, path in _candidates(work, paths, linked, name):
        if path.is_file():
            return path.read_text(encoding='utf-8'), source
    return '', None


def find(work, paths, linked, name):
    return locate(work, paths, linked, name)[0]


def folders(work, paths, linked, sub):
    """Every guidelines/<sub> folder this work can draw from (for listing the agent modes)."""
    return [path.parent for _, path in _candidates(work, paths, linked, f'{sub}/x.md')]


# --- Settings → 지침: the global guidelines ----------------------------------------------------------------------
def group_of(name):
    if name.startswith('agent/'):
        return 'agent'
    if name == 'image-prompt.md':
        return 'image'
    if name in ('platform.md', 'compression.md', 'consistency.md', 'jsx.md') or name.startswith('authoring/'):
        return 'task'
    return 'other'


def check_name(name):
    name = str(name or '')
    if not NAME.fullmatch(name) or '..' in name or name.startswith('.'):
        raise AppError(Msg('server.guidelines.bad_name', 'This guideline name is not allowed.'), 400)
    if name.startswith('agent/') and not AGENT_ID.fullmatch(name[len('agent/') : -len('.md')]):
        raise AppError(
            Msg(
                'server.guidelines.bad_mode_id',
                'A mode ID uses lowercase letters, digits and hyphens (at most 40).',
            ),
            400,
        )
    return name


def _names(folder):
    if not folder.is_dir():
        return set()
    return {p.relative_to(folder).as_posix() for p in folder.rglob('*.md') if p.is_file()}


def mode_head(text):
    """Front matter of an agent mode guideline: name, description, scope (file|work), order."""
    try:
        meta, body, _ = frontmatter.split(text, '.md')
    except frontmatter.MetaError:
        meta, body = None, text
    meta = frontmatter.to_plain(meta) or {}
    scope = meta.get('scope') if meta.get('scope') in ('file', 'work') else 'file'
    try:
        order = int(meta.get('order', 100))
    except (TypeError, ValueError):
        order = 100
    return {
        'name': str(meta.get('name') or '').strip(),
        'description': str(meta.get('description') or '').strip(),
        'scope': scope,
        'order': order,
    }, body


def global_file(paths, name):
    name = check_name(name)
    saved = paths.data / 'guidelines' / name
    default = paths.defaults / 'guidelines' / name
    default_text = default.read_text(encoding='utf-8') if default.is_file() else None
    text = saved.read_text(encoding='utf-8') if saved.is_file() else default_text
    if text is None:
        raise AppError(Msg('server.guidelines.missing', 'This guideline does not exist.'), 404)
    return {'name': name, 'text': text, 'default_text': default_text, 'revision': sha256_text(text)}


def list_global(paths):
    saved_root, default_root = paths.data / 'guidelines', paths.defaults / 'guidelines'
    saved, defaults = _names(saved_root), _names(default_root)
    items = []
    for name in sorted(saved | defaults):
        text = (saved_root / name if name in saved else default_root / name).read_text(encoding='utf-8')
        if name not in defaults:
            source = 'custom'
        elif name in saved and text != (default_root / name).read_text(encoding='utf-8'):
            source = 'modified'
        else:
            source = 'default'
        item = {'name': name, 'group': group_of(name), 'source': source}
        if item['group'] == 'agent':
            head, _ = mode_head(text)
            item.update({**head, 'title': head['name'], 'name': name})
        items.append(item)
    return items


def save_global(paths, name, data):
    name = check_name(name)
    if not isinstance(data, dict) or not isinstance(data.get('text'), str):
        raise AppError(Msg('server.guidelines.invalid', 'A text value and base revision are required.'), 400)
    try:
        current = global_file(paths, name)['revision']
    except AppError:
        current = ''  # a new guideline: the screen sends an empty revision
    if data.get('base_revision') != current:
        raise AppError(Msg('server.guidelines.changed', 'This guideline changed after it was loaded.'), 409)
    atomic_write_text(paths.data / 'guidelines' / name, data['text'].replace('\r\n', '\n'))
    return global_file(paths, name)


def delete_global(paths, name):
    """Only a guideline the user added can go; an app default is reset by saving its default text instead."""
    name = check_name(name)
    if (paths.defaults / 'guidelines' / name).is_file():
        raise AppError(
            Msg(
                'server.guidelines.default_kept',
                'An app guideline cannot be deleted. Reset it to the default instead.',
            ),
            400,
        )
    path = paths.data / 'guidelines' / name
    if not path.is_file():
        raise AppError(Msg('server.guidelines.missing', 'This guideline does not exist.'), 404)
    path.unlink()
    return list_global(paths)
