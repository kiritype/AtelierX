"""Character image design storage, validation, and conversion reconciliation."""

import hashlib
import json
import re
from copy import deepcopy

from ..core.fsutil import sha256_text
from ..core.i18n import AppError, Msg, message_of
from .library import clean_code


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


# Where a part's tags came from (#150): pieces of the character's text. "auto" pieces are the evidence a whole-text
# conversion quoted; "pick" pieces are ranges the person chose. Before #150 a source named a section and its hash.
SOURCE_BY = ('auto', 'pick')
MAX_SPAN = 8000
MAX_SPANS = 40


def _norm(text):
    return ' '.join(str(text).split())


def spans_of(part):
    """The text pieces of a part's source: ``[{text, by}]`` (empty for an old section source or none)."""
    source = (part or {}).get('source') or {}
    return [s for s in source.get('spans') or [] if isinstance(s, dict) and isinstance(s.get('text'), str)]


def picked(part):
    """Whether the person chose (a range of) this part's text, or wrote the part by hand: a whole-text conversion
    then leaves it as it is by default."""
    source = (part or {}).get('source')
    return not source or any(s.get('by') == 'pick' for s in spans_of(part))


def found_in(body, text):
    """Whether ``text`` is still in ``body``, ignoring how lines and spaces are broken."""
    needle = _norm(text)
    return bool(needle) and needle in _norm(body)


def part_status(work, body, part):
    """fresh: every piece of the source is in the text as it was; stale: a piece changed or is gone; manual: written by
    hand; unsourced: converted, but no quoted piece was found in the text. Old section sources are read as before."""
    source = (part or {}).get('source')
    if not source:
        return 'manual'
    if 'spans' in source:
        spans = spans_of(part)
        if not spans:
            return 'unsourced'
        return 'fresh' if all(found_in(body, s['text']) for s in spans) else 'stale'
    text = work.section_text(body, source.get('section'), source.get('heading'))
    if text is None:
        return 'broken'
    return 'fresh' if sha256_text(text) == source.get('hash') else 'stale'


def make_source(texts, by):
    return {'spans': [{'text': str(t)[:MAX_SPAN], 'by': by} for t in texts][:MAX_SPANS]}


def _valid_source(source):
    if source is None:
        return True
    if not isinstance(source, dict):
        return False
    if 'spans' in source:
        spans = source['spans']
        return isinstance(spans, list) and all(
            isinstance(s, dict) and isinstance(s.get('text'), str) and s.get('by') in SOURCE_BY for s in spans
        )
    return all(isinstance(v, (str, type(None))) for v in source.values())


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
    if not _valid_source(appearance.get('source')):
        invalid()
    for outfit_id, outfit in outfits.items():
        if not isinstance(outfit_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', outfit_id):
            invalid()
        if not isinstance(outfit, dict) or not isinstance(outfit.get('name', outfit_id), str):
            invalid()
        if 'code' in outfit:
            try:
                outfit['code'] = clean_code(outfit['code'])
            except ValueError as error:
                raise AppError(message_of(error), 400) from error
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
        if not _valid_source(outfit.get('source')):
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
        # The deployment code is not drawn from the text, so changing it keeps the outfit "from the text".
        previous_content = {k: v for k, v in previous_outfit.items() if k not in ('source', 'code')}
        new_content = {k: v for k, v in outfit.items() if k not in ('source', 'code')}
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


def new_outfit_id(taken):
    number = 1
    while f'o{number:02d}' in taken:
        number += 1
    return f'o{number:02d}'


def reconcile_conversion(previous, generated):
    """Keep outfit IDs stable. A conversion adds and updates outfits; outfits it does not name stay as they were (#150).
    The deployment code and the trigger the person gave stay too."""
    old = previous or {}
    result = deepcopy(generated)
    old_outfits = old.get('outfits') or {}
    retired = set(old.get('retired_outfit_ids') or [])
    new_outfits = {}
    used = set()

    def free(key):
        return key in old_outfits and key not in used

    for generated_id, outfit in (generated.get('outfits') or {}).items():
        source = outfit.get('source') or {}
        match = None
        if free(generated_id) and old_outfits[generated_id].get('name') == outfit.get('name'):
            match = generated_id
        if match is None and source.get('section'):
            # Before #150: the same outfit heading of the same section.
            match = next(
                (
                    key
                    for key, old_outfit in old_outfits.items()
                    if free(key)
                    and (old_outfit.get('source') or {}).get('section') == source.get('section')
                    and (old_outfit.get('source') or {}).get('heading') == source.get('heading')
                ),
                None,
            )
        if match is None:
            match = next(
                (key for key, old_outfit in old_outfits.items() if free(key) and old_outfit.get('name') == outfit.get('name')),
                None,
            )
        if match is None and generated_id not in old_outfits and generated_id not in retired and generated_id not in new_outfits:
            match = generated_id
        if match is None:
            match = new_outfit_id(set(old_outfits) | retired | set(new_outfits))
        used.add(match)
        # A conversion redraws the prompt; the deployment code the user gave stays.
        if 'code' in (old_outfits.get(match) or {}):
            outfit = {**outfit, 'code': old_outfits[match]['code']}
        new_outfits[match] = outfit

    for key, outfit in old_outfits.items():
        if key not in used:
            new_outfits[key] = deepcopy(outfit)
    result['outfits'] = new_outfits
    result['retired_outfit_ids'] = sorted(retired - set(new_outfits))
    if old.get('trigger'):
        result['trigger'] = old['trigger']
    if old.get('default_outfit') in new_outfits:
        result['default_outfit'] = old['default_outfit']
    elif new_outfits:
        result['default_outfit'] = next(iter(new_outfits))
    else:
        result['default_outfit'] = None
    validate(result)
    return result


def default_choice(previous, proposed, focus=None):
    """What adopting a conversion takes when the person did not choose part by part: converted parts, except that
    parts written by hand or from a chosen range keep their current content (the ``focus`` part of a range
    conversion is always taken)."""
    old = previous or {}
    design = deepcopy(proposed)
    if old.get('appearance') and focus != 'appearance' and picked(old['appearance']):
        if (old['appearance'].get('prompt') or old['appearance'].get('negative') or old['appearance'].get('source')):
            design['appearance'] = deepcopy(old['appearance'])
    for key, outfit in (old.get('outfits') or {}).items():
        if key in design.get('outfits', {}) and focus != f'outfit:{key}' and picked(outfit):
            design['outfits'][key] = deepcopy(outfit)
    return design
