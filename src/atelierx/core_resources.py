"""Core's authenticated read-only view of Generation's registered resources."""
from aiohttp import web

from .common import ApiError


def attach(app, core):
    async def resources(request):
        result = await core.generation("GET", "/v1/resources")
        if result is None:
            raise ApiError("CORE_GENERATION_UNAVAILABLE", "Generation resource catalog is unavailable; update Generation", 503)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    app.router.add_get("/v1/generation/resources", resources)
