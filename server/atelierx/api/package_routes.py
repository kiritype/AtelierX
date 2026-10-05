"""Work and settings packages (#46, #47): pack to a ZIP download, upload one to look into, then bring it in."""

import json

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from ..core import packages
from ..core.i18n import wire


def _packages(request):
    return request.app.state.app.packages


async def _body(request):
    raw = await request.body()
    return json.loads(raw) if raw else {}


def _ok(value):
    return JSONResponse(wire(value))


def _download(path, name):
    return FileResponse(
        path,
        media_type='application/zip',
        filename=name,
        background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
    )


async def works_plan(request):
    data = await _body(request)
    return _ok(await run_in_threadpool(_packages(request).plan_works, data.get('ids'), data.get('options')))


async def works_export(request):
    data = await _body(request)
    ids = list(data.get('ids') or [])
    path = await run_in_threadpool(_packages(request).export_works, ids, data.get('options'))
    return _download(path, packages.download_name('works', ids))


async def settings_export(request):
    data = await _body(request)
    path = await run_in_threadpool(_packages(request).export_settings, data.get('areas'))
    return _download(path, packages.download_name('settings'))


async def upload(request):
    """The package file as the request body, written straight to a file; answers what is in it and a token to bring
    it in."""
    pk = _packages(request)
    token, path = pk.new_upload()
    try:
        with path.open('wb') as out:
            async for chunk in request.stream():
                out.write(chunk)
        return _ok(await run_in_threadpool(pk.inspect, token))
    except Exception:
        path.unlink(missing_ok=True)
        raise


async def works_import(request):
    data = await _body(request)
    return _ok(await run_in_threadpool(_packages(request).import_works, data.get('token'), data.get('works')))


async def settings_import(request):
    data = await _body(request)
    return _ok(
        await run_in_threadpool(
            _packages(request).import_settings,
            data.get('token'),
            data.get('areas'),
            data.get('vault_password'),
        )
    )


def routes():
    p = '/api/packages'
    return [
        Route(f'{p}/works/plan', works_plan, methods=['POST']),
        Route(f'{p}/works/export', works_export, methods=['POST']),
        Route(f'{p}/settings/export', settings_export, methods=['POST']),
        Route(f'{p}/upload', upload, methods=['POST']),
        Route(f'{p}/works/import', works_import, methods=['POST']),
        Route(f'{p}/settings/import', settings_import, methods=['POST']),
    ]
