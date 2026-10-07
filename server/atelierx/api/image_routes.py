"""HTTP routes of the image module. The runtime is thread based, so each call runs in the thread pool."""

import json
from pathlib import Path

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from ..core.i18n import AppError, Msg, message_of, wire
from ..image import library
from ..image import settings as image_settings
from ..image.deploy import targets as deploy_targets


def _runtime(request):
    return request.app.state.app.image


async def _body(request):
    raw = await request.body()
    try:
        return json.loads(raw) if raw else {}
    except ValueError as exc:  # not JSON, or not UTF-8: the request's fault, not a server error
        raise AppError(
            Msg('server.request.invalid_json', 'The request body is not valid JSON.'), 400
        ) from exc


def _as_msg(error):
    found = message_of(error)
    return found if isinstance(found, Msg) else Msg('server.image.error', '{text}', text=found)


async def call(fn, *args, status=200):
    """Run a runtime call; its ValueError is the user's mistake (400), RuntimeError a server-side failure (502)."""
    try:
        result = await run_in_threadpool(fn, *args)
    except AppError:
        raise
    except ValueError as error:
        raise AppError(_as_msg(error), 400) from error
    except RuntimeError as error:
        raise AppError(_as_msg(error), 502) from error
    return JSONResponse(wire(result) if result is not None else {'ok': True}, status_code=status)


# --- connection, models, GPU ---------------------------------------------------------------------------------------
async def connection_get(request):
    return await call(_runtime(request).connection)


async def connection_put(request):
    runtime = _runtime(request)
    return await call(runtime.control.save, await _body(request))


async def connection_control(request):
    runtime = _runtime(request)
    return await call(runtime.control.control, (await _body(request)).get('action'))


async def locate(request):
    return await call(_runtime(request).locate)


async def catalog(request):
    return await call(_runtime(request).catalog)


async def model_family(request):
    data = await _body(request)
    runtime = _runtime(request)
    return await call(runtime.models.set_family, data.get('kind'), data.get('name'), data.get('family'))


async def gpu_status(request):
    return await call(_runtime(request).gpu.status)


async def gpu_reserve(request):
    runtime = _runtime(request)
    return await call(runtime.gpu.reserve, await _body(request))


async def gpu_release(request):
    runtime = _runtime(request)
    return await call(runtime.gpu.release_reservation, await _body(request))


async def image_services_get(request):
    return await call(_runtime(request).image_services)


async def image_services_put(request):
    runtime = _runtime(request)
    return await call(runtime.save_image_services, await _body(request))


async def image_service_info(request):
    return await call(_runtime(request).image_service_info, request.path_params['service'])


async def image_service_account(request):
    return await call(_runtime(request).image_service_account, request.path_params['service'])


# --- deployment targets (decision 0023) ---------------------------------------------------------------------------
async def deploy_targets_get(request):
    return await call(_runtime(request).deploy_targets.public)


async def deploy_targets_put(request):
    return await call(_runtime(request).deploy_targets.save, await _body(request))


async def deploy_target_check(request):
    return await call(_runtime(request).deploy_targets.check, request.path_params['target'])


async def deploy_plan(request):
    return await call(_runtime(request).deploy.plan, await _body(request))


async def deploy_upload(request):
    return await call(_runtime(request).deploy.start, await _body(request))


async def deploy_run(request):
    return await call(_runtime(request).deploy.public, request.path_params['run'])


async def deploy_cancel(request):
    return await call(_runtime(request).deploy.cancel, request.path_params['run'])


async def work_deploy_get(request):
    runtime = _runtime(request)
    return await call(deploy_targets.work_settings, runtime.works.get(request.path_params['wid']))


async def work_deploy_put(request):
    runtime = _runtime(request)
    return await call(
        deploy_targets.save_work_settings, runtime.works.get(request.path_params['wid']), await _body(request)
    )


async def settings_get(request):
    runtime = _runtime(request)
    return await call(image_settings.get, runtime.paths, request.path_params['section'])


async def settings_put(request):
    runtime = _runtime(request)
    return await call(
        image_settings.save, runtime.paths, request.path_params['section'], await _body(request)
    )


# --- library, presets ----------------------------------------------------------------------------------------------
def _work_or_none(runtime, request):
    wid = request.query_params.get('work')
    return runtime.works.get(wid) if wid else None


