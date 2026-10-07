"""Unlock, first setup, lock and reset (01-auth)."""

import asyncio

from starlette.routing import Route

from ..core.i18n import AppError, Msg
from ..core.vault import MIN_PASSWORD
from .common import body, ok, st


def _session_response(request, value):
    response = ok(value)
    response.set_cookie(
        st(request).cookie_name, st(request).sessions.issue(), httponly=True, samesite='strict'
    )
    return response


async def auth_status(request):
    s = st(request)
    return ok(
        {
            'initialized': s.vault.initialized,
            'unlocked': s.sessions.valid(request.cookies.get(st(request).cookie_name)),
            'language': s.settings.load()['language'],
            'wait': round(s.sessions.wait_seconds()),
            'password_change_suggested': s.password_change_suggested,
        }
    )


async def auth_setup(request):
    data = await body(request)
    s = st(request)
    s.vault.setup(data.get('password', ''))
    s.password_change_suggested = False
    s.settings.update({'language': data.get('language', 'ko')})
    return _session_response(request, {'ok': True})


async def auth_unlock(request):
    s = st(request)
    if s.sessions.wait_seconds() > 0:
        raise AppError(
            Msg('server.auth.wait', 'Try again in {n} seconds.', n=round(s.sessions.wait_seconds())), 429
        )
    data = await body(request)
    password = data.get('password', '')
    try:
        await asyncio.to_thread(s.vault.unlock, password)
    except AppError:
        s.sessions.failed()
        raise
    s.password_change_suggested = isinstance(password, str) and len(password) < MIN_PASSWORD
    return _session_response(request, {'ok': True, 'password_change_suggested': s.password_change_suggested})


async def auth_lock(request):
    s = st(request)
    s.vault.lock()
    s.sessions.clear()
    s.events.publish('lock')
    response = ok()
    response.delete_cookie(st(request).cookie_name)
    return response


async def auth_reset(request):
    data = await body(request)
    if data.get('confirm') != 'RESET':
        raise AppError(Msg('server.auth.reset_confirm', 'Type RESET to confirm.'))
    s = st(request)
    s.vault.reset(data.get('password', ''))
    s.sessions.clear()
    s.password_change_suggested = False
    return _session_response(request, {'ok': True})


def routes():
    return [
        Route('/api/auth/status', auth_status),
        Route('/api/auth/setup', auth_setup, methods=['POST']),
        Route('/api/auth/unlock', auth_unlock, methods=['POST']),
        Route('/api/auth/lock', auth_lock, methods=['POST']),
        Route('/api/auth/reset', auth_reset, methods=['POST']),
    ]
