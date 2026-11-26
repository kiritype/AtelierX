"""Portable cover copies for one work, written as an atomic archive."""

import json
from contextlib import contextmanager
from io import BytesIO
from pathlib import PureWindowsPath
from re import fullmatch
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from PIL import Image, ImageOps

from . import revisions
from .fsutil import atomic_write_bytes, sha256_bytes
from .i18n import AppError, Msg

FILENAME = 'covers.zip'
MANIFEST = 'manifest.json'
MAX_COVERS = 16
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 64 * 1024 * 1024
MAX_EDGE = 960
MAX_WEBP_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
MAX_ARCHIVE_BYTES = MAX_COVERS * MAX_WEBP_BYTES + 2 * MAX_MANIFEST_BYTES
FORMATS = ('PNG', 'JPEG', 'WEBP')


def _damaged():
    return AppError(Msg('server.covers.damaged', 'The work cover archive could not be read.'))


def _invalid_image():
    return AppError(
        Msg('server.covers.invalid_image', 'Choose a still PNG, WebP, or JPEG image of 32 MB or less.')
    )


def too_large():
    return AppError(Msg('server.covers.too_large', 'The image must be 32 MB or less.'), 413)


def _bad_order():
    return AppError(Msg('server.covers.bad_order', 'Choose only covers that belong to this work.'))


def _missing():
    return AppError(Msg('server.covers.missing', 'This work cover is missing.'), 404)


def _valid_id(ident):
    return isinstance(ident, str) and fullmatch(r'[0-9a-f]{64}', ident) is not None


def _path(work):
    path = work.app / FILENAME
    resolved = path.resolve()
    if (
        path.is_symlink()
        or resolved.parent != work.app.resolve()
        or work.folder.resolve() not in resolved.parents
    ):
        raise _damaged()
    return path


@contextmanager
def _open(work):
    try:
        path = _path(work)
        if not path.exists():
            yield None
            return
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise _damaged()
        with ZipFile(path) as archive:
            yield archive
    except (OSError, ValueError, KeyError, RuntimeError, BadZipFile) as error:
        raise _damaged() from error


def _manifest(items, primary_id):
    return {'schema_version': 1, 'items': items, 'primary_id': primary_id}


def _state(archive):
    if archive is None:
        return _manifest([], None), {}
    members = {info.filename: info for info in archive.infolist()}
    if (
        len(members) != len(archive.infolist())
        or len(members) > MAX_COVERS + 1
        or MANIFEST not in members
        or members[MANIFEST].file_size > MAX_MANIFEST_BYTES
    ):
        raise _damaged()
    doc = json.loads(archive.read(MANIFEST))
    if (
        not isinstance(doc, dict)
        or doc.get('schema_version') != 1
        or not isinstance(doc.get('items'), list)
        or len(doc['items']) > MAX_COVERS
    ):
        raise _damaged()
    items, seen, files = [], set(), {}
    for item in doc['items']:
        if (
            not isinstance(item, dict)
            or not _valid_id(item.get('id'))
            or not isinstance(item.get('name'), str)
        ):
            raise _damaged()
        ident = item['id']
        if ident in seen or not 1 <= len(item['name']) <= 180:
            raise _damaged()
        seen.add(ident)
        items.append({'id': ident, 'name': item['name']})
        info = members.get(f'{ident}.webp')
        if info is not None and 0 < info.file_size <= MAX_WEBP_BYTES:
            files[ident] = info
    primary = doc.get('primary_id')
    if primary is not None and (not _valid_id(primary) or primary not in seen):
        raise _damaged()
    return _manifest(items, primary), files


def _image_url(work_id, ident):
    return f'/api/works/{quote(work_id, safe="")}/covers/{ident}'


def _public(work_id, doc, files):
    return {
        'items': [
            {**item, 'url': _image_url(work_id, item['id'])} for item in doc['items'] if item['id'] in files
        ],
        'primary_id': doc['primary_id'] if doc['primary_id'] in files else None,
        'revision': revisions.of(doc),
    }


def view(work):
    with _open(work) as archive:
        doc, files = _state(archive)
    return _public(work.id, doc, files)