async def library_get(request):
    runtime = _runtime(request)
    work = _work_or_none(runtime, request)
    kind = request.path_params['kind']
    if kind == 'rules':
        return await call(library.compose_rules, runtime.paths)
    return await call(library.items, runtime.paths, work, kind)


async def library_put(request):
    runtime = _runtime(request)
    data = await _body(request)
    work = runtime.works.get(data['work']) if data.get('work') else None
    p = request.path_params
    if p['kind'] == 'rules' and p['ident'] == 'targets':
        return await call(library.save_targets, runtime.paths, data.get('targets'))
    return await call(
        library.save_item,
        runtime.paths,
        work,
        p['kind'],
        data.get('scope', 'global'),
        p['ident'],
        data.get('item'),
        data.get('from_scope'),
    )


async def library_delete(request):
    runtime = _runtime(request)
    work = _work_or_none(runtime, request)
    p = request.path_params
    scope = request.query_params.get('scope', 'global')
    return await call(library.delete_item, runtime.paths, work, p['kind'], scope, p['ident'])


async def presets_get(request):
    return await call(library.presets, _runtime(request).paths)


async def preset_put(request):
    runtime = _runtime(request)
    return await call(library.save_preset, runtime.paths, request.path_params['ident'], await _body(request))


async def preset_delete(request):
    runtime = _runtime(request)
    return await call(library.delete_preset, runtime.paths, request.path_params['ident'])


# --- generation queue ----------------------------------------------------------------------------------------------
async def compose_preview(request):
    runtime = _runtime(request)
    work = runtime.works.get(request.path_params['wid'])
    return await call(runtime.preview, work, await _body(request))


async def check_nodes(request):
    return await call(_runtime(request).check_nodes, await _body(request))


async def enqueue(request):
    runtime = _runtime(request)
    work = runtime.works.get(request.path_params['wid'])
    data = await _body(request)
    if runtime.review_wanted() and data.get('review', True) is not False:
        runtime.llm.require_consent(work, 'image_review', data.get('llm'))
    return await call(runtime.enqueue, work, data)


async def queue_get(request):
    return await call(_runtime(request).public_jobs)


async def queue_action(request):
    runtime = _runtime(request)
    action = request.path_params['action']
    if action == 'pause':
        return await call(runtime.set_paused, True)
    if action == 'resume':
        return await call(runtime.set_paused, False)
    if action == 'cancel-queued':
        return await call(runtime.cancel_queued)
    if action == 'clear-finished':
        return await call(runtime.remove_finished)
    raise AppError(Msg('server.image.unknown_action', 'Unknown action.'), 404)


async def job_action(request):
    runtime = _runtime(request)
    p = request.path_params
    actions = {'cancel': runtime.cancel, 'retry': runtime.retry, 'remove': runtime.remove_finished}
    if p['action'] not in actions:
        raise AppError(Msg('server.image.unknown_action', 'Unknown action.'), 404)
    return await call(actions[p['action']], p['jid'])


async def lab_import(request):
    runtime = _runtime(request)
    return await call(runtime.import_lab, await _body(request))


async def lab_enqueue(request):
    runtime = _runtime(request)
    return await call(runtime.enqueue_lab, await _body(request))


async def lab_runs(request):
    return await call(_runtime(request).lab_runs)


async def output_file(request):
    """Files under the output root (generated images and their records). Paths never leave that folder."""
    root = Path(_runtime(request).paths.output).resolve()
    target = (root / request.path_params['path']).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise AppError(Msg('server.image.file_missing', 'The file does not exist.'), 404)
    return FileResponse(target)


async def tags_complete(request):
    runtime = _runtime(request)
    return await call(runtime.tags.complete, request.query_params.get('q', ''), 15)


async def tags_check(request):
    runtime = _runtime(request)
    return await call(runtime.tags.check, (await _body(request)).get('tags') or [])


# --- gallery and review ---------------------------------------------------------------------------------------------
async def gallery_list(request):
    runtime = _runtime(request)
    return await call(runtime.reviews.list, dict(request.query_params))


async def gallery_tree(request):
    return await call(_runtime(request).gallery.tree)


async def gallery_detail(request):
    runtime = _runtime(request)
    return await call(runtime.reviews.detail, request.query_params.get('path', ''))


