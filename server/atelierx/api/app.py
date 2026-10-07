"""HTTP API (Starlette). Every route except /api/auth/* needs a session (architecture: 인증과 세션)."""

import contextlib
from datetime import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..core.auth import COOKIE, Sessions
from ..core.bootstrap import ensure_layout
from ..core.events import Events
from ..core.fsutil import read_json, sha256_text, write_json
from ..core.i18n import AppError, Msg
from ..core.jobs import Jobs
from ..core.llm import LlmGate, Providers
from ..core.packages import Packages
from ..core.presets import Presets
from ..core.settings import Settings
from ..core.snapshots import Snapshots
from ..core.updater import Updater
from ..core.vault import Vault
from ..core.work_jobs import WorkJobs
from ..core.works import WorkStore
from ..image.runtime import ImageRuntime
from . import (
    about_routes,
    agent_routes,
    auth_routes,
    chat_routes,
    design_routes,
    draft_routes,
    editor_routes,
    history_routes,
    image_routes,
    items_routes,
    jobs_routes,
    llm_routes,
    lora_routes,
    package_routes,
    settings_routes,
    tool_routes,
    works_routes,
)
from .common import st


class State:
    def __init__(self, paths, dev=False, kdf=None, desktop=False):
        self.paths = paths
        # The desktop window (pywebview) can hand the same address to the system browser.
        self.desktop = desktop
        self.cookie_name = COOKIE + '_' + sha256_text(str(paths.root.resolve()).casefold())[:12]
        self.dev = dev
        ensure_layout(paths)
        self.vault = Vault(paths.vault_file, kdf=kdf)
        self.sessions = Sessions()
        self.settings = Settings(paths.settings_file)
        self.works = WorkStore(paths)
        self.presets = Presets(paths)
        self.events = Events()
        self.jobs = Jobs(self.events)
        self.llm = Providers(paths, self.vault)
        self.image = ImageRuntime(paths, self.works, self.llm)
        self.work_jobs = WorkJobs(paths, self.llm, self.presets, self.events, self.jobs)
        self.llm.gate = LlmGate(
            self.image.gpu, lambda: (self.settings.load().get('jobs') or {}).get('api_concurrency', 2)
        )
        self.packages = Packages(paths, self.works, self.image, self.vault)
        self.updater = Updater(paths, busy=self.busy_work)
        self.maintain()

    def busy_work(self):
        """What an update would cut off: image work in the queue, LoRA training, installs, LLM jobs."""
        busy = []
        with self.image.lock:
            if any(j['status'] in ('queued', 'running', 'cancelling') for j in self.image.jobs):
                busy.append(Msg('server.update.busy_images', 'image work in the queue'))
        if self.image.trainer.active:
            busy.append(Msg('server.update.busy_training', 'LoRA training'))
        if (self.image.installs.run or {}).get('status') == 'running':
            busy.append(Msg('server.update.busy_install', 'an install'))
        if any(j['status'] in ('queued', 'running') for j in self.jobs.jobs.values()):
            busy.append(Msg('server.update.busy_jobs', 'LLM jobs'))
        return busy

    def maintain(self):
        """Once a day at start: prune old save snapshots in every work (09-snapshots: 정리)."""
        marker = self.paths.state / 'maintenance.json'
        today = datetime.now().astimezone().strftime('%Y-%m-%d')
        if (read_json(marker) or {}).get('pruned') == today:
            return
        rule = self.settings.load().get('history_prune') or {}
        for work in self.works.all():
            Snapshots(work).prune(rule.get('keep_recent', 200), rule.get('daily_days', 30))
        write_json(marker, {'pruned': today})


