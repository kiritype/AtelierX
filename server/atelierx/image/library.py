"""Image prompt library (data-model: 라이브러리): expressions, compositions, styles, common prompts, shared outfit
parts and generation presets. Items live globally (data/image/) and per work (.atelierx/image/); a work item
with the same id overrides the global one.
"""

import re

from ..core.i18n import Msg
from .util import atomic_json, read_json

KINDS = ('expressions', 'compositions', 'styles', 'common', 'outfits')
SCOPES = ('global', 'work')
ITEM_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
MAX_TAGS = 300
MAX_GROUP = 40
MAX_TARGETS = 20
# What an item can be written for (#80): model families of the local image server and the image services. Users may
# add more in compose.json; an item without targets fits all of them.
DEFAULT_TARGETS = [
    {'id': 'sdxl', 'name': 'SDXL·IL'},
    {'id': 'anima', 'name': 'Anima'},
    {'id': 'novelai', 'name': 'NovelAI'},
    {'id': 'pixai', 'name': 'PixAI'},
]
# Before #80 an item named one model family (or 'shared' for both).
LEGACY_FAMILIES = ('anima', 'sdxl')


def _check_kind(kind):
    if kind not in KINDS:
        raise ValueError(Msg('server.image.library.unknown_kind', 'Unknown library kind: {kind}', kind=kind))


def _file(paths, work, kind, scope):
    if scope == 'global':
        return paths.data / 'image' / f'{kind}.json'
    if scope == 'work' and work is not None:
        return work.app / 'image' / f'{kind}.json'
    raise ValueError(Msg('server.image.library.unknown_scope', 'Choose global or work.'))


def targets_of(item, known=None):
    """The targets an item is written for; empty means all. Reads the model_family of files from before #80."""
    if isinstance(item.get('targets'), list):
        wanted = [t for t in item['targets'] if isinstance(t, str)]
    else:
        family = item.get('model_family')
        wanted = [family] if family in LEGACY_FAMILIES else []
    return [t for t in dict.fromkeys(wanted) if known is None or t in known]


def fits(item, target):
    """Whether an item may go into a prompt for `target` (a model family or an image service)."""
    wanted = item.get('targets') if 'targets' in item else targets_of(item)
    return not target or not wanted or target in wanted


def items(paths, work, kind):
    """Merged items of one kind: {id: {..., 'group', 'targets', 'scope': 'global'|'work', 'overrides': bool}}."""
    _check_kind(kind)
    known = {t['id'] for t in compose_rules(paths)['targets']}
    merged = {}
    for scope in SCOPES:
        if scope == 'work' and work is None:
            continue
        doc = read_json(_file(paths, work, kind, scope), {}) or {}
        for ident, item in (doc.get('items') or {}).items():
            entry = {k: v for k, v in item.items() if k != 'model_family'}
            merged[ident] = {
                **entry,
                'group': str(item.get('group') or ''),
                'targets': targets_of(item, known),
                'id': ident,
                'scope': scope,
                'overrides': ident in merged,
            }
    return merged


def compose_rules(paths):
    rules = read_json(paths.data / 'image' / 'compose.json', {}) or {}
    return {
        'order': rules.get('order')
        or ['common', 'style', 'composition', 'trigger', 'appearance', 'expression', 'outfit'],
        'slots': rules.get('slots') or [{'id': 'full', 'name': 'full'}],
        'ratings': rules.get('ratings') or [{'id': 'general', 'name': 'general'}],
        'targets': _clean_targets(rules.get('targets')) or DEFAULT_TARGETS,
    }


def _clean_targets(value):
    out, seen = [], set()
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict):
            continue
        ident = str(entry.get('id') or '').strip()
        name = str(entry.get('name') or '').strip()[:MAX_GROUP] or ident
        if ITEM_ID.match(ident) and ident not in seen:
            seen.add(ident)
            out.append({'id': ident, 'name': name})
    return out[:MAX_TARGETS]


def save_targets(paths, targets):
    """Replace the target list in the global compose.json. Items keep their choices; a target no longer listed is
    ignored, so an item written only for it fits every target again."""
    cleaned = _clean_targets(targets)
    if not cleaned:
        raise ValueError(Msg('server.image.library.targets', 'Keep at least one target.'))
    path = paths.data / 'image' / 'compose.json'
    doc = read_json(path, {}) or {'schema_version': 1}
    doc['targets'] = cleaned
    atomic_json(path, doc)
    return compose_rules(paths)


