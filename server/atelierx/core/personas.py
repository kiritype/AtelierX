"""User personas for the test screen (08-chat-test: 페르소나): one list for the whole app in ``data/personas.json``.

Which persona a work uses is screen state (``state/ui.json``), not work data, so it never goes into exports or snapshots.
"""

import secrets

from . import revisions
from .fsutil import read_json, write_json
from .i18n import AppError, Msg
from .works import now_iso

NAME_LIMIT = 100
DESCRIPTION_LIMIT = 20000


def _file(paths):
    return paths.data / 'personas.json'


def _revision(personas):
    return revisions.of([[p['id'], p['name'], p['description']] for p in personas])


def load(paths):
    doc = read_json(_file(paths), {}) or {}
    personas = [p for p in doc.get('personas', []) if isinstance(p, dict) and p.get('id')]
    return {'personas': personas, 'revision': _revision(personas)}


def save(paths, data):
    """Replace the list. ``base_revision`` must match the list the screen started from."""
    if not isinstance(data, dict) or not isinstance(data.get('personas'), list):
        raise AppError(Msg('server.personas.invalid', 'A persona list is required.'), 400)
    current = load(paths)
    if data.get('base_revision') != current['revision']:
        raise AppError(
            Msg('server.personas.stale', 'The persona list changed in another window. Reopen it.'), 409
        )
    before = {p['id']: p for p in current['personas']}
    out, seen = [], set()
    for entry in data['personas']:
        if not isinstance(entry, dict):
            raise AppError(Msg('server.personas.invalid', 'A persona list is required.'), 400)
        name = str(entry.get('name') or '').strip()
        description = str(entry.get('description') or '').replace('\r\n', '\n')
        if len(name) > NAME_LIMIT or len(description) > DESCRIPTION_LIMIT:
            raise AppError(
                Msg(
                    'server.personas.too_long',
                    'A persona name is at most {name} characters and a description at most {description}.',
                    name=NAME_LIMIT,
                    description=DESCRIPTION_LIMIT,
                ),
                400,
            )
        persona_id = str(entry.get('id') or '')
        if not persona_id or persona_id in seen or not persona_id.replace('-', '').isalnum():
            persona_id = f'p-{secrets.token_hex(4)}'
        seen.add(persona_id)
        old = before.get(persona_id)
        changed = not old or old['name'] != name or old['description'] != description
        out.append(
            {
                'id': persona_id,
                'name': name,
                'description': description,
                'updated_at': now_iso() if changed else old.get('updated_at'),
            }
        )
    write_json(_file(paths), {'schema_version': 1, 'personas': out})
    return {'personas': out, 'revision': _revision(out)}
