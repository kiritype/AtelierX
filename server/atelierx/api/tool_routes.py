"""HTTP routes of the image tools (22-image-tools). Upload and mask bodies are raw bytes, not JSON."""

import io
from urllib.parse import unquote

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Route

from ..core.i18n import AppError, Msg
from ..image.tools import processors
from .image_routes import _as_msg, _body, _runtime, call

MAX_UPLOAD_BYTES = 1024**3


def _ids(request):
    return [i for i in request.query_params.get('ids', '').split(',') if i]


async def _bytes(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except ValueError as error:
        raise AppError(_as_msg(error), 400) from error
    except (OSError, KeyError) as error:
        raise AppError(Msg('server.image.file_missing', 'The file does not exist.'), 404) from error


def _download(raw, name, kind):
    return Response(raw, media_type=kind, headers={'Content-Disposition': f'attachment; filename="{name}"'})


async def items(request):
    return await call(_runtime(request).tools.public)


async def analyze(request):
    runtime = _runtime(request)
    return await call(runtime.tools.analyze, request.query_params.get('id', ''))


async def tagger_info(request):
    return await call(_runtime(request).tagger_info)


async def postprocess_info(request):
    return await call(_runtime(request).postprocess_info)


async def methods(request):
    """The ways each tool feature can run (this PC, an internet service); the screen greys out the rest."""
    return await call(lambda: {'methods': list(processors.METHODS), 'features': processors.features()})


async def upload(request):
    raw = await request.body()
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise AppError(Msg('server.handler.the_file_is_empty_or_too', 'The file is empty or too large.'), 400)
    name = unquote(request.headers.get('x-file-name', '') or 'upload')
    return await call(_runtime(request).tools.upload, name, raw)


async def mask_get(request):
    runtime = _runtime(request)
    mask = await _bytes(
        runtime.tools.mask, request.query_params.get('id', ''), request.query_params.get('kind', 'censor')
    )
    if mask is None:
        raise AppError(Msg('server.handler.no_mask', 'No mask.'), 404)
    out = io.BytesIO()
    mask.save(out, 'PNG')
    return Response(out.getvalue(), media_type='image/png')


async def mask_put(request):
    runtime = _runtime(request)
    raw = await request.body()
    item_id = request.query_params.get('id', '')
    kind = request.query_params.get('kind', 'censor')

    def save():
        runtime.tools.set_mask(item_id, raw, 'edited', kind)
        return {'item': runtime.tools.get(item_id)}

    return await call(save)


async def thumbnail(request):
    runtime = _runtime(request)
    raw = await _bytes(runtime.tools.thumbnail, request.query_params.get('id', ''))
    return Response(raw, media_type='image/webp', headers={'Cache-Control': 'private, max-age=300'})


async def image(request):
    runtime = _runtime(request)
    raw, kind = await _bytes(runtime.tools.image, request.query_params.get('id', ''))
    return Response(raw, media_type='image/' + kind.lower())


async def tags_export(request):
    runtime = _runtime(request)
    raw, name, kind = await _bytes(
        runtime.export_tags, _ids(request), request.query_params.get('format', 'txt')
    )
    return _download(raw, name, kind)


async def zip_items(request):
    runtime = _runtime(request)
    raw, name = await _bytes(runtime.tools.zip, _ids(request))
    return _download(raw, name, 'application/zip')


async def convert_task(request):
    runtime = _runtime(request)
    return await call(runtime.convert.get, request.query_params.get('id', ''))


async def convert_zip(request):
    runtime = _runtime(request)
    raw, name = await _bytes(runtime.convert.zip, request.query_params.get('id', ''))
    return _download(raw, name, 'application/zip')


def _post(attr, key=None):
    """A JSON POST that calls ``runtime.<attr>`` with the body (or one key of it)."""

    async def handler(request):
        runtime = _runtime(request)
        target = runtime
        for part in attr.split('.'):
            target = getattr(target, part)
        body = await _body(request)
        return await call(target, body.get(key) if key else body)

    return handler


def routes():
    p = '/api/image/tools'
    return [
        Route(f'{p}/items', items),
        Route(f'{p}/analyze', analyze),
        Route(f'{p}/tagger', tagger_info),
        Route(f'{p}/postprocess', postprocess_info),
        Route(f'{p}/methods', methods),
        Route(f'{p}/upload', upload, methods=['POST']),
        Route(f'{p}/mask', mask_get),
        Route(f'{p}/mask', mask_put, methods=['PUT']),
        Route(f'{p}/thumbnail', thumbnail),
        Route(f'{p}/image', image),
        Route(f'{p}/tags/export', tags_export),
        Route(f'{p}/zip', zip_items),
        Route(f'{p}/convert/task', convert_task),
        Route(f'{p}/convert/zip', convert_zip),
        Route(f'{p}/gallery', _post('tools.add_gallery', 'paths'), methods=['POST']),
        Route(f'{p}/remove', _post('tools.remove', 'ids'), methods=['POST']),
        Route(f'{p}/convert', _post('convert.start'), methods=['POST']),
        Route(f'{p}/censor', _post('apply_censor'), methods=['POST']),
        Route(f'{p}/alpha', _post('apply_alpha'), methods=['POST']),
        Route(f'{p}/tag', _post('enqueue_tags'), methods=['POST']),
        Route(f'{p}/postprocess', _post('enqueue_postprocess'), methods=['POST']),
    ]
