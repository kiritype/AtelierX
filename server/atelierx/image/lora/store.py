"""Where a character's LoRA records live in the work folder.

.atelierx/image/characters/<C>/datasets/<D###>.json   images chosen for training + captions
.atelierx/image/characters/<C>/lora/runs/<R###>.json  one training run
.atelierx/image/characters/<C>/lora/models.json       the LoRAs this character uses
"""

import re

from ...core.i18n import Msg
from ..util import atomic_json, code, read_json

RECORD_ID = re.compile(r'^[A-Z]\d{3,}$')


def character_dir(work, character_id):
    return work.app / 'image' / 'characters' / code(character_id)


def record_id(value):
    if not isinstance(value, str) or not RECORD_ID.match(value):
        raise ValueError(Msg('server.lora.bad_id', 'Unknown record id: {id}', id=value))
    return value


def dataset_file(work, character_id, ident):
    return character_dir(work, character_id) / 'datasets' / f'{record_id(ident)}.json'


def run_file(work, character_id, ident):
    return character_dir(work, character_id) / 'lora' / 'runs' / f'{record_id(ident)}.json'


def models_file(work, character_id):
    return character_dir(work, character_id) / 'lora' / 'models.json'


def _list(folder):
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob('*.json')):
        data = read_json(path)
        if isinstance(data, dict):
            out.append({**data, 'id': path.stem})
    return out


def datasets(work, character_id):
    return _list(character_dir(work, character_id) / 'datasets')


def runs(work, character_id):
    return _list(character_dir(work, character_id) / 'lora' / 'runs')


def next_id(existing, prefix):
    """The first free code like D001 / R001."""
    used = {item.get('id') for item in existing}
    number = 1
    while f'{prefix}{number:03d}' in used:
        number += 1
    return f'{prefix}{number:03d}'


def write(path, data):
    atomic_json(path, {k: v for k, v in data.items() if k != 'id'})


def read(path):
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(Msg('server.lora.missing', 'The record does not exist.'))
    return {**data, 'id': path.stem}
