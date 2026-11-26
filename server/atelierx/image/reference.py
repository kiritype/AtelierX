"""Work-scoped, content-addressed inputs and portable exports for reference generation."""

import base64
import binascii
import hashlib
import io
import json
import re
import tempfile
import uuid
import zipfile
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from PIL import Image

from ..core.i18n import Msg
from . import moss_reference
from .comfy import REFERENCE_NODE, REFERENCE_WEIGHT
from .tools.inspect import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS
from .util import atomic_json, code, read_json, replace_file

NODE_COMMIT = 'f02d54dd34593b4d4ce27b38de2a996049aeac58'
WEIGHTS_SHA256 = '71dda6079e18d354e16e3347bc49a9b710afd9495c378efbb833d30cac9cb81b'
INPUT_PREFIX = 'atelierx-reference-'
FORMATS = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}
MAX_BODY_BYTES = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 4096


def _invalid_image():
    return ValueError(
        Msg(
            'server.reference.invalid_image', 'Choose one readable PNG, WebP, or JPEG image of 32 MB or less.'
        )
    )


def _missing_image():
    return ValueError(
        Msg('server.reference.missing_image', 'The saved reference image is missing or has changed.')
    )


def _asset_root(work):
    root = work.app / 'image' / 'references'
    if not root.resolve().is_relative_to(work.app.resolve()):
        raise _missing_image()
    return root


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _image_bytes(path):
    if path.is_symlink() or not path.is_file():
        raise _missing_image()
    try:
        with path.open('rb') as source:
            return source.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        raise _missing_image() from error


