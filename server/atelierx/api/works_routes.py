"""Works: list, create, change, delete, duplicate, samples, the data trash and one work."""

import shutil

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Route

from ..core import work_covers
from ..core.i18n import AppError, Msg
from ..core.snapshots import Snapshots
from ..core.works import trash_bundle
from ..image.uuid_migration import FileCheckpoint, migrate_runtime, migrate_runtime_guarded
from .common import body, ok, st, work_of


async def works_list(request):
    s = st(request)
    return ok({'works': [s.works.card(w) for w in s.works.all()], 'suggest_id': s.works.suggest_id()})


async def works_create(request):
    data = await body(request)
    s = st(request)
    tags = data.get('tags')
    if tags is None:
        default = s.settings.load().get('default_platform_preset')
        tags = [default] if default else []
    work = s.works.create(
        data['name'], data.get('id') or None, tags, data.get('scale', 'single'), data.get('language', 'ko')
    )
    return ok(s.works.card(work), 201)


async def works_patch(request):
    data = await body(request)
    s = st(request)
    work = work_of(request)
    if 'name' in data and data['name'] != work.name:
        work = s.works.rename(work.id, data['name'])
    fields = {
        k: v
        for k, v in data.items()
        if k in ('tags', 'scale', 'language', 'overrides', 'char', 'order', 'llm_consent')
    }
    if fields:
        work.update_doc(fields)
    return ok(s.works.card(work))


async def works_delete(request):
    return ok(st(request).works.delete(request.path_params['wid']))


async def works_duplicate(request):
    data = await body(request)
    s = st(request)
    return ok(
        s.works.card(s.works.duplicate(request.path_params['wid'], data['name'], data.get('id') or None))
    )


async def samples_list(request):
    return ok(st(request).works.samples())


async def samples_install(request):
    s = st(request)
    with s.admission.exclusive(s.busy_work):
        before = set(s.paths.works.iterdir()) if s.paths.works.is_dir() else set()
        try:
            work = s.works.install_sample(request.path_params['name'])
            migrate_runtime_guarded(s)
        except BaseException:
            s.admission.seal()
            for folder in set(s.paths.works.iterdir()) - before:
                shutil.rmtree(folder)
            migrate_runtime(s.image)
            s.admission.unseal()
            raise
        Snapshots(work).create('import', '샘플 설치')
    return ok(s.works.card(work), 201)


async def data_trash_list(request):
    return ok(st(request).works.trash())


async def data_trash_restore(request):
    s = st(request)
    with s.admission.exclusive(s.busy_work):
        bundle = trash_bundle(s.paths.data_trash, request.path_params['bid'])
        checkpoint = FileCheckpoint(s.paths, [bundle])
        before = set(s.paths.works.iterdir()) if s.paths.works.is_dir() else set()
        try:
            result = s.works.restore(request.path_params['bid'])
            migrate_runtime_guarded(s)
        except BaseException:
            s.admission.seal()
            for folder in set(s.paths.works.iterdir()) - before:
                shutil.rmtree(folder)
            checkpoint.rollback()
            migrate_runtime(s.image)
            s.admission.unseal()
            raise
        finally:
            if not s.admission.quarantined:
                checkpoint.close()
    return ok(result)


async def data_trash_purge(request):
    st(request).works.purge(request.path_params.get('bid'))
    return ok()


async def work_get(request):
    s = st(request)
    work = work_of(request)
    doc = work.doc()
    return ok(
        {
            'name': work.name,
            'doc': doc,
            'effective': s.presets.effective(doc),
            'presets': s.presets.list(),
        }
    )


async def covers_list(request):
    return ok(work_covers.view(work_of(request)))


async def covers_upload(request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > work_covers.MAX_INPUT_BYTES:
            raise work_covers.too_large()
        raw.extend(chunk)
    normalized = await run_in_threadpool(work_covers.normalized_image, bytes(raw))
    return ok(
        work_covers.add(
            work_of(request),
            request.query_params.get('base_revision'),
            request.query_params.get('filename'),
            normalized,
        )
    )


async def covers_gallery(request):
    data = await body(request)
    if not isinstance(data, dict):
        raise AppError(Msg('server.covers.gallery_scope', 'Choose an image from this work.'))
    filename, normalized = await run_in_threadpool(
        work_covers.gallery_image, st(request).image.gallery, work_of(request).id, data.get('gallery_path')
    )
    return ok(work_covers.add(work_of(request), data.get('base_revision'), filename, normalized))


async def covers_update(request):
    data = await body(request)
    if not isinstance(data, dict):
        raise AppError(Msg('server.covers.bad_order', 'Choose only covers that belong to this work.'))
    return ok(
        work_covers.update(
            work_of(request), data.get('base_revision'), data.get('ids'), data.get('primary_id')
        )
    )


async def covers_image(request):
    raw = work_covers.image(work_of(request), request.path_params['cover_id'])
    return Response(raw, media_type='image/webp', headers={'X-Content-Type-Options': 'nosniff'})


def routes():
    w = '/api/works/{wid}'
    return [
        Route('/api/works', works_list),
        Route('/api/works', works_create, methods=['POST']),
        Route('/api/samples', samples_list),
        Route('/api/samples/{name}/install', samples_install, methods=['POST']),
        Route('/api/trash', data_trash_list),
        Route('/api/trash', data_trash_purge, methods=['DELETE']),
        Route('/api/trash/{bid}/restore', data_trash_restore, methods=['POST']),
        Route('/api/trash/{bid}', data_trash_purge, methods=['DELETE']),
        Route(w, work_get),
        Route(w, works_patch, methods=['PATCH']),
        Route(w, works_delete, methods=['DELETE']),
        Route(f'{w}/duplicate', works_duplicate, methods=['POST']),
        Route(f'{w}/covers', covers_list),
        Route(f'{w}/covers', covers_gallery, methods=['POST']),
        Route(f'{w}/covers', covers_update, methods=['PUT']),
        Route(f'{w}/covers/upload', covers_upload, methods=['POST']),
        Route(f'{w}/covers/{{cover_id}}', covers_image),
    ]
