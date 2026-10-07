"""Helpers every route module uses: JSON answers and bodies, the app state and the work in the path."""

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from ..core.i18n import AppError, Msg, wire

if TYPE_CHECKING:
    from .app import State


def ok(value=None, status=200):
    return JSONResponse(wire(value) if value is not None else {'ok': True}, status_code=status)


async def body(request):
    raw = await request.body()
    try:
        return json.loads(raw) if raw else {}
    except ValueError as exc:  # not JSON, or not UTF-8: the request's fault, not a server error
        raise AppError(
            Msg('server.request.invalid_json', 'The request body is not valid JSON.'), 400
        ) from exc


def st(request) -> 'State':
    return request.app.state.app


def work_of(request):
    return st(request).works.get(request.path_params['wid'])
