"""Datasets (22-datasets): images of one character picked for training, with a caption each.

Images are referenced by their path in the output root and their hash, never copied. Without a choice, a dataset
takes the adopted images of its outfits. A caption a person edited survives rebuilding.
"""

from ...core.i18n import Msg
from ..compose import design_of
from . import store
from .captions import caption, default_triggers


def candidates(rt, work, character_id, outfit_ids=None):
    """Every work image of the character (optionally only some outfits), adopted ones marked."""
    items = [
        rt.reviews.annotate(item)
        for item in rt.gallery.snapshot_items()
        if item['kind'] == 'image'
        and item['work_id'] == work.id
        and item['character_id'] == character_id
        and (not outfit_ids or item['outfit_id'] in outfit_ids)
    ]
    items.sort(key=lambda i: (i['outfit_id'], i['expression_id'], i['path']))
    return [
        {
            'path': i['path'],
            'sha256': i['sha256'],
            'outfit_id': i['outfit_id'],
            'expression_id': i['expression_id'],
            'expression_name': i['expression_name'],
            'human_status': i['human_status'],
            'adopted': i['adopted'],
            'thumbnail_url': i['thumbnail_url'],
            'image_url': i['image_url'],
        }
        for i in items
    ]


def _record(rt, path):
    try:
        return rt.gallery.metadata(path)
    except ValueError as error:
        raise ValueError(
            Msg(
                'server.datasets.images_without_a_record_cannot_be',
                'Images without a record cannot be used for training: {path}',
                path=path,
            )
        ) from error


def _triggers(value):
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise ValueError(Msg('server.datasets.triggers', 'Triggers must be text.'))
    return {'character': value.get('character', '').strip(), 'outfit': value.get('outfit', '').strip()}


def save(rt, work, character_id, body):
    """Create or rebuild a dataset. ``paths`` None takes the adopted images of the chosen outfits."""
    existing = store.datasets(work, character_id)
    ident = body.get('id') or store.next_id(existing, 'D')
    previous = next((d for d in existing if d['id'] == ident), None) or {}
    outfits = body.get('outfits', previous.get('outfits')) or []
    if not isinstance(outfits, list) or not all(isinstance(o, str) for o in outfits):
        raise ValueError(Msg('server.datasets.outfits', 'Choose the outfits of the dataset.'))
    design = design_of(work, character_id)
    triggers = _triggers(
        body.get('triggers')
        or previous.get('triggers')
        or default_triggers(work.id, character_id, design, outfits)
    )
    pool = {c['path']: c for c in candidates(rt, work, character_id, outfits)}
    paths = body.get('paths')
    if paths is None:
        paths = [p for p, c in pool.items() if c['adopted']]
    if not isinstance(paths, list) or not paths:
        raise ValueError(
            Msg(
                'server.datasets.choose_images_for_the_dataset_without',
                'Choose images for the dataset. Without adopted images, pick them yourself.',
            )
        )
    kept = {i['image']['path']: i for i in previous.get('items', [])}
    items = []
    for path in dict.fromkeys(paths):
        found = pool.get(path)
        if found is None:
            raise ValueError(
                Msg(
                    'server.datasets.not_an_image_of_this_outfit',
                    'Not an image of these outfits: {path}',
                    path=path,
                )
            )
        meta = _record(rt, path)
        old = kept.get(path)
        edited = bool(old and old.get('edited'))
        items.append(
            {
                'image': {
                    'root': 'output',
                    'path': path,
                    'sha256': found['sha256'],
                    'size': rt.gallery.safe_path(path).stat().st_size,
                },
                'outfit_id': found['outfit_id'],
                'expression_id': found['expression_id'],
                'caption': old['caption'] if edited else caption(meta, triggers),
                'edited': edited,
            }
        )
    data = {
        'schema_version': 1,
        'name': str(
            body.get('name')
            or previous.get('name')
            or ', '.join((design.get('outfits') or {}).get(o, {}).get('name', o) for o in outfits)
            or ident
        )[:200],
        'outfits': outfits,
        'triggers': triggers,
        'items': items,
    }
    store.write(store.dataset_file(work, character_id, ident), data)
    return {**data, 'id': ident}


def edit_captions(rt, work, character_id, body):
    """Save captions a person changed (``items``: path → caption) or rebuild the automatic ones (``rebuild``)."""
    path = store.dataset_file(work, character_id, body.get('id'))
    data = store.read(path)
    if body.get('triggers'):
        data['triggers'] = _triggers(body['triggers'])
    changes = body.get('items') or {}
    if not isinstance(changes, dict):
        raise ValueError(Msg('server.datasets.captions', 'Captions must map image paths to text.'))
    for item in data['items']:
        image = item['image']['path']
        if image in changes:
            text = str(changes[image]).strip()
            if text != item['caption']:
                item.update(caption=text, edited=True)
        elif body.get('rebuild') and not item.get('edited'):
            item['caption'] = caption(_record(rt, image), data['triggers'])
        if body.get('reset_edits') and image not in changes:
            item.update(caption=caption(_record(rt, image), data['triggers']), edited=False)
    store.write(path, data)
    return data


def delete(work, character_id, ident):
    store.dataset_file(work, character_id, ident).unlink(missing_ok=True)
    return {'deleted': ident}
