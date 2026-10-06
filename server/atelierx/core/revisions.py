"""Save conflicts (data-model: 저장 충돌, #90): a screen saves with the revision it loaded, and a save over a newer
version is refused with 409 so nothing done elsewhere (another window, an adopted draft) is silently overwritten.

A file of the work uses the hash of its text (``base_hash``); app data kept as one JSON document uses ``revision`` here.
"""

import json

from .fsutil import sha256_text
from .i18n import AppError, Msg


def of(value):
    """The revision of a JSON-like value: the same content gives the same revision, whatever the key order."""
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def check(base, current, msg=None):
    """Refuse a save whose ``base`` is not the revision now stored."""
    if base != current:
        raise AppError(
            msg
            or Msg(
                'server.save.stale',
                'This was changed elsewhere after you opened it. It has been reloaded; make your change again.',
            ),
            409,
        )
