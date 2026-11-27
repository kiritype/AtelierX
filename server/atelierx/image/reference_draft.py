"""Portable image-only reference draft with optimistic revision checks."""

import json
import threading

from ..core import revisions
from ..core.fsutil import write_json
from ..core.i18n import Msg
from . import reference
from .util import read_json

LOCK = threading.RLock()
FAMILIES = ('anima', 'moss')
TEXT_FIELDS = (('positive', 30000), ('negative', 30000), ('description', 30000), ('guidance', 32))
INVALID = Msg('server.reference.draft_invalid', 'The reference draft is invalid or too large.')


def _path(paths):
    return paths.state / 'image' / 'reference-draft.json'


def read(paths):
    with LOCK:
        draft = read_json(_path(paths))
        return {'draft': draft, 'revision': revisions.of(draft)}


def _asset(assets, value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(INVALID)
    asset, _ = reference.data(assets, value.get('id'))
    return reference.public(None, asset)


def _validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError(INVALID)
    text = ('family', 'model', 'text_encoder', 'vae', 'sampler', 'scheduler', 'clip_type')
    numeric = ('steps', 'cfg', 'width', 'height', 'seed', 'clip_skip', 'shift')
    if any(value.get(key) is not None and not isinstance(value[key], str) for key in text):
        raise ValueError(INVALID)
    if any(value.get(key) is not None and type(value[key]) not in (int, float) for key in numeric):
        raise ValueError(INVALID)
    loras = value.get('loras')
    if loras is not None and (
        not isinstance(loras, list)
        or any(not isinstance(lora, dict) or not isinstance(lora.get('name'), str) for lora in loras)
    ):
        raise ValueError(INVALID)


def save(paths, body):
    if not isinstance(body, dict) or not isinstance(body.get('draft'), dict):
        raise ValueError(INVALID)
    draft = body['draft']
    parameters = draft.get('parameters')
    try:
        length = len(json.dumps(draft, ensure_ascii=False, allow_nan=False))
    except ValueError as error:
        raise ValueError(INVALID) from error
    if (
        draft.get('schema_version') != 1
        or draft.get('family') not in FAMILIES
        or draft.get('animaEngine') not in ('anima_v2', 'snapref')
        or draft.get('snaprefMode') not in ('cs', 'char')
        or not isinstance(draft.get('firstOnRight'), bool)
        or any(not isinstance(draft.get(key), str) or len(draft[key]) > limit for key, limit in TEXT_FIELDS)
        or not isinstance(parameters, dict)
        or length > 500000
    ):
        raise ValueError(INVALID)
    cleaned_parameters = {}
    for family in FAMILIES:
        item = parameters.get(family)
        if not isinstance(item, dict) or not isinstance(item.get('preset'), str) or len(item['preset']) > 256:
            raise ValueError(INVALID)
        _validate_settings(item.get('settings'))
        cleaned_parameters[family] = {'settings': item['settings'], 'preset': item['preset']}
    second = draft.get('second')
    if second is not None and (
        not isinstance(second, dict)
        or not isinstance(second.get('description'), str)
        or len(second['description']) > 30000
    ):
        raise ValueError(INVALID)
    assets = reference.asset_root(paths)
    cleaned = {
        key: draft[key]
        for key in (
            'schema_version',
            'family',
            'animaEngine',
            'snaprefMode',
            'firstOnRight',
            *(k for k, _ in TEXT_FIELDS),
        )
    }
    cleaned.update(
        parameters=cleaned_parameters,
        reference=_asset(assets, draft.get('reference')),
        second=None
        if second is None
        else {'reference': _asset(assets, second.get('reference')), 'description': second['description']},
    )
    with LOCK:
        revisions.check(
            body.get('revision'),
            read(paths)['revision'],
            Msg(
                'server.single.draft_stale',
                'This draft changed in another window. Reload it before saving again.',
            ),
        )
        write_json(_path(paths), cleaned)
        return {'draft': cleaned, 'revision': revisions.of(cleaned)}
