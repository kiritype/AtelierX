"""Versioned editable MOSS layouts and the native model's prompt contract (#307).

Rectangles use normalized upper-left xywh coordinates. Only compile() knows the
model's centered yxyx contract; editor metadata never enters that JSON.
"""

import copy
import json
import math

from ..core.i18n import Msg

MAX_ITEMS = 32
MAX_PROMPT = 30000


def invalid(field):
    return ValueError(Msg('server.moss.layout_invalid', 'Invalid MOSS layout: {field}.', field=field))


def text(value, field, limit=10000):
    if not isinstance(value, str) or len(value) > limit:
        raise invalid(field)
    return value


def clean(value, *, complete=False):
    """Validate even inactive drafts, allowing unfinished captions until generation."""
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise invalid('schema_version')
    scene = text(value.get('scene'), 'scene')
    mode = value.get('mode')
    if mode not in ('general', 'layout'):
        raise invalid('mode')
    out = {'schema_version': 1, 'mode': mode, 'scene': scene, 'items': []}
    for key in ('width', 'height'):
        number = value.get(key)
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or not 256 <= number <= 3072
            or number % 16
        ):
            raise invalid(key)
        out[key] = number
    items = value.get('items')
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise invalid('items')
    seen = set()
    for index, item in enumerate(items):
        field = f'items[{index + 1}]'
        if not isinstance(item, dict):
            raise invalid(field)
        ident = text(item.get('id'), field + '.id', 100)
        if not ident or ident in seen:
            raise invalid(field + '.id')
        seen.add(ident)
        label = item.get('label')
        binding = item.get('binding', 'manual')
        if label not in ('character', 'object', 'text') or binding not in ('manual', 'target'):
            raise invalid(field + '.label/binding')
        if binding == 'target' and label != 'character':
            raise invalid(field + '.binding')
        rect = item.get('rect')
        if (
            not isinstance(rect, list)
            or len(rect) != 4
            or any(
                isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in rect
            )
        ):
            raise invalid(field + '.rect')
        x, y, w, h = rect
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
            raise invalid(field + '.rect')
        entry = {
            'id': ident,
            'label': label,
            'name': text(item.get('name', ''), field + '.name', 200),
            'caption': text(item.get('caption', ''), field + '.caption'),
            'binding': binding,
            'rect': list(rect),
        }
        if label == 'text':
            entry['text'] = text(item.get('text', ''), field + '.text', 4000)
            if complete and not entry['text'].strip():
                raise invalid(field + '.text')
        if binding == 'target' and item.get('resolved') is not None:
            resolved = item['resolved']
            if not isinstance(resolved, dict):
                raise invalid(field + '.resolved')
            entry['resolved'] = {
                k: text(resolved.get(k, ''), field + '.resolved.' + k)
                for k in ('caption', 'negative', 'character_id', 'outfit_id', 'expression_id', 'name')
            }
        caption = join(entry.get('resolved', {}).get('caption', ''), entry['caption'])
        if complete and (
            not caption.strip()
            or (binding == 'target' and not entry.get('resolved', {}).get('caption', '').strip())
        ):
            raise invalid(field + '.caption')
        out['items'].append(entry)
    if complete and (not scene.strip() or not items):
        raise invalid('scene/items')
    if len(json.dumps(out, ensure_ascii=False)) > 100000:
        raise invalid('size')
    return out


def join(*parts):
    return ', '.join(part.strip() for part in parts if part and part.strip())


def resolved_target(snapshot):
    parts = snapshot['parts']
    return {
        **{key: snapshot.get(key, '') for key in ('character_id', 'outfit_id', 'expression_id')},
        'name': join(
            snapshot.get('character_id', ''),
            snapshot.get('outfit_name', ''),
            snapshot.get('expression_name', ''),
        ),
        'caption': join(*(parts.get(key, '') for key in ('trigger', 'appearance', 'outfit', 'expression'))),
        'negative': snapshot.get('negative', ''),
    }


def prepare(value, settings, target=None, scene_material=''):
    doc = clean(value)
    if doc['mode'] != 'layout':
        return doc, None
    doc.update(width=settings.get('width', 1024), height=settings.get('height', 1024))
    if target is not None:
        for item in doc['items']:
            if item['binding'] == 'target':
                item['resolved'] = copy.deepcopy(resolved_target(target))
    compiled_doc = {**doc, 'scene': join(doc['scene'], scene_material)}
    return doc, compile_layout(compiled_doc)


def compile_layout(value):
    doc = clean(value, complete=True)
    width, height = doc['width'], doc['height']
    items = []
    for item in doc['items']:
        x, y, w, h = item['rect']
        entry = {
            'label': item['label'],
            'caption': join(item.get('resolved', {}).get('caption', ''), item['caption']),
            'bbox': [
                math.floor(round(y * height, 9)) - height // 2,
                math.floor(round(x * width, 9)) - width // 2,
                math.ceil(round((y + h) * height, 9)) - height // 2,
                math.ceil(round((x + w) * width, 9)) - width // 2,
            ],
        }
        if item['label'] == 'text':
            entry['text'] = item['text']
        items.append(entry)
    result = json.dumps(
        {
            'summary': {'caption': doc['scene']},
            'items': items,
            'bbox_coord_space': 'abs_centralized',
            'bbox_format': 'yxyx',
        },
        ensure_ascii=False,
        separators=(',', ':'),
    )
    if len(result) > MAX_PROMPT:
        raise invalid('prompt length')
    return result
