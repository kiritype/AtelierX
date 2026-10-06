"""Character image completeness board (#45): which outfit × expression combinations each character still needs.

A character needs every combination of its design's outfits and the work's expression library, less the ones marked
excluded. Each combination is missing (never made), generated (images but none adopted) or adopted; images waiting in
the queue are counted separately so the same combination is not queued twice. Exclusions are kept per work in
``.atelierx/image/board.json``.
"""

import copy
import json
import re
from collections import Counter

from ..core.i18n import Msg
from . import library
from .util import atomic_json, read_json

BOARD_FILE = 'board.json'
COMBO = re.compile(r'^[A-Za-z0-9_-]{1,64}/[A-Za-z0-9_-]{1,64}$')
WAITING = ('queued', 'running')


def _path(work):
    return work.app / 'image' / BOARD_FILE


def exclusions(work):
    """``{character_id: {'outfit/expression', …}}``."""
    doc = read_json(_path(work), {}) or {}
    return {
        str(cid): {str(c) for c in (entry or {}).get('excluded') or [] if COMBO.match(str(c))}
        for cid, entry in (doc.get('characters') or {}).items()
    }


def set_excluded(work, character_id, combos, excluded):
    """Mark ``combos`` ('outfit/expression') of a character as not needed, or needed again."""
    character_id = str(character_id or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', character_id):
        raise ValueError(Msg('server.board.bad_character', 'Choose a character.'))
    if not isinstance(combos, list) or not combos or any(not COMBO.match(str(c)) for c in combos):
        raise ValueError(Msg('server.board.bad_combo', 'Combinations are written as outfit/expression.'))
    current = exclusions(work)
    chosen = current.setdefault(character_id, set())
    chosen.update(combos) if excluded else chosen.difference_update(combos)
    atomic_json(
        _path(work),
        {
            'schema_version': 1,
            'characters': {cid: {'excluded': sorted(c)} for cid, c in sorted(current.items()) if c},
        },
    )
    return exclusions(work).get(character_id, set())


def _characters(work):
    """Characters in use that have an image design, with their outfits, in tree order."""
    out = []
    for item in work.index():
        cid = item['meta'].get('id')
        if item['kind'] != 'character' or not cid or not item['meta'].get('enabled', True):
            continue
        design = read_json(work.app / 'image' / 'characters' / cid / 'design.json') or {}
        outfits = [{'id': k, 'name': v.get('name', k)} for k, v in (design.get('outfits') or {}).items()]
        if outfits:
            out.append({'id': cid, 'name': item['name'], 'outfits': outfits})
    return out


def _adopted(runtime, images):
    """Combinations whose adopted image still exists."""
    paths = {i['path'] for i in images}
    with runtime.reviews.lock:
        adopted = copy.deepcopy(runtime.reviews.state.get('adopted') or {})
    return {tuple(json.loads(key)) for key, pointer in adopted.items() if pointer.get('path') in paths}


def board(runtime, work):
    expressions = [
        {'id': e['id'], 'name': e.get('name') or e['id'], 'rating': e.get('rating') or 'general'}
        for e in library.items(runtime.paths, work, 'expressions').values()
    ]
    images = [
        i for i in runtime.gallery.snapshot_items() if i['kind'] == 'image' and i.get('work_id') == work.id
    ]
    made = Counter((i.get('character_id'), i.get('outfit_id'), i.get('expression_id')) for i in images)
    adopted = _adopted(runtime, images)
    waiting = Counter(
        (j.get('character_id'), j.get('outfit_id'), j.get('expression_id'))
        for j in runtime.queue.select(
            lambda j: j.get('kind') is None and j.get('work_id') == work.id and j.get('status') in WAITING
        )
    )
    excluded = exclusions(work)
    characters, total_required, total_adopted = [], 0, 0
    for character in _characters(work):
        cid, cells, required, done = character['id'], {}, 0, 0
        for outfit in character['outfits']:
            for expression in expressions:
                combo = f'{outfit["id"]}/{expression["id"]}'
                key = (cid, outfit['id'], expression['id'])
                if combo in excluded.get(cid, set()):
                    state = 'excluded'
                elif (work.id, *key) in adopted:
                    state = 'adopted'
                elif made[key]:
                    state = 'generated'
                else:
                    state = 'missing'
                if state != 'excluded':
                    required += 1
                    done += state == 'adopted'
                cells[combo] = {'state': state, 'images': made[key], 'queued': waiting[key]}
        characters.append({**character, 'cells': cells, 'required': required, 'adopted': done})
        total_required += required
        total_adopted += done
    return {
        'expressions': expressions,
        'characters': characters,
        'required': total_required,
        'adopted': total_adopted,
    }


def adjust_export_plan(runtime, work, plan, filters):
    """The deployment export's missing list for one work: needed combinations without an adopted image (never made
    ones too), less the excluded ones. Combinations outside the board (a character without a design) stay as they were.
    """
    filters = filters or {}
    current = board(runtime, work)
    rating = {e['id']: e['rating'] for e in current['expressions']}
    on_board, missing = set(), []
    for character in current['characters']:
        for combo, cell in character['cells'].items():
            outfit, expression = combo.split('/')
            path = f'{work.id}/{character["id"]}/{combo}'
            on_board.add(path)
            if (
                (filters.get('character') and character['id'] != filters['character'])
                or (filters.get('outfit') and outfit != filters['outfit'])
                or (filters.get('rating') and rating.get(expression) != filters['rating'])
            ):
                continue
            if cell['state'] in ('missing', 'generated'):
                missing.append(path)
    others = [m for m in plan.get('missing') or [] if m not in on_board]
    return {**plan, 'missing': sorted(set(missing) | set(others))}
