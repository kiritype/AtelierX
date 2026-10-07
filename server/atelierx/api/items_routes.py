"""Inside a work: files and folders, checks, search, the work trash, renaming across the work, JSX example props, the relation map and the glossary."""

from starlette.routing import Route

from ..core import checks, rename, review
from ..core import item_import as item_import_core
from ..core.i18n import AppError, Msg
from ..core.jsx import Props
from ..core.relations import Glossary, Relations
from ..core.snapshots import Snapshots
from ..core.works import KIND_PREFIX
from .common import body, ok, st, work_of
from .draft_routes import item_by_id


async def work_tree(request):
    return ok(work_of(request).tree())


def _with_links(work, item):
    # The editor locks the ID field while other data refers to the ID.
    return {**item, 'id_links': work.id_links(item['meta'].get('id'))}


async def item_get(request):
    work = work_of(request)
    return ok(_with_links(work, work.get_item(request.query_params['path'])))


async def item_put(request):
    data = await body(request)
    work = work_of(request)
    saved = work.save_item(
        request.query_params['path'], data.get('meta'), data.get('body'), data.get('base_hash')
    )
    Snapshots(work).save_point(st(request).settings.load().get('snapshot_interval_minutes'))
    return ok(_with_links(work, saved))


async def item_create(request):
    data = await body(request)
    return ok(work_of(request).create_file(data['path'], data.get('kind')), 201)


async def item_import(request):
    """Bring single .md/.jsx files in (#115): a preview of what each becomes, or (``apply``) writing them."""
    data = await body(request)
    work = work_of(request)
    args = (work, data.get('folder'), data.get('files'), data.get('choices'))
    if data.get('apply'):
        return ok(item_import_core.apply(*args))
    return ok(item_import_core.public(item_import_core.plan(*args)))


async def folder_create(request):
    data = await body(request)
    return ok(work_of(request).create_folder(data['path']), 201)


async def item_move(request):
    data = await body(request)
    return ok(work_of(request).move(data['from'], data['to']))


async def item_kind(request):
    data = await body(request)
    return ok(work_of(request).change_kind(data['path'], data['kind']))


async def item_delete(request):
    work = work_of(request)
    return ok(work.delete(request.query_params['path'], request.query_params.get('extras') == '1'))


async def suggest_item_id(request):
    kind = request.query_params.get('kind', 'lorebook')
    return ok({'id': work_of(request).suggest_id(kind) if kind in KIND_PREFIX else ''})


async def work_check(request):
    s = st(request)
    work = work_of(request)
    return ok(checks.run(work, s.presets.effective(work.doc())))


async def work_search(request):
    query = request.query_params.get('q', '').lower()
    work = work_of(request)
    hits = []
    if query:
        for path in work.item_paths():
            item = work.read_item(path)
            lines = [
                (n + 1, line) for n, line in enumerate(item['body'].splitlines()) if query in line.lower()
            ]
            names = query in item['name'].lower() or query in str(item['meta'].get('id', '')).lower()
            if lines or names:
                hits.append({'path': item['path'], 'name': item['name'], 'lines': lines[:20]})
    return ok(hits)


async def work_trash(request):
    return ok(work_of(request).trash())


async def work_trash_restore(request):
    work = work_of(request)
    Snapshots(work).create('before_bulk', '휴지통에서 되살리기 전')
    return ok(work.restore_trash(request.path_params['bid']))


async def work_trash_purge(request):
    work_of(request).purge_trash(request.path_params.get('bid'))
    return ok()


async def rename_preview(request):
    data = await body(request)
    work = work_of(request)
    return ok(rename.preview(work, data.get('find', ''), data.get('replace', ''), data.get('targets')))


async def rename_apply(request):
    data = await body(request)
    work = work_of(request)
    Snapshots(work).create('before_bulk', f'이름 바꾸기 전: {data.get("find", "")}', force=True)
    return ok(rename.apply(work, data['find'], data['replace'], data.get('hits', [])))


def _props(request):
    # The component name turns old JSON examples into calls; an item without that ID still lists its examples.
    work, jsx_id = work_of(request), request.path_params['jid']
    try:
        name = item_by_id(work, jsx_id, 'jsx')['name']
    except AppError:
        name = 'Component'
    return Props(work, jsx_id, name, review.response_rule(st(request).presets.effective(work.doc())))


async def props_list(request):
    return ok(_props(request).list())


async def props_put(request):
    text = (await request.body()).decode('utf-8')
    # Examples are written only for a JSX item that exists, never under a stray ID (e.g. before the item has one).
    work, jsx_id = work_of(request), request.path_params['jid']
    if not any(i['meta'].get('id') == jsx_id and i['kind'] == 'jsx' for i in work.index()):
        raise AppError(Msg('server.jsx.no_item', 'There is no JSX item with the ID {id}.', id=jsx_id), 404)
    return ok(_props(request).save(request.path_params['name'], text))


async def props_delete(request):
    return ok(_props(request).delete(request.path_params['name']))


async def relations_get(request):
    return ok(Relations(work_of(request)).view())


async def relations_put(request):
    return ok(Relations(work_of(request)).update(await body(request)))


async def glossary_get(request):
    return ok(Glossary(work_of(request)).view())


async def glossary_put(request):
    return ok(Glossary(work_of(request)).update(await body(request)))


def routes():
    w = '/api/works/{wid}'
    return [
        Route(f'{w}/tree', work_tree),
        Route(f'{w}/file', item_get),
        Route(f'{w}/file', item_put, methods=['PUT']),
        Route(f'{w}/file', item_create, methods=['POST']),
        Route(f'{w}/file', item_delete, methods=['DELETE']),
        Route(f'{w}/folder', folder_create, methods=['POST']),
        Route(f'{w}/import', item_import, methods=['POST']),
        Route(f'{w}/move', item_move, methods=['POST']),
        Route(f'{w}/kind', item_kind, methods=['POST']),
        Route(f'{w}/suggest-id', suggest_item_id),
        Route(f'{w}/check', work_check),
        Route(f'{w}/search', work_search),
        Route(f'{w}/trash', work_trash),
        Route(f'{w}/trash', work_trash_purge, methods=['DELETE']),
        Route(f'{w}/trash/{{bid}}/restore', work_trash_restore, methods=['POST']),
        Route(f'{w}/trash/{{bid}}', work_trash_purge, methods=['DELETE']),
        Route(f'{w}/jsx/{{jid}}/props', props_list),
        Route(f'{w}/jsx/{{jid}}/props/{{name}}', props_put, methods=['PUT']),
        Route(f'{w}/jsx/{{jid}}/props/{{name}}', props_delete, methods=['DELETE']),
        Route(f'{w}/rename-text/preview', rename_preview, methods=['POST']),
        Route(f'{w}/rename-text', rename_apply, methods=['POST']),
        Route(f'{w}/relations', relations_get),
        Route(f'{w}/relations', relations_put, methods=['PUT']),
        Route(f'{w}/glossary', glossary_get),
        Route(f'{w}/glossary', glossary_put, methods=['PUT']),
    ]
