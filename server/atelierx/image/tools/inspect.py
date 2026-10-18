"""Read generation records from an external image without storing or changing it."""

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from . import gen_info, metadata

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 64 * 1024 * 1024
IMAGE_FORMATS = {'PNG', 'JPEG', 'WEBP'}


def inspect_image(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Choose a PNG, WebP, or JPEG image of 32 MB or less.')
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in IMAGE_FORMATS:
                raise ValueError('Choose a PNG, WebP, or JPEG image.')
            image_size = (image.width, image.height)
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError('The image is too large to inspect safely.')
            image_format = image.format
            text, exif = metadata.read_raw(image)
            image.load()  # A readable header alone does not prove the file is complete.
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError('The image could not be read.') from error

    studio = metadata._json(text.get('atelierx')) or metadata._json(text.get('asset_studio'))
    malformed = False
    if (
        not isinstance(studio, dict)
        or not isinstance(studio.get('positive'), str)
        or not isinstance(studio.get('settings') or {}, dict)
    ):
        malformed = studio is not None
        studio = None
    graph = metadata._json(text.get('prompt'))
    if graph is not None and (
        not isinstance(graph, dict)
        or any(
            not isinstance(node, dict) or not isinstance(node.get('inputs') or {}, dict)
            for node in graph.values()
        )
    ):
        malformed = True
        text_for_analysis = {key: value for key, value in text.items() if key != 'prompt'}
    else:
        text_for_analysis = text
    try:
        generation = gen_info.analyze(text_for_analysis, exif, studio, image_size)
    except (AttributeError, IndexError, KeyError, RecursionError, TypeError, ValueError):
        malformed = True
        generation = gen_info.analyze({}, {}, None, image_size)
    has_result = bool(
        generation['positive']
        or generation['negative']
        or any(key not in ('width', 'height') for key in generation['settings'])
    )
    status = 'none' if not text and not exif else 'parsed' if has_result and not malformed else 'partial'
    return {
        'format': image_format,
        'width': image_size[0],
        'height': image_size[1],
        'status': status,
        'metadata_limited': any(
            len(value) >= metadata.TEXT_LIMIT for value in (*text.values(), *exif.values())
        ),
        'generation': generation,
        'raw': {'text': text, 'exif': exif},
    }
