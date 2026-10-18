"""Work and settings packages (#46, #47): pack to a ZIP download, upload one to look into, then bring it in."""

import copy
import json
import zipfile

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from ..core import packages
from ..core.i18n import wire
from ..image.uuid_migration import FileCheckpoint, migrate_runtime, migrate_runtime_guarded


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
    s = request.app.state.app
    with s.admission.exclusive(s.busy_work):
        pk = _packages(request)
        try:
            result = await run_in_threadpool(pk.import_works, data.get('token'), data.get('works'))
            await run_in_threadpool(migrate_runtime_guarded, s)
        except BaseException:
            s.admission.seal()
            await run_in_threadpool(pk.rollback_last_work_import)
            await run_in_threadpool(migrate_runtime, s.image)
            s.admission.unseal()
            raise
    return _ok(result)


async def settings_import(request):
    data = await _body(request)
    s = request.app.state.app
    with s.admission.exclusive(s.busy_work):
        pk = _packages(request)
        targets = []
        with zipfile.ZipFile(pk._upload(data.get('token'))) as archive:
            members = set(archive.namelist())
            for area in data.get('areas') or []:
                if area not in packages.SETTINGS:
                    continue
                root_name, inner, kind = packages.SETTINGS[area]
                target = getattr(s.paths, root_name) / inner
                if kind == 'files':
                    for member in members:
                        if not member.startswith(f'settings/{area}/'):
                            continue
                        parts = packages._safe_member(member)
                        if len(parts) == 3 and parts[2] != 'uuid-map.json':
                            targets.append(target / parts[2])
                else:
                    targets.append(target)
        checkpoint = FileCheckpoint(s.paths, targets)
        vault_secrets = copy.deepcopy(s.vault._secrets)
        try:
            result = await run_in_threadpool(
                pk.import_settings,
                data.get('token'),
                data.get('areas'),
                data.get('vault_password'),
            )
            await run_in_threadpool(migrate_runtime_guarded, s)
        except BaseException:
            s.admission.seal()
            checkpoint.rollback()
            s.vault._secrets = vault_secrets
            await run_in_threadpool(migrate_runtime, s.image)
            s.admission.unseal()
            raise
        finally:
            if not s.admission.quarantined:
                checkpoint.close()
    return _ok(result)


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