async def gallery_thumbnail(request):
    runtime = _runtime(request)
    try:
        data = await run_in_threadpool(runtime.gallery.thumbnail, request.query_params.get('path', ''))
    except (ValueError, OSError) as error:
        raise AppError(Msg('server.image.file_missing', 'The file does not exist.'), 404) from error
    return Response(data, media_type='image/webp', headers={'Cache-Control': 'private, max-age=86400'})


async def gallery_review(request):
    runtime = _runtime(request)
    return await call(runtime.reviews.review, await _body(request))


async def gallery_regenerate(request):
    runtime = _runtime(request)
    data = await _body(request)
    return await call(runtime.rounds.regenerate, data.get('items'), data.get('review'))


async def gallery_export_plan(request):
    runtime = _runtime(request)
    return await call(runtime.reviews.plan_export, (await _body(request)).get('filters'))


async def gallery_export(request):
    runtime = _runtime(request)
    data = await _body(request)
    try:
        target, name = await run_in_threadpool(runtime.reviews.export_zip, data)
    except ValueError as error:
        raise AppError(_as_msg(error), 400) from error
    return FileResponse(
        target,
        media_type='application/zip',
        filename=name,
        background=BackgroundTask(lambda: Path(target).unlink(missing_ok=True)),
    )


async def gallery_delete(request):
    runtime = _runtime(request)
    return await call(runtime.trash.delete, (await _body(request)).get('paths'))


async def trash_list(request):
    return await call(_runtime(request).trash.list)


async def trash_action(request):
    runtime = _runtime(request)
    action = request.path_params['action']
    ids = (await _body(request)).get('ids')
    if action == 'restore':
        return await call(runtime.trash.restore, ids)
    if action == 'purge':
        return await call(runtime.trash.purge, ids)
    raise AppError(Msg('server.image.unknown_action', 'Unknown action.'), 404)


async def installs_get(request):
    return await call(_runtime(request).installs.status)


async def installs_action(request):
    runtime = _runtime(request)
    action = request.path_params['action']
    if action == 'cancel':
        return await call(runtime.installs.cancel)
    if action == 'restart-comfy':
        return await call(runtime.installs.restart_comfy)
    return await call(runtime.installs.start, action, await _body(request))


async def review_settings_get(request):
    return await call(_runtime(request).rounds.public_settings)


async def review_settings_put(request):
    runtime = _runtime(request)
    return await call(runtime.rounds.save_settings, await _body(request))


async def review_rounds(request):
    return await call(_runtime(request).rounds.public)


async def review_rounds_action(request):
    runtime = _runtime(request)
    action = request.path_params['action']
    if action == 'dismiss':
        return await call(runtime.rounds.dismiss)
    if action == 'retry':
        return await call(runtime.rounds.retry, (await _body(request)).get('ids'))
    raise AppError(Msg('server.image.unknown_action', 'Unknown action.'), 404)


def _designs(work):
    """Character items with their image design summary (outfits, trigger), in tree order."""
    from ..image.util import read_json

    out = []
    for item in work.index():
        cid = item['meta'].get('id')
        if item['kind'] != 'character' or not cid or not item['meta'].get('enabled', True):
            continue
        design = read_json(work.app / 'image' / 'characters' / cid / 'design.json') or {}
        out.append(
            {
                'id': cid,
                'name': item['name'],
                'path': item['path'],
                'has_design': bool(design),
                'trigger': design.get('trigger'),
                'default_outfit': design.get('default_outfit'),
                'outfits': [
                    {'id': k, 'name': v.get('name', k)} for k, v in (design.get('outfits') or {}).items()
                ],
            }
        )
    return out


async def image_board(request):
    from ..image import board

    runtime = _runtime(request)
    return await call(board.board, runtime, runtime.works.get(request.path_params['wid']))


async def image_board_exclude(request):
    from ..image import board

    runtime = _runtime(request)
    work = runtime.works.get(request.path_params['wid'])
    data = await _body(request)

    def run():
        board.set_excluded(
            work, data.get('character_id'), data.get('combos'), bool(data.get('excluded', True))
        )
        return board.board(runtime, work)

    return await call(run)


async def designs(request):
    runtime = _runtime(request)
    return await call(_designs, runtime.works.get(request.path_params['wid']))


