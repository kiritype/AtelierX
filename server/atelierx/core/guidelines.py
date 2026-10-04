"""Guidelines with fixed names (data-model: 정해진 이름), looked up work → linked presets in tag order → global."""

from .fsutil import atomic_write_text, sha256_text
from .i18n import AppError, Msg

COMPRESSION_GUIDELINE = 'compression.md'


def compression_settings(paths):
    """Return the editable global compression guideline and its immutable default."""
    saved = paths.data / 'guidelines' / COMPRESSION_GUIDELINE
    default = paths.defaults / 'guidelines' / COMPRESSION_GUIDELINE
    text = saved.read_text(encoding='utf-8') if saved.is_file() else ''
    default_text = default.read_text(encoding='utf-8') if default.is_file() else ''
    return {'text': text, 'default_text': default_text, 'revision': sha256_text(text)}


def save_compression_settings(paths, data):
    """Save only the fixed global guideline path using optimistic concurrency."""
    if (
        not isinstance(data, dict)
        or not isinstance(data.get('text'), str)
        or not isinstance(data.get('base_revision'), str)
    ):
        raise AppError(Msg('server.guidelines.invalid', 'A text value and base revision are required.'), 400)
    current = compression_settings(paths)
    if data['base_revision'] != current['revision']:
        raise AppError(
            Msg('server.guidelines.stale', 'The compression guideline changed after it was loaded.'), 409
        )
    path = paths.data / 'guidelines' / COMPRESSION_GUIDELINE
    atomic_write_text(path, data['text'])
    return compression_settings(paths)


def find(work, paths, linked, name):
    candidates = [work.app / 'guidelines' / name]
    candidates += [paths.platforms / preset / 'guidelines' / name for preset in linked]
    candidates.append(paths.data / 'guidelines' / name)
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding='utf-8')
    return ''
