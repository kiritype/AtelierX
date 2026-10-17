"""Settings, screen state, the vault and platform presets."""

import asyncio

from starlette.routing import Route

from ..core import guidelines, personas
from ..core.fsutil import read_json, write_json
from ..core.i18n import AppError, Msg
from .common import body, ok, st


async def settings_get(request):
    return ok(st(request).settings.load())


async def settings_patch(request):
    return ok(st(request).settings.update(await body(request)))


async def compression_guideline_get(request):
    return ok(guidelines.compression_settings(st(request).paths))


async def compression_guideline_put(request):
    return ok(guidelines.save_compression_settings(st(request).paths, await body(request)))


async def personas_get(request):
    return ok(personas.load(st(request).paths))


async def personas_put(request):
    return ok(personas.save(st(request).paths, await body(request)))


async def ui_state_get(request):
    return ok(read_json(st(request).paths.state / 'ui.json', {}))


async def ui_state_put(request):
    write_json(st(request).paths.state / 'ui.json', await body(request))
    return ok()


async def ui_state_patch(request):
    """Merge only the supplied screen state after reading the latest file.

    The read/merge/write section has no await: requests on this server's event loop
    cannot interleave there. The persisted ui.json shape stays unchanged.
    """
    changes = await body(request)
    if not isinstance(changes, dict) or set(changes) - {'works', 'last_work', 'persona_by_work'}:
        raise AppError(Msg('server.request.invalid_ui_state', 'Invalid UI state update.'), 400)
    for key in ('works', 'persona_by_work'):
        if key in changes and (
            not isinstance(changes[key], dict) or not all(isinstance(k, str) and k for k in changes[key])
        ):
            raise AppError(Msg('server.request.invalid_ui_state', 'Invalid UI state update.'), 400)
    if 'works' in changes and not all(isinstance(value, dict) for value in changes['works'].values()):
        raise AppError(Msg('server.request.invalid_ui_state', 'Invalid UI state update.'), 400)
    if 'persona_by_work' in changes and not all(
        value is None or isinstance(value, str) for value in changes['persona_by_work'].values()
    ):
        raise AppError(Msg('server.request.invalid_ui_state', 'Invalid UI state update.'), 400)
    if 'last_work' in changes and not isinstance(changes['last_work'], str):
        raise AppError(Msg('server.request.invalid_ui_state', 'Invalid UI state update.'), 400)

    path = st(request).paths.state / 'ui.json'
    state = read_json(path, {})
    if 'last_work' in changes:
        state['last_work'] = changes['last_work']
    if 'works' in changes:
        works = state.setdefault('works', {})
        for work_id, update in changes['works'].items():
            current = works.get(work_id, {})
            merged = {**current, **update}
            if isinstance(current.get('sidebar'), dict) and isinstance(update.get('sidebar'), dict):
                merged['sidebar'] = {**current['sidebar'], **update['sidebar']}
            works[work_id] = merged
    if 'persona_by_work' in changes:
        personas_by_work = state.setdefault('persona_by_work', {})
        for work_id, persona_id in changes['persona_by_work'].items():
            if persona_id is None:
                personas_by_work.pop(work_id, None)
            else:
                personas_by_work[work_id] = persona_id
    write_json(path, state)
    return ok(state)


async def vault_list(request):
    return ok(st(request).vault.list())


async def vault_put(request):
    data = await body(request)
    st(request).vault.put(data['name'], data.get('kind', 'other'), data['value'], data.get('note', ''))
    return ok()


async def vault_delete(request):
    st(request).vault.delete(request.path_params['name'])
    return ok()


async def vault_password(request):
    data = await body(request)
    await asyncio.to_thread(st(request).vault.change_password, data.get('old', ''), data.get('new', ''))
    st(request).password_change_suggested = False
    return ok()


async def presets_list(request):
    return ok(st(request).presets.list())


async def presets_create(request):
    data = await body(request)
    return ok(
        st(request).presets.create(data['id'], data.get('name', data['id']), data.get('base', 'generic'))
    )


async def presets_get(request):
    return ok(st(request).presets.get(request.path_params['pid']))


async def presets_put(request):
    return ok(st(request).presets.save(request.path_params['pid'], await body(request)))


async def presets_delete(request):
    s = st(request)
    return ok(s.presets.delete(request.path_params['pid'], s.works.all(), s.settings.load()))


def routes():
    return [
        Route('/api/settings', settings_get),
        Route('/api/settings', settings_patch, methods=['PATCH']),
        Route('/api/settings/compression-guideline', compression_guideline_get),
        Route('/api/settings/compression-guideline', compression_guideline_put, methods=['PUT']),
        Route('/api/personas', personas_get),
        Route('/api/personas', personas_put, methods=['PUT']),
        Route('/api/ui-state', ui_state_get),
        Route('/api/ui-state', ui_state_put, methods=['PUT']),
        Route('/api/ui-state', ui_state_patch, methods=['PATCH']),
        Route('/api/vault', vault_list),
        Route('/api/vault', vault_put, methods=['POST']),
        Route('/api/vault/password', vault_password, methods=['POST']),
        Route('/api/vault/{name}', vault_delete, methods=['DELETE']),
        Route('/api/platforms', presets_list),
        Route('/api/platforms', presets_create, methods=['POST']),
        Route('/api/platforms/{pid}', presets_get),
        Route('/api/platforms/{pid}', presets_put, methods=['PUT']),
        Route('/api/platforms/{pid}', presets_delete, methods=['DELETE']),
    ]
