"""The LoRAs a character uses (23-lora-training: 등록), in ``lora/models.json`` of the character.

An entry is an epoch of one of the character's training runs, or a LoRA file the server already has. An entry with
``auto_apply`` joins every generation of the character (``apply_to: character``) or only of one outfit
(``apply_to: outfit``), for its model family. At most one automatic entry per character / outfit and family.
"""

import math
import re
from pathlib import PureWindowsPath

from ...core.i18n import Msg
from ..util import read_json
from . import store

APPLY_TO = ('character', 'outfit')
FAMILIES = ('anima', 'sdxl', 'shared')
ENTRY_ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')


def _doc(work, character_id):
    data = read_json(store.models_file(work, character_id)) or {}
    return {'schema_version': 1, 'models': list(data.get('models') or [])}


def public(work, character_id):
    return _doc(work, character_id)


def _key(entry):
    outfit = entry.get('outfit_id') if entry.get('apply_to') == 'outfit' else None
    return (entry.get('apply_to', 'character'), outfit, entry.get('model_family', 'anima'))


def _check(entry):
    strength = entry.get('strength', 1.0)
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength):
        raise ValueError(Msg('server.records.strength_must_be_a_number', 'strength must be a number.'))
    if not -4 <= strength <= 4:
        raise ValueError(Msg('server.lora.strength_range', 'Strength must be between -4 and 4.'))
    if entry.get('apply_to', 'character') not in APPLY_TO:
        raise ValueError(
            Msg('server.records.apply_to_must_be_character_or', 'apply_to must be character or outfit.')
        )
    if entry.get('apply_to') == 'outfit' and not entry.get('outfit_id'):
        raise ValueError(Msg('server.lora.outfit_needed', 'Choose the outfit this LoRA applies to.'))
    if entry.get('model_family', 'anima') not in FAMILIES:
        raise ValueError(
            Msg(
                'server.records.model_family_must_be_anima_sdxl',
                'model_family must be anima, sdxl or shared.',
            )
        )
    if not isinstance(entry.get('file'), str) or not entry['file'].endswith('.safetensors'):
        raise ValueError(
            Msg('server.records.file_must_be_a_safetensors_file', 'file must be a .safetensors file name.')
        )


def _write(work, character_id, doc, changed):
    # Only one automatic LoRA per target: turning one on turns the others off.
    if changed.get('auto_apply'):
        for other in doc['models']:
            if other['id'] != changed['id'] and other.get('auto_apply') and _key(other) == _key(changed):
                other['auto_apply'] = False
    store.write(store.models_file(work, character_id), doc)
    return doc


def add(work, character_id, entry):
    doc = _doc(work, character_id)
    if not ENTRY_ID.match(str(entry.get('id', ''))):
        raise ValueError(Msg('server.lora.bad_id', 'Unknown record id: {id}', id=entry.get('id')))
    if any(m['id'] == entry['id'] for m in doc['models']):
        raise ValueError(Msg('server.lora.already_registered', '{id} is already registered.', id=entry['id']))
    entry = {
        'name': entry.get('name') or entry['id'],
        'strength': 1.0,
        'auto_apply': False,
        'apply_to': 'character',
        'model_family': 'anima',
        'enabled': True,
        **entry,
    }
    _check(entry)
    doc['models'].append(entry)
    return _write(work, character_id, doc, entry)


def update(work, character_id, ident, changes):
    doc = _doc(work, character_id)
    entry = next((m for m in doc['models'] if m['id'] == ident), None)
    if entry is None:
        raise ValueError(Msg('server.lora.missing', 'The record does not exist.'))
    for key in ('name', 'strength', 'auto_apply', 'apply_to', 'outfit_id', 'model_family', 'enabled'):
        if key in changes:
            entry[key] = changes[key]
    entry['auto_apply'] = bool(entry.get('auto_apply'))
    entry['enabled'] = bool(entry.get('enabled', True))
    _check(entry)
    return _write(work, character_id, doc, entry)


def remove(work, character_id, ident):
    doc = _doc(work, character_id)
    doc['models'] = [m for m in doc['models'] if m['id'] != ident]
    store.write(store.models_file(work, character_id), doc)
    return doc


def rename_file(works, old, new):
    """Point every character LoRA entry for the file ``old`` (by file name) at ``new``. Returns how many changed."""
    changed = 0
    for work in works:
        for path in (work.app / 'image' / 'characters').glob('*/lora/models.json'):
            doc = read_json(path) or {}
            entries = doc.get('models') or []
            hit = False
            for entry in entries:
                if PureWindowsPath(str(entry.get('file') or '')).name == old:
                    entry['file'] = new
                    hit = True
                    changed += 1
            if hit:
                store.write(path, {**doc, 'models': entries})
    return changed


def auto_loras(work, character_id, outfit_id, family):
    """The automatic LoRAs for one generation, in the queue's LoRA format."""
    found = []
    for entry in _doc(work, character_id)['models']:
        if not entry.get('enabled', True) or not entry.get('auto_apply'):
            continue
        if entry.get('model_family', 'anima') not in (family, 'shared'):
            continue
        if entry.get('apply_to') == 'outfit' and entry.get('outfit_id') != outfit_id:
            continue
        strength = float(entry.get('strength', 1.0))
        found.append(
            {
                'name': entry['file'],
                'strength_model': strength,
                'strength_clip': strength,
                'auto': entry['id'],
            }
        )
    return found
