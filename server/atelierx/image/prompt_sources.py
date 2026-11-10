"""Frozen, already-expanded prompt materials for single-image drafts and records."""

from ..core.i18n import Msg

KINDS = ('common', 'direct', 'character', 'expression', 'composition', 'style')


def normalize_sources(value, positive, negative):
    """Never resolve a saved material against today's library or strip it a second time."""
    invalid = Msg('server.single.sources', 'Choose valid prompt materials, with one entry per source.')
    if not isinstance(value, list) or len(value) > len(KINDS):
        raise ValueError(invalid)
    found = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(invalid)
        kind = item.get('kind')
        if not isinstance(kind, str) or kind not in KINDS or kind in found:
            raise ValueError(invalid)
        if any(
            not isinstance(item.get(key), str) or len(item[key]) > limit
            for key, limit in (('id', 256), ('name', 1000), ('positive', 30000), ('negative', 30000))
        ):
            raise ValueError(invalid)
        found[kind] = {key: item[key] for key in ('kind', 'id', 'name', 'positive', 'negative')}
    # Direct input has the usual note syntax; the other materials are final, frozen text.
    if 'direct' in found and (found['direct']['positive'], found['direct']['negative']) != (
        positive,
        negative,
    ):
        raise ValueError(invalid)
    found['direct'] = {'kind': 'direct', 'id': '', 'name': '', 'positive': positive, 'negative': negative}
    return [found[kind] for kind in KINDS if kind in found]


def combine_sources(sources, target):
    return ', '.join(source[target] for source in sources if source[target])
