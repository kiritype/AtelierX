"""Prompt library items shared as one JSON file of this app (#154): some or all items of one kind.

Importing reads the file first and shows each item as new or already here (by id), with what would change, and the
values this PC does not know (targets, slots, ratings, a composition). Those values are kept as they are; the person
then chooses per item to add, overwrite or skip, and where the items go (global or this work).
"""

from __future__ import annotations

import time

from .. import __version__
from ..core.i18n import Msg
from . import library
from .util import atomic_json, read_json
from .uuid_migration import canonical_for_save, resolve

FORMAT = 'atelierx-prompt-library'
MAX_ITEMS = 2000
FIELDS = (
    'name',
    'group',
    'targets',
    'prompt',
    'negative',
    'code',
    'rating',
    'composition',
    'suggest_slots',
    'hide_outfit',
    'target',
    'default',
    'slot',
)


@library.locked
def export(paths, work, kind, ids):
    """``(document, file name)`` of the chosen items of one kind (all when ``ids`` is empty), as the list shows them."""
    merged = library.items(paths, work, kind)
    chosen = [i for i in ids if i in merged] if ids else list(merged)
    if not chosen:
        raise ValueError(Msg('server.library.share.none', 'Choose the items to export.'))
    out = {}
    dependencies = {}
    for ident in chosen:
        item = merged[ident]
        # The stored item keeps targets this PC does not list (the merged view leaves them out).
        stored = _stored(paths, work, kind, item['scope']).get(ident)
        entry = _clean(paths, kind, ident, stored if isinstance(stored, dict) else item) or {}
        out[ident] = {**entry, 'scope': item['scope']}
        if kind == 'expressions' and entry.get('composition'):
            composition_id = entry['composition']
            composition = library.items(paths, work, 'compositions').get(composition_id)
            if composition:
                source = _stored(paths, work, 'compositions', composition['scope']).get(composition_id)
                dependencies[composition_id] = {
                    **(
                        _clean(
                            paths,
                            'compositions',
                            composition_id,
                            source if isinstance(source, dict) else composition,
                        )
                        or {}
                    ),
                    'scope': composition['scope'],
                }
    doc = {
        'kind': FORMAT,
        'schema_version': 1,
        'app_version': __version__,
        'library': kind,
        'exported_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'items': out,
        **({'dependencies': {'compositions': dependencies}} if dependencies else {}),
    }
    name = f'prompt-library-{kind}-{chosen[0] if len(chosen) == 1 else len(chosen)}-{time.strftime("%Y%m%d")}.json'
    return doc, name


def _stored(paths, work, kind, scope):
    if scope == 'work' and work is None:
        return {}
    return (read_json(library._file(paths, work, kind, scope), {}) or {}).get('items') or {}


def _rules_for(paths, item):
    """The rules of this PC, widened with the slot and rating the item names, so that a value this PC does not know
    is kept instead of replaced (the preview names it)."""
    rules = library.compose_rules(paths)
    slots = [s['id'] for s in rules['slots']]
    ratings = [r['id'] for r in rules['ratings']]
    extra_slots = [item.get('slot')] + list(item.get('suggest_slots') or [])
    for value in extra_slots:
        if isinstance(value, str) and library.ITEM_ID.match(value) and value not in slots:
            slots.append(value)
    rating = item.get('rating')
    if isinstance(rating, str) and library.ITEM_ID.match(rating) and rating not in ratings:
        ratings.append(rating)
    return {
        **rules,
        'slots': [{'id': s, 'name': s} for s in slots],
        'ratings': [{'id': r, 'name': r} for r in ratings],
    }


def _bad():
    return ValueError(Msg('server.library.share.bad', 'This file is not an AtelierX prompt library file.'))


def _read(kind, doc):
    """The file's items cleaned the way the library stores them, or a refusal that says what is wrong."""
    library._check_kind(kind)
    if not isinstance(doc, dict) or doc.get('kind') != FORMAT or not isinstance(doc.get('items'), dict):
        raise _bad()
    if doc.get('library') != kind:
        if doc.get('library') in library.KINDS:
            raise ValueError(
                Msg(
                    'server.library.share.other_kind',
                    'This file holds {found} items. Import it from that list.',
                    found=Msg(f'server.library.kind.{doc["library"]}', doc['library']),
                )
            )
        raise _bad()
    if len(doc['items']) > MAX_ITEMS:
        raise ValueError(
            Msg('server.library.share.too_many', 'The file has more than {count} items.', count=MAX_ITEMS)
        )
    return doc['items']


def _clean(paths, kind, ident, raw):
    if not library.ITEM_ID.match(str(ident)) or not isinstance(raw, dict):
        return None
    try:
        item = library.clean_item(kind, raw, _rules_for(paths, raw))
    except ValueError:
        return None
    # Targets this PC does not list are kept, so the item fits the same targets once they are added here.
    if isinstance(raw.get('targets'), list):
        wanted = [t for t in raw['targets'] if isinstance(t, str) and library.ITEM_ID.match(t)]
        if wanted:
            item['targets'] = list(dict.fromkeys(wanted))[: library.MAX_TARGETS]
    return item


