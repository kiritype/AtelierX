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
from . import anima_reference, moss_reference
from .comments import strip_text
from .tools.inspect import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS
from .util import atomic_json, code, read_json, replace_file

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
    if anima_reference.is_entry(entry):
        return {**entry, 'subjects': [public(work_id, subject) for subject in entry['subjects']]}
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


def _guidance(parameters):
    value = parameters.get('guidance', anima_reference.DEFAULT_GUIDANCE)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 20:
        raise ValueError(Msg('server.reference.guidance', 'Choose reference guidance from 0 to 20.'))
    return float(value)


def _invalid_subjects():
    return ValueError(
        Msg(
            'server.reference.subjects',
            'Choose one centered person or two people with different left and right positions.',
        )
    )


def _anima_subjects(work, subjects):
    if not isinstance(subjects, list) or len(subjects) not in (1, 2):
        raise _invalid_subjects()
    chosen = []
    for subject in subjects:
        if not isinstance(subject, dict) or set(subject) - {'slot', 'id', 'position', 'description'}:
            raise _invalid_subjects()
        slot = subject.get('slot')
        position = subject.get('position')
        description = subject.get('description', '')
        if (
            slot not in ('a', 'b')
            or position not in ('center', 'left', 'right')
            or not isinstance(description, str)
        ):
            raise _invalid_subjects()
        asset, _ = data(work, subject.get('id'))
        chosen.append(
            {**asset, 'slot': slot, 'position': position, 'description': strip_text(description).strip()}
        )
    positions, slots = ({'center'}, {'a'}) if len(chosen) == 1 else ({'left', 'right'}, {'a', 'b'})
    if {subject['position'] for subject in chosen} != positions or {
        subject['slot'] for subject in chosen
    } != slots:
        raise _invalid_subjects()
    return chosen


def _image_size(path):
    try:
        with Image.open(path, formats=list(FORMATS)) as image:
            width, height = image.size
            return (height, width) if image.getexif().get(274) in (5, 6, 7, 8) else (width, height)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise _missing_image() from error


def _anima_files(work, subjects):
    files = [data(work, subject['id']) for subject in sorted(subjects, key=lambda item: item['position'])]
    if len(files) == 2:
        left_width, left_height = _image_size(files[0][1])
        right_width, right_height = _image_size(files[1][1])
        stitched_width = int(left_height * (right_width / right_height))
        if stitched_width < 1 or left_height * (left_width + stitched_width) > MAX_IMAGE_PIXELS:
            raise ValueError(
                Msg(
                    'server.reference.stitch_size',
                    'These two reference sizes cannot be stitched safely. Choose images with closer dimensions.',
                )
            )
    return files


def _anima_parameters(parameters):
    engine = parameters['engine']
    if engine == anima_reference.SNAPREF:
        mode = parameters.get('snapref_mode', 'cs')
        if mode not in ('cs', 'char'):
            raise ValueError(Msg('server.reference.snapref_mode', 'Choose a supported SnapRef mode.'))
        return {'snapref_mode': mode, 'ref_weight': 1.0, 'snapref_guidance': False}
    return {'guidance': _guidance(parameters)}


def _prepare_anima(work, parameters):
    engine = parameters['engine']
    option = 'snapref_mode' if engine == anima_reference.SNAPREF else 'guidance'
    if set(parameters) - {'engine', 'subjects', option}:
        raise ValueError(Msg('server.reference.engine', 'Choose a supported reference generation engine.'))
    subjects = _anima_subjects(work, parameters.get('subjects'))
    _anima_files(work, subjects)
    return {
        'engine': engine,
        'subjects': subjects,
        **anima_reference.provenance(engine),
        **_anima_parameters(parameters),
    }


def prepare(work, parameters):
    if not isinstance(parameters, dict):
        raise _invalid_image()
    if anima_reference.is_entry(parameters):
        return _prepare_anima(work, parameters)
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
    guidance = _guidance(parameters)
    asset, _ = data(work, parameters.get('id'))
    return {
        **asset,
        'guidance': guidance,
        **anima_reference.provenance(anima_reference.ANIMA_V2),
    }


def check_moss_record(entry):
    for key, expected in {**moss_reference.PROVENANCE, **moss_reference.PARAMETERS}.items():
        if entry.get(key) != expected:
            raise ValueError(
                Msg('server.reference.moss_revision', 'This run needs a different version of MossRef.')
            )


def check_anima_record(work, entry):
    fields = {**anima_reference.provenance(entry['engine']), **_anima_parameters(entry)}
    if any(entry.get(key) != value for key, value in fields.items()):
        raise ValueError(
            Msg(
                'server.reference.anima_revision',
                'This run needs a different version of the Anima reference adapter.',
            )
        )
    subjects = _anima_subjects(
        work,
        [
            {key: subject[key] for key in ('id', 'slot', 'position', 'description')}
            for subject in entry['subjects']
        ],
    )
    return _anima_files(work, subjects)


def _checked_bytes(asset, path):
    raw = _image_bytes(path)
    if len(raw) > MAX_IMAGE_BYTES or _hash(raw) != asset['sha256']:
        raise _missing_image()
    return raw


def _upload_image(comfy, path, raw):
    name = INPUT_PREFIX + path.name
    # LoadImage only lists files at the root of ComfyUI input in the editor.
    result = comfy.upload(name, raw, subfolder='')
    if result.get('name') != name or result.get('subfolder'):
        raise RuntimeError(
            Msg('server.reference.upload', 'ComfyUI did not keep the uploaded reference image.')
        )
    return name


def upload(comfy, work, entry):
    if anima_reference.is_entry(entry):
        files = check_anima_record(work, entry)
        anima_reference.require_ready(comfy, entry)
        originals = {path: _checked_bytes(asset, path) for asset, path in files}
        uploaded = {path: _upload_image(comfy, path, raw) for path, raw in originals.items()}
        return {
            'engine': entry['engine'],
            'images': [uploaded[path] for _, path in files],
            **_anima_parameters(entry),
        }
    if is_moss(entry):
        check_moss_record(entry)
    else:
        require_ready(comfy)
    asset, path = data(work, entry['id'])
    name = _upload_image(comfy, path, _checked_bytes(asset, path))
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
    originals = {}
    if include_reference:
        entry = record['reference']
        subjects = entry['subjects'] if anima_reference.is_entry(entry) else [entry]
        for ident in dict.fromkeys(subject['id'] for subject in subjects):
            asset, asset_path = data(work, ident)
            originals[f'input/{INPUT_PREFIX}{asset_path.name}'] = _checked_bytes(asset, asset_path)
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
            for name, raw in originals.items():
                archive.writestr(name, raw, compress_type=zipfile.ZIP_STORED)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination, f'atelierx-reference-{image_path.stem}.zip'
