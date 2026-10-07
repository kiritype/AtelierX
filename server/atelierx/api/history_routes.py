"""Snapshots (09-snapshots) and export."""

from starlette.routing import Route

from ..core import exporter
from ..core.snapshots import Snapshots
from .common import body, ok, st, work_of


async def snap_list(request):
    return ok(Snapshots(work_of(request)).list())


async def snap_create(request):
    data = await body(request)
    created = Snapshots(work_of(request)).create(data.get('reason', 'manual'), data.get('label'), force=True)
    return ok(created, 201)


async def snap_save_point(request):
    """Called when a work is closed: keep a save point if anything changed since the last snapshot."""
    created = Snapshots(work_of(request)).save_point(0, force=True)
    return ok(created)


async def snap_diff(request):
    snaps = Snapshots(work_of(request))
    return ok(snaps.diff(request.path_params['sid'], request.query_params.get('against', 'parent')))


async def snap_file(request):
    snaps = Snapshots(work_of(request))
    path = request.query_params['path']
    sid = request.path_params['sid']
    current = snaps.path_in_work(path)
    return ok(
        {
            'snapshot': snaps.file_text(sid, path),
            'current': current.read_text(encoding='utf-8') if current.is_file() else None,
        }
    )


async def snap_restore(request):
    data = await body(request)
    return ok(Snapshots(work_of(request)).restore(request.path_params['sid'], data.get('paths')))


async def snap_patch(request):
    data = await body(request)
    return ok(Snapshots(work_of(request)).mark_release(request.path_params['sid'], data.get('release')))


async def export_preview(request):
    work = work_of(request)
    include, skip = exporter.plan(work)
    target = request.query_params.get('target')
    blocked = exporter.blocked_target(target, st(request).paths.root, work.folder) if target else None
    return ok(
        {
            'include': [i['path'] for i in include],
            'skip': skip,
            'keywords_file': exporter.KEYWORDS_FILE,
            'clash': exporter.name_clash(include),
            'target': exporter.target_state(target, include),
            'blocked': blocked.as_dict() if blocked else None,
        }
    )


async def export_run(request):
    return ok(st(request).work_jobs.export(work_of(request), await body(request)))


def routes():
    w = '/api/works/{wid}'
    return [
        Route(f'{w}/snapshots', snap_list),
        Route(f'{w}/snapshots', snap_create, methods=['POST']),
        Route(f'{w}/snapshots/save-point', snap_save_point, methods=['POST']),
        Route(f'{w}/snapshots/{{sid}}/diff', snap_diff),
        Route(f'{w}/snapshots/{{sid}}/file', snap_file),
        Route(f'{w}/snapshots/{{sid}}/restore', snap_restore, methods=['POST']),
        Route(f'{w}/snapshots/{{sid}}', snap_patch, methods=['PATCH']),
        Route(f'{w}/export/preview', export_preview),
        Route(f'{w}/export', export_run, methods=['POST']),
    ]
