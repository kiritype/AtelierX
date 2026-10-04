"""Character image design storage, validation, and conversion reconciliation."""

import hashlib
import json
import re
from copy import deepcopy

from ..core.i18n import AppError, Msg


def character_design_path(work, character_id):
    """Return a contained design path for a syntactically safe character ID."""
    if not isinstance(character_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', character_id):
        raise AppError(
            Msg('server.image.no_character', 'Character {id} was not found.', id=character_id), 404
        )
    app_root = work.app.resolve()
    unresolved_root = app_root / 'image' / 'characters'
    root = unresolved_root.resolve()
    try:
        root.relative_to(app_root)
    except ValueError:
        raise AppError(
            Msg('server.image.no_character', 'Character {id} was not found.', id=character_id), 404
        ) from None
    path = (root / character_id / 'design.json').resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise AppError(
            Msg('server.image.no_character', 'Character {id} was not found.', id=character_id), 404
        ) from None
    return path


def revision(design):
    if design is None:
        return None
    raw = json.dumps(design, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def validate(design):
    def invalid():
        raise AppError(Msg('server.image.design.invalid', 'The image design is invalid.'), 400)

    if not isinstance(design, dict):
        invalid()
    appearance = design.get('appearance')
    outfits = design.get('outfits')
    if not isinstance(appearance, dict) or not isinstance(outfits, dict):
        invalid()
    if 'trigger' in design and not isinstance(design['trigger'], str):
        invalid()

    def tags(value):
        return isinstance(value, list) and all(isinstance(tag, str) for tag in value)

    if not tags(appearance.get('prompt', [])) or not tags(appearance.get('negative', [])):
        invalid()
    source = appearance.get('source')
    if source is not None and (
        not isinstance(source, dict) or any(not isinstance(v, (str, type(None))) for v in source.values())
    ):
        invalid()
    for outfit_id, outfit in outfits.items():
        if not isinstance(outfit_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', outfit_id):
            invalid()
        if not isinstance(outfit, dict) or not isinstance(outfit.get('name', outfit_id), str):
            invalid()
        if not tags(outfit.get('negative', [])):
            invalid()
        slots = outfit.get('slots', {})
        if not isinstance(slots, dict):
            invalid()
        for slot, entry in slots.items():
            if not isinstance(slot, str) or not isinstance(entry, dict):
                invalid()
            prompt = entry.get('prompt', [])
            if not tags(entry.get('negative', [])):
                invalid()
            ref = entry.get('ref')
            if not tags(prompt) or (
                ref is not None
                and (
                    not isinstance(ref, str) or not re.fullmatch(r'(?:work|global):[A-Za-z0-9_-]{1,64}', ref)
                )
            ):
                invalid()
        source = outfit.get('source')
        if source is not None and (
            not isinstance(source, dict) or any(not isinstance(v, (str, type(None))) for v in source.values())
        ):
            invalid()
    default = design.get('default_outfit')
    if default is not None and default not in outfits:
        invalid()
    retired = design.get('retired_outfit_ids', [])
    if not isinstance(retired, list) or not all(isinstance(x, str) for x in retired):
        invalid()
    if set(retired) & set(outfits):
        invalid()
    return design


def prepare_update(previous, submitted):
    """Preserve unknown fields and source metadata only for untouched parts."""
    validate(submitted)
    old = previous or {}
    result = deepcopy(old)
    result.update(deepcopy(submitted))
    old_appearance = old.get('appearance') or {}
    appearance = deepcopy(submitted['appearance'])
    old_content = {k: v for k, v in old_appearance.items() if k != 'source'}
    new_appearance_content = {k: v for k, v in appearance.items() if k != 'source'}
    if old_appearance.get('source') and old_content == new_appearance_content:
        appearance['source'] = deepcopy(old_appearance['source'])
    else:
        appearance.pop('source', None)
    result['appearance'] = appearance

    old_outfits = old.get('outfits') or {}
    new_outfits = deepcopy(submitted['outfits'])
    for key, outfit in new_outfits.items():
        previous_outfit = old_outfits.get(key) or {}
        previous_content = {k: v for k, v in previous_outfit.items() if k != 'source'}
        new_content = {k: v for k, v in outfit.items() if k != 'source'}
        if previous_outfit.get('source') and previous_content == new_content:
            outfit['source'] = deepcopy(previous_outfit['source'])
        else:
            outfit.pop('source', None)
    retired = set(old.get('retired_outfit_ids') or [])
    retired.update(set(old_outfits) - set(new_outfits))
    retired.update(submitted.get('retired_outfit_ids') or [])
    result['retired_outfit_ids'] = sorted(retired)
    result['outfits'] = new_outfits
    validate(result)
    return result


def reconcile_conversion(previous, generated):
    """Keep IDs stable and retain manually managed parts absent from source conversion."""
    old = previous or {}
    result = deepcopy(generated)
    old_outfits = old.get('outfits') or {}
    retired = set(old.get('retired_outfit_ids') or [])
    available = {key: value for key, value in old_outfits.items()}
    new_outfits = {}
    used = set()
    for generated_id, outfit in (generated.get('outfits') or {}).items():
        source = outfit.get('source') or {}
        match = next(
            (
                key
                for key, old_outfit in available.items()
                if key not in used
                and (old_outfit.get('source') or {}).get('heading') == source.get('heading')
                and (old_outfit.get('source') or {}).get('section') == source.get('section')
            ),
            None,
        )
        if match is None:
            match = next(
                (
                    key
                    for key, old_outfit in available.items()
                    if key not in used and old_outfit.get('name') == outfit.get('name')
                ),
                None,
            )
        if match is None and generated_id not in old_outfits and generated_id not in retired:
            match = generated_id
        if match is None:
            number = 1
            while (
                f'o{number:02d}' in old_outfits
                or f'o{number:02d}' in retired
                or f'o{number:02d}' in new_outfits
            ):
                number += 1
            match = f'o{number:02d}'
        used.add(match)
        new_outfits[match] = outfit

    # Source-free parts are user-created and should survive conversion.
    for key, outfit in old_outfits.items():
        if key not in used and not outfit.get('source'):
            new_outfits[key] = deepcopy(outfit)
    result['outfits'] = new_outfits
    result['retired_outfit_ids'] = sorted(retired | (set(old_outfits) - set(new_outfits)))
    if old.get('trigger'):
        result['trigger'] = old['trigger']
    if old.get('default_outfit') in new_outfits:
        result['default_outfit'] = old['default_outfit']
    elif new_outfits:
        result['default_outfit'] = next(iter(new_outfits))
    validate(result)
    return result