def _image_format(raw):
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise _invalid_image()
    try:
        with Image.open(io.BytesIO(raw), formats=list(FORMATS)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS or getattr(image, 'is_animated', False):
                raise _invalid_image()
            image.load()
            return image.format
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise _invalid_image() from error


def _data_url(value):
    if not isinstance(value, str) or len(value) > MAX_BODY_BYTES:
        raise _invalid_image()
    prefix, _, data = value.partition(',')
    if prefix not in ('data:image/png;base64', 'data:image/webp;base64', 'data:image/jpeg;base64'):
        raise _invalid_image()
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as error:
        raise _invalid_image() from error


def data(work, ident):
    """Return private input metadata and its file. Read or hash the bytes only when needed."""
    if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{64}', ident):
        raise _missing_image()
    root = _asset_root(work)
    record = read_json(root / f'{ident}.json')
    image_format = record.get('format') if isinstance(record, dict) else None
    if not isinstance(image_format, str) or image_format not in FORMATS:
        raise _missing_image()
    path = root / (ident + FORMATS[image_format])
    if path.is_symlink() or not path.is_file():
        raise _missing_image()
    name = record.get('name')
    return {'id': ident, 'name': name if isinstance(name, str) and name else path.name, 'sha256': ident}, path


def public(work_id, entry):
    ident = entry['id']
    return {**entry, 'url': f'/api/works/{quote(work_id, safe="")}/image/reference/assets/{ident}'}


def store(work, gallery, body):
    if not isinstance(body, dict) or ('gallery_path' in body) == ('data_url' in body):
        raise _invalid_image()
    if 'gallery_path' in body:
        source = body['gallery_path']
        path = gallery.safe_path(source)
        parts = path.relative_to(gallery.root).parts
        work_id = code(work.id)
        if parts[0] != work_id and parts[:2] != ('_single', work_id):
            raise ValueError(Msg('server.reference.gallery_scope', 'Choose an image from this work.'))
        name, raw = path.name, _image_bytes(path)
    else:
        value = body.get('filename')
        name = PureWindowsPath(value[:512]).name[:180] if isinstance(value, str) else ''
        raw = _data_url(body['data_url'])
    image_format = _image_format(raw)
    ident = _hash(raw)
    root = _asset_root(work)
    root.mkdir(parents=True, exist_ok=True)
    target = root / (ident + FORMATS[image_format])
    if target.is_symlink():
        raise _missing_image()
    if not target.is_file() or _hash(_image_bytes(target)) != ident:
        temp = root / f'{ident}.{uuid.uuid4().hex}.tmp'
        try:
            temp.write_bytes(raw)
            replace_file(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    metadata = root / f'{ident}.json'
    if not isinstance(read_json(metadata), dict):
        atomic_json(metadata, {'name': name or target.name, 'format': image_format})
    return public(work.id, data(work, ident)[0])


def require_ready(comfy):
    status = comfy.reference_status()
    if not status['node_ready']:
        raise ValueError(
            Msg(
                'server.reference.missing_node',
                'Install Anima Ref Adapter in Settings → Install, then restart ComfyUI.',
            )
        )
    if not status['weights_ready']:
        raise ValueError(
            Msg(
                'server.reference.missing_weights',
                'Install the Anima reference weights in Settings → Install.',
            )
        )


def is_moss(entry):
    return entry.get('engine') == moss_reference.ENGINE


def prepare(work, parameters):
    if not isinstance(parameters, dict):
        raise _invalid_image()
    if is_moss(parameters):
        if set(parameters) != {'id', 'engine'}:
            raise ValueError(
                Msg('server.reference.moss_reference', 'MossRef accepts one reference image in Auto mode.')
            )
        asset, _ = data(work, parameters.get('id'))
        return {
            **asset,
            'engine': moss_reference.ENGINE,
            **moss_reference.PROVENANCE,
            **moss_reference.PARAMETERS,
        }
    if 'engine' in parameters:
        raise ValueError(Msg('server.reference.engine', 'Choose a supported reference generation engine.'))
    guidance = parameters.get('guidance', 4.5)
    if isinstance(guidance, bool) or not isinstance(guidance, (int, float)) or not 0 <= guidance <= 20:
        raise ValueError(Msg('server.reference.guidance', 'Choose reference guidance from 0 to 20.'))
    asset, _ = data(work, parameters.get('id'))
    return {
        **asset,
        'guidance': float(guidance),
        'node': REFERENCE_NODE,
        'expected_node_commit': NODE_COMMIT,
        'weights': REFERENCE_WEIGHT,
        'expected_weights_sha256': WEIGHTS_SHA256,
    }


def check_moss_record(entry):
    for key, expected in {**moss_reference.PROVENANCE, **moss_reference.PARAMETERS}.items():
        if entry.get(key) != expected:
            raise ValueError(
                Msg('server.reference.moss_revision', 'This run needs a different version of MossRef.')
            )


def upload(comfy, work, entry):
    if is_moss(entry):
        check_moss_record(entry)
    else:
        require_ready(comfy)
    asset, path = data(work, entry['id'])
    raw = _image_bytes(path)
    if _hash(raw) != asset['sha256'] or len(raw) > MAX_IMAGE_BYTES:
        raise _missing_image()
    name = INPUT_PREFIX + path.name
    # LoadImage only lists files at the root of ComfyUI input in the editor.
    result = comfy.upload(name, raw, subfolder='')
    if result.get('name') != name or result.get('subfolder'):
        raise RuntimeError(
            Msg('server.reference.upload', 'ComfyUI did not keep the uploaded reference image.')
        )
    return (
        {
            'image': name,
            'engine': moss_reference.ENGINE,
            **{key: entry[key] for key in moss_reference.PARAMETERS},
        }
        if is_moss(entry)
        else {'image': name, 'guidance': entry['guidance']}
    )


def result_record(work, gallery, relative):
    path = gallery.safe_path(relative)
    prefix = path.relative_to(gallery.root).parts[:2]
    if prefix != ('_single', code(work.id)):
        raise ValueError(
            Msg('server.reference.result', 'Choose a reference generation result from this work.')
        )
    record = gallery.metadata(relative)
    if (
        record.get('kind') != 'single'
        or record.get('work_id') != work.id
        or record.get('service') != 'comfyui'
        or not isinstance(record.get('reference'), dict)
    ):
        raise ValueError(
            Msg('server.reference.result', 'Choose a reference generation result from this work.')
        )
    return path, record


def export_zip(work, gallery, relative, include_reference):
    image_path, record = result_record(work, gallery, relative)
    try:
        with Image.open(image_path) as image:
            editor = json.loads(image.text['workflow'])
        graph = record['workflow']
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValueError(
            Msg('server.reference.workflow', 'The editable reference workflow is unavailable.')
        ) from error
    asset_path = None
    if include_reference:
        asset, asset_path = data(work, record['reference']['id'])
        raw = _image_bytes(asset_path)
        if len(raw) > MAX_IMAGE_BYTES or _hash(raw) != asset['sha256']:
            raise _missing_image()
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as file:
        destination = Path(file.name)
    try:
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(image_path, 'result.png', compress_type=zipfile.ZIP_STORED)
            archive.writestr('workflow.json', json.dumps(editor, ensure_ascii=False, indent=2))
            archive.writestr('prompt.json', json.dumps(graph, ensure_ascii=False, indent=2))
            archive.writestr(
                'generation.json',
                json.dumps(
                    {key: value for key, value in record.items() if key != 'workflow'},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            if asset_path:
                archive.writestr(
                    f'input/{INPUT_PREFIX}{asset_path.name}', raw, compress_type=zipfile.ZIP_STORED
                )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination, f'atelierx-reference-{image_path.stem}.zip'
