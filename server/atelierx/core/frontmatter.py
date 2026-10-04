"""Metadata heads of items (decision 0005).

``.md`` files start with a YAML front matter block (``---`` … ``---``); ``.jsx`` files keep the same YAML in a leading
comment (``/*---`` … ``---*/``). Key order and unknown keys survive a round trip.
"""

import io

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

_yaml = YAML(typ='rt')
_yaml.default_flow_style = None
_yaml.width = 4096
_yaml.preserve_quotes = True

HEADS = {
    '.md': ('---\n', '\n---\n'),
    '.jsx': ('/*---\n', '\n---*/\n'),
}


class MetaError(ValueError):
    """The head exists but is not readable YAML."""


def split(text, suffix):
    """Return ``(meta, body, raw_head)``. ``meta`` is ``None`` when the file has no head."""
    text = text.replace('\r\n', '\n')
    start, end = HEADS[suffix]
    if not text.startswith(start):
        return None, text, ''
    stop = text.find(end, len(start) - 1)
    if stop < 0:
        raise MetaError('metadata head is not closed')
    raw = text[len(start) : stop]
    try:
        meta = _yaml.load(raw) if raw.strip() else CommentedMap()
    except Exception as error:  # ruamel raises several error types
        raise MetaError(str(error)) from error
    if not isinstance(meta, dict):
        raise MetaError('metadata head is not a mapping')
    body = text[stop + len(end) :]
    return meta, body, raw


def _flow_lists(meta):
    for key, value in meta.items():
        if isinstance(value, list) and hasattr(value, 'fa'):
            value.fa.set_flow_style()
        elif isinstance(value, list):
            from ruamel.yaml.comments import CommentedSeq

            seq = CommentedSeq(value)
            seq.fa.set_flow_style()
            meta[key] = seq
    return meta


def join(meta, body, suffix):
    """Build file text from ``meta`` (a mapping, may be empty) and ``body``."""
    start, end = HEADS[suffix]
    if meta is None:
        return body
    if not isinstance(meta, CommentedMap):
        meta = CommentedMap(meta)
    stream = io.StringIO()
    _yaml.dump(_flow_lists(meta), stream)
    head = stream.getvalue().rstrip('\n')
    return f'{start}{head}{end}{body}'


def to_plain(meta):
    """JSON-friendly copy of a ruamel mapping."""
    if meta is None:
        return None
    out = {}
    for key, value in meta.items():
        if isinstance(value, list):
            out[str(key)] = [
                v if isinstance(v, (str, int, float, bool)) or v is None else str(v) for v in value
            ]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value
        else:
            out[str(key)] = str(value)
    return out


def apply_changes(meta, changes):
    """Update ``meta`` in place with ``changes`` (``None`` removes a key), keeping order and unknown keys."""
    if meta is None:
        meta = CommentedMap()
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    return meta