def _unknown(paths, work, kind, item):
    """What the item names that this PC does not have: ``[{field, value}]``."""
    rules = library.compose_rules(paths)
    out = []
    known_targets = {t['id'] for t in rules['targets']}
    out += [{'field': 'targets', 'value': t} for t in item.get('targets') or [] if t not in known_targets]
    slots = {s['id'] for s in rules['slots']}
    if item.get('slot') and item['slot'] not in slots:
        out.append({'field': 'slot', 'value': item['slot']})
    out += [{'field': 'suggest_slots', 'value': s} for s in item.get('suggest_slots') or [] if s not in slots]
    if item.get('rating') and item['rating'] not in {r['id'] for r in rules['ratings']}:
        out.append({'field': 'rating', 'value': item['rating']})
    if item.get('composition') and item['composition'] not in library.items(paths, work, 'compositions'):
        out.append({'field': 'composition', 'value': item['composition']})
    return out


def _changes(old, new):
    """Fields that differ: ``[{field, old, new}]``."""
    out = []
    for field in FIELDS:
        before, after = old.get(field), new.get(field)
        if field == 'group':
            before, after = before or '', after or ''
        if field == 'targets':
            before, after = before or [], after or []
        if before != after:
            out.append({'field': field, 'old': before, 'new': after})
    return out


@library.locked
def preview(paths, work, kind, doc, scope):
    """Each item of the file: ``{id, name, scope (in the file), exists, here_scope, changes, unknown, shadowed}``."""
    raw_items = _read(kind, doc)
    if scope not in library.SCOPES or (scope == 'work' and work is None):
        raise ValueError(Msg('server.image.library.unknown_scope', 'Choose global or work.'))
    merged = library.items(paths, work, kind)
    target = _stored(paths, work, kind, scope)
    out, skipped = [], 0
    for ident, raw in raw_items.items():
        item = _clean(paths, kind, ident, raw)
        if item is None:
            skipped += 1
            continue
        canonical = resolve(paths, kind, ident, work.id if scope == 'work' and work else None)
        # Compared with what is stored where it would go, or else with what the list shows now.
        here = target.get(canonical)
        if here is not None:
            old = _clean(paths, kind, ident, here) or {}
        elif canonical in merged:
            old = {k: v for k, v in merged[canonical].items() if k in FIELDS}
        else:
            old = None
        out.append(
            {
                'id': ident,
                'revision': library.item_revision(paths, work, kind, canonical),
                'name': item['name'] or ident,
                'scope': raw.get('scope') if raw.get('scope') in library.SCOPES else None,
                'exists': old is not None,
                'here_scope': merged[canonical]['scope'] if canonical in merged else None,
                'changes': _changes(old, item) if old is not None else [],
                'unknown': _unknown(paths, work, kind, item),
                # A global item a work item of the same id keeps hiding in this work.
                'shadowed': scope == 'global'
                and work is not None
                and canonical in _stored(paths, work, kind, 'work'),
            }
        )
    if not out:
        raise _bad()
    return {'app_version': doc.get('app_version'), 'items': out, 'skipped': skipped}


@library.locked
def apply(paths, work, kind, doc, scope, choices, base_revisions=None):
    """``choices``: ``{id: 'add' | 'overwrite' | 'skip'}``; an id not named is added when new and skipped when here.
    Everything is checked before anything is written. Returns ``{written, items}``."""
    raw_items = _read(kind, doc)
    if scope not in library.SCOPES or (scope == 'work' and work is None):
        raise ValueError(Msg('server.image.library.unknown_scope', 'Choose global or work.'))
    merged = library.items(paths, work, kind)
    plan = {}
    pending = []
    for ident, raw in raw_items.items():
        item = _clean(paths, kind, ident, raw)
        if item is None:
            continue
        canonical = resolve(paths, kind, ident, work.id if scope == 'work' and work else None)
        choice = (choices or {}).get(ident, 'add')
        if choice not in ('add', 'overwrite', 'skip'):
            raise ValueError(
                Msg('server.library.share.bad_choice', 'Choose add, overwrite or skip for each item.')
            )
        if choice == 'skip' or (choice == 'add' and canonical in merged):
            continue
        library.revisions.check(
            (base_revisions or {}).get(ident), library.item_revision(paths, work, kind, canonical)
        )
        pending.append((ident, item))
    dependencies = {}
    if kind == 'expressions':
        raw_dependencies = (doc.get('dependencies') or {}).get('compositions') or {}
        for ident, item in pending:
            ref = item.get('composition')
            if ref and ref not in library.items(paths, work, 'compositions'):
                dependency = _clean(paths, 'compositions', ref, raw_dependencies.get(ref))
                if dependency:
                    dependencies[ref] = dependency
    for ident, item in pending:
        canonical = canonical_for_save(paths, kind, ident, scope, work.id if work else None)
        if kind == 'expressions' and item.get('composition'):
            item['composition'] = canonical_for_save(
                paths, 'compositions', item['composition'], scope, work.id if work else None
            )
        plan[canonical] = item
    if dependencies:
        comp_path = library._file(paths, work, 'compositions', scope)
        comp_doc = read_json(comp_path, {}) or {'schema_version': 2, 'items': {}}
        comp_doc['schema_version'] = 2
        for ident, item in dependencies.items():
            canonical = canonical_for_save(paths, 'compositions', ident, scope, work.id if work else None)
            comp_doc.setdefault('items', {}).setdefault(canonical, item)
        atomic_json(comp_path, comp_doc)
    if plan:
        path = library._file(paths, work, kind, scope)
        stored = read_json(path, {}) or {'schema_version': 1, 'items': {}}
        stored['schema_version'] = 2
        stored.setdefault('items', {}).update(plan)
        atomic_json(path, stored)
    return {'written': list(plan), 'items': library.items(paths, work, kind)}
