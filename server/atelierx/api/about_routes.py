"""Help menu: about, licences, opening in the browser and the update check."""

import webbrowser

from starlette.responses import Response
from starlette.routing import Route

from ..core import about
from ..core.i18n import AppError, Msg
from .common import ok, st


async def about_get(request):
    return ok({**about.info(st(request).paths), 'desktop': st(request).desktop})


async def open_in_browser(request):
    if not st(request).desktop:
        raise AppError(
            Msg('server.about.not_desktop', 'Only the desktop window can open the app in a browser.'), 400
        )
    webbrowser.open(str(request.base_url))
    return ok({'url': str(request.base_url)})


async def about_notices(request):
    return Response(about.notices(st(request).paths), media_type='text/plain; charset=utf-8')


async def update_check(request):
    return ok(await about.check_update())


async def update_status(request):
    return ok(st(request).updater.status())


async def update_start(request):
    return ok(st(request).updater.start())


async def update_apply(request):
    return ok(st(request).updater.apply())


async def update_forget(request):
    st(request).updater.forget_result()
    return ok()


def routes():
    return [
        Route('/api/about', about_get),
        Route('/api/about/notices', about_notices),
        Route('/api/update-check', update_check),
        Route('/api/update/status', update_status),
        Route('/api/update/start', update_start, methods=['POST']),
        Route('/api/update/apply', update_apply, methods=['POST']),
        Route('/api/update/forget', update_forget, methods=['POST']),
        Route('/api/open-in-browser', open_in_browser, methods=['POST']),
    ]
