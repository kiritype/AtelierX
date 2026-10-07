"""Works: list, create, change, delete, duplicate, samples, the data trash and one work."""

from starlette.routing import Route

from ..core.snapshots import Snapshots
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
        if k
        in ('tags', 'scale', 'language', 'overrides', 'character_sections', 'char', 'order', 'llm_consent')
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
    work = s.works.install_sample(request.path_params['name'])
    Snapshots(work).create('import', '샘플 설치')
    return ok(s.works.card(work), 201)


async def data_trash_list(request):
    return ok(st(request).works.trash())


async def data_trash_restore(request):
    return ok(st(request).works.restore(request.path_params['bid']))


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
            'sections': work.section_titles(),
            'presets': s.presets.list(),
        }
    )


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
    ]