def _tags(value, name):
    if value is None:
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(',')]
    if not isinstance(value, list) or len(value) > MAX_TAGS or not all(isinstance(v, str) for v in value):
        raise ValueError(Msg('server.image.library.tags', '{name}: give a list of tags.', name=name))
    return list(dict.fromkeys(v.strip() for v in value if v.strip()))


def clean_item(kind, item, rules):
    """Keep only the fields this kind uses, with tags normalized (trimmed, de-duplicated, order kept)."""
    if not isinstance(item, dict):
        raise ValueError(Msg('server.image.library.item_object', 'The item must be an object.'))
    name = str(item.get('name') or '').strip()[:200]
    out = {
        'name': name,
        'prompt': _tags(item.get('prompt'), 'prompt'),
        'negative': _tags(item.get('negative'), 'negative'),
    }
    group = str(item.get('group') or '').strip()[:MAX_GROUP]
    if group:
        out['group'] = group
    targets = targets_of(item, {t['id'] for t in rules['targets']})
    if targets:
        out['targets'] = targets
    if kind == 'expressions':
        ratings = {r['id'] for r in rules['ratings']}
        out['rating'] = item.get('rating') if item.get('rating') in ratings else rules['ratings'][0]['id']
        if item.get('composition'):
            out['composition'] = str(item['composition'])
    elif kind == 'compositions':
        slots = {s['id'] for s in rules['slots']}
        out['suggest_slots'] = [s for s in item.get('suggest_slots') or [] if s in slots]
    elif kind == 'common':
        out['target'] = 'negative' if item.get('target') == 'negative' else 'positive'
        out['default'] = bool(item.get('default', True))
        out.pop('negative', None)
    elif kind == 'outfits':
        slots = {s['id'] for s in rules['slots']}
        if item.get('slot') not in slots:
            raise ValueError(Msg('server.image.library.slot', 'Choose a slot for the outfit part.'))
        out['slot'] = item['slot']
    return out


def save_item(paths, work, kind, scope, ident, item):
    _check_kind(kind)
    if not ITEM_ID.match(ident or ''):
        raise ValueError(Msg('server.image.library.item_id', "Use letters, digits, '_' and '-' for the id."))
    path = _file(paths, work, kind, scope)
    doc = read_json(path, {}) or {'schema_version': 1, 'items': {}}
    doc.setdefault('items', {})[ident] = clean_item(kind, item, compose_rules(paths))
    atomic_json(path, doc)
    return items(paths, work, kind)


def delete_item(paths, work, kind, scope, ident):
    _check_kind(kind)
    path = _file(paths, work, kind, scope)
    doc = read_json(path, {}) or {}
    if ident in (doc.get('items') or {}):
        del doc['items'][ident]
        atomic_json(path, doc)
    return items(paths, work, kind)


# --- generation presets (global): family, model and sampler settings, default common/style picks -----------------
def _presets_dir(paths):
    return paths.data / 'image' / 'presets'


def presets(paths):
    folder = _presets_dir(paths)
    out = []
    if folder.is_dir():
        for path in sorted(folder.glob('*.json')):
            doc = read_json(path, {}) or {}
            out.append({**doc, 'id': path.stem})
    return out


def save_preset(paths, ident, preset):
    if not ITEM_ID.match(ident or ''):
        raise ValueError(Msg('server.image.library.item_id', "Use letters, digits, '_' and '-' for the id."))
    if not isinstance(preset, dict):
        raise ValueError(Msg('server.image.library.item_object', 'The item must be an object.'))
    settings = preset.get('settings') if isinstance(preset.get('settings'), dict) else {}
    doc = {
        'schema_version': 1,
        'name': str(preset.get('name') or ident)[:200],
        'family': preset.get('family') if preset.get('family') in ('anima', 'sdxl') else 'anima',
        'settings': settings,
        'common': [str(x) for x in preset.get('common') or []],
        'styles': [str(x) for x in preset.get('styles') or []],
    }
    atomic_json(_presets_dir(paths) / f'{ident}.json', doc)
    return presets(paths)


def delete_preset(paths, ident):
    if ITEM_ID.match(ident or ''):
        (_presets_dir(paths) / f'{ident}.json').unlink(missing_ok=True)
    return presets(paths)