def primary_url(work, work_id):
    try:
        with _open(work) as archive:
            doc, files = _state(archive)
        primary = doc['primary_id']
        return _image_url(work_id, primary) if primary in files else None
    except AppError:
        return None


def _read_image(archive, info, ident):
    raw = archive.read(info)
    if raw[:4] != b'RIFF' or raw[8:12] != b'WEBP' or sha256_bytes(raw) != ident:
        raise _damaged()
    return raw


def image(work, ident):
    if not _valid_id(ident):
        raise _missing()
    with _open(work) as archive:
        _, files = _state(archive)
        if ident not in files:
            raise _missing()
        return _read_image(archive, files[ident], ident)


def normalized_image(raw):
    if not raw:
        raise _invalid_image()
    if len(raw) > MAX_INPUT_BYTES:
        raise too_large()
    try:
        with Image.open(BytesIO(raw), formats=FORMATS) as source:
            if source.width * source.height > MAX_PIXELS or getattr(source, 'is_animated', False):
                raise _invalid_image()
            picture = ImageOps.exif_transpose(source)
            picture.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            picture = picture.convert('RGBA' if picture.has_transparency_data else 'RGB')
            output = BytesIO()
            picture.save(output, 'WEBP', quality=85)
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise _invalid_image() from error
    normalized = output.getvalue()
    if len(normalized) > MAX_WEBP_BYTES:
        raise _invalid_image()
    return normalized


def _gallery_scope():
    return AppError(Msg('server.covers.gallery_scope', 'Choose an image from this work.'))


def gallery_image(gallery, work_id, relative):
    try:
        path = gallery.safe_path(relative).resolve()
        canonical = path.relative_to(gallery.root.resolve())
        parts = canonical.parts
        is_character = len(parts) == 6 and parts[0] == work_id and parts[2] == 'images'
        is_single = len(parts) == 4 and parts[:2] == ('_single', work_id)
        if not (is_character or is_single) or gallery.find(canonical.as_posix())['work_id'] != work_id:
            raise _gallery_scope()
    except ValueError as error:
        raise _gallery_scope() from error
    try:
        with path.open('rb') as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise _missing() from error
    return path.name, normalized_image(raw)


def _write(work, doc, images):
    path = _path(work)
    if not images:
        path.unlink(missing_ok=True)
        return _public(work.id, doc, images)
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr(MANIFEST, json.dumps(doc, ensure_ascii=False))
        for ident, raw in images.items():
            archive.writestr(f'{ident}.webp', raw)
    atomic_write_bytes(path, buffer.getvalue())
    return _public(work.id, doc, images)


def add(work, revision, filename, raw):
    ident = sha256_bytes(raw)
    with _open(work) as archive:
        doc, files = _state(archive)
        revisions.check(revision, revisions.of(doc))
        if ident in files:
            return _public(work.id, doc, files)
        if len(files) >= MAX_COVERS:
            raise AppError(Msg('server.covers.limit', 'A work can have at most {n} covers.', n=MAX_COVERS))
        items = [item for item in doc['items'] if item['id'] in files]
        images = {key: _read_image(archive, info, key) for key, info in files.items()}
    name = PureWindowsPath(filename[:512]).name[:180] if isinstance(filename, str) else ''
    items.append({'id': ident, 'name': name or f'{ident[:12]}.webp'})
    primary = doc['primary_id'] if doc['primary_id'] in images else items[0]['id']
    images[ident] = raw
    return _write(work, _manifest(items, primary), images)


def update(work, revision, ids, primary_id):
    if not isinstance(ids, list) or len(ids) > MAX_COVERS or not all(_valid_id(ident) for ident in ids):
        raise _bad_order()
    if len(ids) != len(set(ids)) or (primary_id is not None and primary_id not in ids):
        raise _bad_order()
    with _open(work) as archive:
        doc, files = _state(archive)
        revisions.check(revision, revisions.of(doc))
        if any(ident not in files for ident in ids):
            raise _bad_order()
        by_id = {item['id']: item for item in doc['items']}
        items = [by_id[ident] for ident in ids]
        updated = _manifest(items, primary_id or next(iter(ids), None))
        if updated == doc:
            return _public(work.id, doc, files)
        images = {ident: _read_image(archive, files[ident], ident) for ident in ids}
    return _write(work, updated, images)
