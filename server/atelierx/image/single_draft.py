"""Portable standalone-image draft; independent of browser storage and work drafts."""

import json
import threading

from ..core import revisions
from ..core.fsutil import read_json, write_json
from ..core.i18n import Msg
from .prompt_sources import normalize_sources

LOCK = threading.RLock()
SERVICES = ('comfyui', 'novelai', 'pixai')


def read(paths):
    with LOCK:
        draft = read_json(paths.state / 'image' / 'single-draft.json')
        return {'draft': draft, 'revision': revisions.of(draft)}


def save(paths, body):
    invalid = Msg('server.single.draft_invalid', 'The image draft is invalid or too large.')
    if not isinstance(body, dict) or not isinstance(body.get('draft'), dict):
        raise ValueError(invalid)
    draft = body['draft']
    if (
        draft.get('schema_version') not in (3, 4)
        or draft.get('service') not in SERVICES
        or any(
            not isinstance(draft.get(k), str) or len(draft[k]) > limit
            for k, limit in (('positive', 30000), ('negative', 30000), ('preset', 256))
        )
        or not isinstance(draft.get('settings'), dict)
        or any(not isinstance(draft['settings'].get(s), dict) for s in SERVICES)
        or len(json.dumps(draft, ensure_ascii=False)) > 500000
    ):
        raise ValueError(invalid)
    sources = normalize_sources(draft.get('sources'), draft['positive'], draft['negative'])
    cleaned = {
        k: draft[k] for k in ('schema_version', 'positive', 'negative', 'service', 'settings', 'preset')
    }
    if draft.get('moss_layout') is not None:
        from .moss_layout import clean

        cleaned['moss_layout'] = clean(draft['moss_layout'])
        cleaned['schema_version'] = 4
    cleaned['sources'] = [source for source in sources if source['kind'] != 'direct']
    if draft.get('legacyPreset'):
        cleaned['legacyPreset'] = True
    with LOCK:
        revisions.check(
            body.get('revision'),
            read(paths)['revision'],
            Msg(
                'server.single.draft_stale',
                'This draft changed in another window. Reload it before saving again.',
            ),
        )
        write_json(paths.state / 'image' / 'single-draft.json', cleaned)
        return {'draft': cleaned, 'revision': revisions.of(cleaned)}