# --- middleware ------------------------------------------------------------------------------------------------
class Guard(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith('/api/'):
            if _unsafe_api_path(request.scope['path']):
                return JSONResponse(
                    {'error': Msg('server.works.bad_path', 'This path is not allowed.').as_dict()},
                    status_code=400,
                )
            origin = request.headers.get('origin')
            if origin and not _origin_ok(origin, request, st(request).dev):
                return JSONResponse(
                    {'error': Msg('server.auth.bad_origin', 'Request from another site.').as_dict()},
                    status_code=403,
                )
            if not path.startswith('/api/auth/') and not st(request).sessions.valid(
                request.cookies.get(st(request).cookie_name)
            ):
                return JSONResponse(
                    {'error': Msg('server.auth.required', 'Unlock the app first.').as_dict()}, status_code=401
                )
        try:
            response = await call_next(request)
            if path.startswith('/api/') and 'cache-control' not in response.headers:
                # API answers change with every edit; a cached one would show stale data.
                response.headers['Cache-Control'] = 'no-store'
            if path.startswith('/assets/'):
                # Bundled files only. The preview frame has an opaque origin and loads them as CORS module scripts.
                response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        except AppError as error:
            return JSONResponse({'error': error.msg.as_dict()}, status_code=error.status)


def _unsafe_api_path(path):
    """IDs and names in API URLs become file names (trash bundles, drafts, examples …). None of them needs a backslash,
    a colon or a dot segment, and on Windows each of those can step out of the folder the ID belongs to."""
    # A part made only of dots and spaces ('..', '...', '. ') is the current or parent folder to Windows.
    return any(c in path for c in '\\:\x00') or any(part and not part.strip('. ') for part in path.split('/'))


def _origin_ok(origin, request, dev):
    host = request.headers.get('host', '')
    allowed = {f'http://{host}'}
    if dev:
        allowed |= {'http://localhost:5173', 'http://127.0.0.1:5173'}
    return origin in allowed


async def handle_app_error(request, error):
    return JSONResponse({'error': error.msg.as_dict()}, status_code=error.status)


# --- static web --------------------------------------------------------------------------------------------------
def spa(web_dir: Path):
    async def index(request):
        if request.path_params.get('rest', '').startswith('api/'):
            return JSONResponse(
                {'error': Msg('server.api.not_found', 'Unknown API address.').as_dict()}, status_code=404
            )
        # The sandboxed JSX preview is its own page; everything else is the app.
        page = 'preview.html' if request.path_params.get('rest') == 'preview.html' else 'index.html'
        target = web_dir / page
        if target.is_file():
            return FileResponse(target)
        return Response(
            'Web UI is not built. Run the dev server (npm run dev) or build it (npm run build).',
            media_type='text/plain',
            status_code=503,
        )

    return index


def build_app(paths, dev=False, kdf=None, desktop=False):
    routes = [
        *auth_routes.routes(),
        *about_routes.routes(),
        *settings_routes.routes(),
        *llm_routes.routes(),
        *works_routes.routes(),
        *items_routes.routes(),
        *history_routes.routes(),
        *draft_routes.routes(),
        *design_routes.routes(),
        *chat_routes.routes(),
        *jobs_routes.routes(),
        *agent_routes.routes(),
        *editor_routes.routes(),
        *image_routes.routes(),
        *tool_routes.routes(),
        *lora_routes.routes(),
        *package_routes.routes(),
    ]
    if paths.web.is_dir() and (paths.web / 'assets').is_dir():
        routes.append(Mount('/assets', StaticFiles(directory=paths.web / 'assets')))
    # The packaged app carries the offline manual beside the executable; Help opens it from here.
    if (paths.root / 'manual' / 'index.html').is_file():
        routes.append(Mount('/manual', StaticFiles(directory=paths.root / 'manual', html=True)))
    routes.append(Route('/{rest:path}', spa(paths.web)))
    state = State(paths, dev=dev, kdf=kdf, desktop=desktop)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        # The image worker thread lives as long as the server.
        state.image.start()
        try:
            yield
        finally:
            state.image.shutdown()

    app = Starlette(
        routes=routes,
        middleware=[Middleware(Guard)],
        exception_handlers={AppError: handle_app_error},
        lifespan=lifespan,
    )
    app.state.app = state
    return app