def routes():
    p = '/api/image'
    return [
        Route(f'{p}/connection', connection_get),
        Route(f'{p}/connection', connection_put, methods=['PUT']),
        Route(f'{p}/connection/control', connection_control, methods=['POST']),
        Route(f'{p}/locate', locate),
        Route(f'{p}/catalog', catalog),
        Route(f'{p}/models/family', model_family, methods=['PUT']),
        Route(f'{p}/gpu', gpu_status),
        Route(f'{p}/gpu/reserve', gpu_reserve, methods=['POST']),
        Route(f'{p}/gpu/release', gpu_release, methods=['POST']),
        Route(f'{p}/deploy/targets', deploy_targets_get),
        Route(f'{p}/deploy/targets', deploy_targets_put, methods=['PUT']),
        Route(f'{p}/deploy/targets/{{target}}/check', deploy_target_check, methods=['POST']),
        Route(f'{p}/deploy/plan', deploy_plan, methods=['POST']),
        Route(f'{p}/deploy/upload', deploy_upload, methods=['POST']),
        Route(f'{p}/deploy/runs/{{run}}', deploy_run),
        Route(f'{p}/deploy/runs/{{run}}/cancel', deploy_cancel, methods=['POST']),
        Route(f'{p}/services', image_services_get),
        Route(f'{p}/services', image_services_put, methods=['PUT']),
        Route(f'{p}/services/{{service}}/info', image_service_info),
        Route(f'{p}/services/{{service}}/account', image_service_account),
        Route(f'{p}/settings/{{section}}', settings_get),
        Route(f'{p}/settings/{{section}}', settings_put, methods=['PUT']),
        Route(f'{p}/tags/complete', tags_complete),
        Route(f'{p}/tags/check', tags_check, methods=['POST']),
        Route(f'{p}/library/{{kind}}', library_get),
        Route(f'{p}/library/{{kind}}/{{ident}}', library_put, methods=['PUT']),
        Route(f'{p}/library/{{kind}}/{{ident}}', library_delete, methods=['DELETE']),
        Route(f'{p}/presets', presets_get),
        Route(f'{p}/presets/{{ident}}', preset_put, methods=['PUT']),
        Route(f'{p}/presets/{{ident}}', preset_delete, methods=['DELETE']),
        Route(f'{p}/queue', queue_get),
        Route(f'{p}/queue/{{action}}', queue_action, methods=['POST']),
        Route(f'{p}/jobs/{{jid}}/{{action}}', job_action, methods=['POST']),
        Route(f'{p}/lab', lab_enqueue, methods=['POST']),
        Route(f'{p}/lab/runs', lab_runs),
        Route(f'{p}/lab/import', lab_import, methods=['POST']),
        Route(f'{p}/files/{{path:path}}', output_file),
        Route(f'{p}/gallery', gallery_list),
        Route(f'{p}/gallery/tree', gallery_tree),
        Route(f'{p}/gallery/detail', gallery_detail),
        Route(f'{p}/gallery/thumbnail', gallery_thumbnail),
        Route(f'{p}/gallery/review', gallery_review, methods=['POST']),
        Route(f'{p}/gallery/regenerate', gallery_regenerate, methods=['POST']),
        Route(f'{p}/gallery/export/plan', gallery_export_plan, methods=['POST']),
        Route(f'{p}/gallery/export', gallery_export, methods=['POST']),
        Route(f'{p}/gallery/delete', gallery_delete, methods=['POST']),
        Route(f'{p}/trash', trash_list),
        Route(f'{p}/installs', installs_get),
        Route(f'{p}/installs/{{action}}', installs_action, methods=['POST']),
        Route(f'{p}/trash/{{action}}', trash_action, methods=['POST']),
        Route(f'{p}/review/settings', review_settings_get),
        Route(f'{p}/review/settings', review_settings_put, methods=['PUT']),
        Route(f'{p}/review/rounds', review_rounds),
        Route(f'{p}/review/rounds/{{action}}', review_rounds_action, methods=['POST']),
        Route('/api/works/{wid}/image/designs', designs),
        Route('/api/works/{wid}/image/board', image_board),
        Route('/api/works/{wid}/image/deploy', work_deploy_get),
        Route('/api/works/{wid}/image/deploy', work_deploy_put, methods=['PUT']),
        Route('/api/works/{wid}/image/board/exclude', image_board_exclude, methods=['PUT']),
        Route('/api/works/{wid}/image/compose', compose_preview, methods=['POST']),
        Route('/api/works/{wid}/image/jobs', enqueue, methods=['POST']),
        Route('/api/image/generate/check-nodes', check_nodes, methods=['POST']),
    ]
