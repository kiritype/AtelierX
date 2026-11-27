"""Freeze image-only emotion and composition prompts before adding a reference batch."""

from ..core import revisions
from ..core.i18n import Msg
from . import library
from .compose import _join
from .uuid_migration import resolve

FAMILIES = ('anima', 'moss')
INVALID_SELECTION = Msg(
    'server.reference.emotions_selection', 'Choose at least one emotion prompt for the current model family.'
)
INVALID_COMPOSITION = Msg(
    'server.reference.emotions_composition', 'Choose a composition for the current model family.'
)
STALE = Msg(
    'server.reference.emotions_stale', 'An emotion or composition changed. Preview the combinations again.'
)


def _find(paths, items, kind, ident):
    if not isinstance(ident, str) or not ident:
        return None
    return items.get(ident) or items.get(resolve(paths, kind, ident))


def _compatible_composition(item, family):
    return item is not None and item.get('moss_layout') is None and library.fits(item, family)


def _prompt(expression, composition, key):
    return ', '.join(_join(composition.get(key), expression.get(key)))


@library.locked
def preview(paths, body):
    if not isinstance(body, dict) or body.get('family') not in FAMILIES:
        raise ValueError(INVALID_SELECTION)
    family = body['family']
    ids = body.get('expression_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(ident, str) for ident in ids):
        raise ValueError(INVALID_SELECTION)
    choice = body.get('composition', {'mode': 'none'})
    if not isinstance(choice, dict) or choice.get('mode') not in ('none', 'linked', 'library'):
        raise ValueError(INVALID_COMPOSITION)
    mode = choice['mode']
    expressions = library.items(paths, None, 'expressions')
    compositions = library.items(paths, None, 'compositions') if mode != 'none' else {}
    common = _find(paths, compositions, 'compositions', choice.get('id')) if mode == 'library' else None
    if mode == 'library' and not _compatible_composition(common, family):
        raise ValueError(INVALID_COMPOSITION)
    rows, seen = [], set()
    for ident in ids:
        expression = _find(paths, expressions, 'expressions', ident)
        if expression is None or expression['id'] in seen or not library.fits(expression, family):
            raise ValueError(INVALID_SELECTION)
        seen.add(expression['id'])
        linked = expression.get('composition') if mode == 'linked' else None
        composition = _find(paths, compositions, 'compositions', linked) if linked else common
        if not _compatible_composition(composition, family):
            composition = None
        source = composition or {}
        name = expression.get('name') or expression['id']
        positive = _prompt(expression, source, 'prompt')
        negative = _prompt(expression, source, 'negative')
        if not positive:
            raise ValueError(
                Msg('server.reference.emotions_empty', 'A positive prompt is required for {name}.', name=name)
            )
        if max(len(positive), len(negative)) > 30000:
            raise ValueError(
                Msg('server.single.prompt_length', 'Prompts must be text of at most 30,000 characters.')
            )
        rows.append(
            {
                'expression_id': expression['id'],
                'expression_name': name,
                'composition_id': source.get('id'),
                'composition_name': source.get('name'),
                'composition_omitted': bool(linked and composition is None),
                'positive': positive,
                'negative': negative,
            }
        )
    return {'rows': rows, 'revision': revisions.of({'family': family, 'rows': rows})}
