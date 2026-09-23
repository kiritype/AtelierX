"""Strict static host for the same-origin pilot UI; it has no REST privileges."""
from pathlib import Path

from aiohttp import web


_ROOT = Path(__file__).resolve().parents[3] / "frontend"
_ASSETS = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "api.js": "text/javascript; charset=utf-8",
    "production.js": "text/javascript; charset=utf-8",
    "creation.js": "text/javascript; charset=utf-8",
    "review.js": "text/javascript; charset=utf-8",
    "gallery.js": "text/javascript; charset=utf-8",
    "jobs.js": "text/javascript; charset=utf-8",
    "settings.js": "text/javascript; charset=utf-8",
    "connection.js": "text/javascript; charset=utf-8",
    "fragments.js": "text/javascript; charset=utf-8",
    "fragment-picker.js": "text/javascript; charset=utf-8",
    "fragment-rules.js": "text/javascript; charset=utf-8",
    "studio-tree.js": "text/javascript; charset=utf-8",
    "lightbox.js": "text/javascript; charset=utf-8",
    "reference-sets.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}


def attach(app):
    def response(name):
        content_type = _ASSETS.get(name)
        path = _ROOT / name
        if content_type is None or not path.is_file():
            raise web.HTTPNotFound()
        return web.Response(body=path.read_bytes(), headers={"Content-Type": content_type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def asset(request):
        return response(request.match_info["asset"])

    async def index(request):
        return response("index.html")

    async def entry(request):
        # Fixed relative target: never derive a redirect from Host or user input.
        raise web.HTTPFound(location="/ui/", headers={"Cache-Control": "no-store"})

    app.add_routes([web.get("/", entry), web.get("/ui", entry), web.get("/ui/", index), web.get("/ui/{asset}", asset)])
