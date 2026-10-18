"""HTTP routes of the image tools (22-image-tools). Upload and mask bodies are raw bytes, not JSON."""

import io
from urllib.parse import unquote

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Route

from ..core.i18n import AppError, Msg
from ..core.lifecycle import UNFINISHED
from ..image.tools import processors
from .image_routes import _as_msg, _body, _runtime, call

MAX_UPLOAD_BYTES = 1024**3


def _ids(request):
    return [i for i in request.query_params.get('ids', '').split(',') if i]


def _number(request, name, default):
    try:
        return int(request.query_params[name]) if name in request.query_params else default
    except ValueError as error:
        raise AppError(Msg('server.bulk.page', 'Invalid page number.'), 400) from error


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
    offset = _number(request, 'offset', 0)
    limit = _number(request, 'limit', None)
    return await call(
        _runtime(request).tools.public, offset, limit, request.query_params.get('archived') == '1'
    )


async def item_ids(request):
    return await call(_runtime(request).tools.ids, request.query_params.get('archived') == '1')


async def analyze(request):
    runtime = _runtime(request)

    def run():
        result = runtime.tools.analyze(request.query_params.get('id', ''))
        if result.get('generation'):
            runtime.check_generation(result['generation'])
        return result

    return await call(run)


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


def _protected_post(attr):
    async def handler(request):
        runtime = _runtime(request)
        body = await _body(request)

        def run():
            with runtime.lock:
                return getattr(runtime, attr)(body) if attr != 'convert' else runtime.convert.start(body)

        return await call(run)

    return handler


async def batches(request):
    return await call(_runtime(request).bulk.list)


async def clear_completed_batches(request):
    return await call(_runtime(request).bulk.clear_completed)


async def remove_items(request):
    runtime = _runtime(request)
    body = await _body(request)
    ids = body.get('ids')
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise AppError(Msg('server.bulk.targets_invalid', 'Invalid bulk targets.'), 400)

    def remove():
        with runtime.lock:
            _check_in_use(runtime, ids)
            return runtime.tools.remove(ids)

    return await call(remove)


def _check_in_use(runtime, ids):
    if (
        runtime.bulk.active_targets(ids)
        or any(job.get('tool_item') in ids and job.get('status') in UNFINISHED for job in runtime.queue.jobs)
        or runtime.convert.in_use(ids)
    ):
        raise AppError(
            Msg('server.bulk.image_in_use', 'An unfinished image tool job still uses a selected image.'),
            409,
        )


async def archive_items(request):
    runtime = _runtime(request)
    body = await _body(request)
    ids = body.get('ids')
    archived = body.get('archived')
    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) > 50000
        or not all(isinstance(item, str) for item in ids)
        or not isinstance(archived, bool)
    ):
        raise AppError(Msg('server.bulk.targets_invalid', 'Invalid bulk targets.'), 400)

    def update():
        with runtime.lock:
            if archived:
                _check_in_use(runtime, ids)
            return runtime.tools.set_archived(ids, archived)

    return await call(update)


async def batch_details(request):
    return await call(
        _runtime(request).bulk.details,
        request.path_params['batch'],
        _number(request, 'offset', 0),
        _number(request, 'limit', 100),
    )


async def batch_action(request):
    runtime = _runtime(request)
    action = request.path_params['action']
    if action not in ('cancel', 'retry'):
        raise AppError(Msg('server.bulk.action', 'Unknown bulk action.'), 400)
    return await call(getattr(runtime.bulk, action), request.path_params['batch'])


def routes():
    p = '/api/image/tools'
    return [
        Route(f'{p}/items', items),
        Route(f'{p}/ids', item_ids),
        Route(f'{p}/batches', batches),
        Route(f'{p}/batches', _post('bulk.submit'), methods=['POST']),
        Route(f'{p}/batches/clear-completed', clear_completed_batches, methods=['POST']),
        Route(f'{p}/batches/{{batch}}', batch_details),
        Route(f'{p}/batches/{{batch}}/{{action}}', batch_action, methods=['POST']),
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
        Route(f'{p}/remove', remove_items, methods=['POST']),
        Route(f'{p}/archive', archive_items, methods=['POST']),
        Route(f'{p}/convert', _protected_post('convert'), methods=['POST']),
        Route(f'{p}/censor', _protected_post('apply_censor'), methods=['POST']),
        Route(f'{p}/alpha', _protected_post('apply_alpha'), methods=['POST']),
        Route(f'{p}/tag', _protected_post('enqueue_tags'), methods=['POST']),
        Route(f'{p}/postprocess', _protected_post('enqueue_postprocess'), methods=['POST']),
    ]
