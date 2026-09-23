"""Loopback-only HTTP surface: static UI, `/api/*` for the local browser, `/status` for Core."""
from __future__ import annotations

import argparse
import asyncio
import hmac
import sys
import webbrowser
from pathlib import Path

from aiohttp import web

from ..common import ProcessLock
from .config import ControlPaths
from .panel import Panel, tail
from .shortcut import StartupShortcut

UI = Path(__file__).resolve().parent / "ui"
ASSETS = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "styles.css": "text/css; charset=utf-8"}
MUTATING = {"POST", "PUT", "DELETE", "PATCH"}
PANEL = web.AppKey("panel", Panel)
SHORTCUT = web.AppKey("shortcut", StartupShortcut)
TOKEN = web.AppKey("token", str)


def forbidden(message="forbidden"):
    return web.json_response({"error": message}, status=403)


def security_middleware(port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in hosts}

    @web.middleware
    async def guard(request, handler):
        # Host allow-list blocks DNS rebinding; custom header + Origin block cross-site (CSRF) writes.
        if request.headers.get("Host", "").lower() not in hosts:
            return forbidden("host not allowed")
        if request.path == "/status":
            expected = request.app[TOKEN]
            supplied = request.headers.get("Authorization", "")
            if request.method != "GET" or not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:].encode(), expected.encode()):
                return web.json_response({"error": "unauthorized"}, status=401)
        elif request.path.startswith("/api/") and request.method in MUTATING:
            if request.headers.get("X-AtelierX-Control") != "1":
                return forbidden("missing control header")
            origin = request.headers.get("Origin")
            if origin is not None and origin not in origins:
                return forbidden("origin not allowed")
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    return guard


def item_id(request):
    value = request.match_info["item"]
    if value not in request.app[PANEL].items:
        raise web.HTTPNotFound()
    return value


async def index(request):
    return asset_response("index.html")


async def asset(request):
    return asset_response(request.match_info["name"])


def asset_response(name):
    path = UI / name
    if name not in ASSETS or not path.is_file():
        raise web.HTTPNotFound()
    return web.Response(body=path.read_bytes(), headers={"Content-Type": ASSETS[name]})


async def core_status(request):
    panel = request.app[PANEL]
    return web.json_response(panel.status(await panel.dependency_checks()))


async def api_status(request):
    return web.json_response(request.app[PANEL].ui_status())


async def api_action(request):
    panel, target, action = request.app[PANEL], item_id(request), request.match_info["action"]
    if action not in {"start", "stop", "restart"}:
        raise web.HTTPNotFound()
    if panel.busy(target):
        return web.json_response({"error": "다른 작업이 진행 중입니다."}, status=409)
    panel.start_op(target, action)
    await asyncio.sleep(0)
    return web.json_response({"accepted": True, "item": target, "action": action}, status=202)


async def api_settings(request):
    panel = request.app[PANEL]
    if request.method == "PUT":
        try:
            body = await request.json()
            panel.settings.update(body)
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)
    return web.json_response(panel.settings.public())


async def api_logs(request):
    panel, target = request.app[PANEL], item_id(request)
    path = panel.items[target].log_path()
    try:
        lines = max(1, min(int(request.query.get("lines", "200")), 1000))
    except ValueError:
        lines = 200
    return web.json_response({"item": target, "file": Path(path).name if path else None,
                              "lines": await asyncio.to_thread(tail, path, lines) if path else []})


async def api_dependencies(request):
    panel = request.app[PANEL]
    checks = await panel.dependency_checks(refresh=request.method == "POST")
    return web.json_response({"dependencies": checks})


async def api_shortcut(request):
    shortcut = request.app[SHORTCUT]
    try:
        if request.method == "POST":
            await asyncio.to_thread(shortcut.create)
        elif request.method == "DELETE":
            await asyncio.to_thread(shortcut.remove)
    except (OSError, RuntimeError) as error:
        return web.json_response({"error": str(error), "exists": shortcut.exists()}, status=500)
    return web.json_response({"exists": shortcut.exists()})


def create_app(panel: Panel, token: str, shortcut: StartupShortcut) -> web.Application:
    app = web.Application(middlewares=[security_middleware(panel.port)], client_max_size=64 * 1024)
    app[PANEL], app[TOKEN], app[SHORTCUT] = panel, token, shortcut
    app.add_routes([
        web.get("/", index), web.get("/ui/{name}", asset), web.get("/status", core_status),
        web.get("/api/status", api_status), web.post("/api/items/{item}/{action}", api_action),
        web.get("/api/settings", api_settings), web.put("/api/settings", api_settings),
        web.get("/api/logs/{item}", api_logs),
        web.get("/api/dependencies", api_dependencies), web.post("/api/dependencies/refresh", api_dependencies),
        web.get("/api/startup-shortcut", api_shortcut), web.post("/api/startup-shortcut", api_shortcut),
        web.delete("/api/startup-shortcut", api_shortcut),
    ])
    return app


async def serve(paths: ControlPaths, port: int, autostart: bool, open_browser: bool, startup_dir=None):
    paths.ensure()
    token = paths.read_token()
    panel = Panel(paths, port=port)
    await asyncio.to_thread(panel.adopt)
    await panel.refresh()
    app = create_app(panel, token, StartupShortcut(paths.repo, startup_dir))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", port).start()
        print(f"[control] AtelierX 제어판: http://127.0.0.1:{port}/ (종료: Ctrl+C, 관리 중인 프로그램은 계속 실행됩니다)", flush=True)
        panel.background(panel.monitor())
        if autostart:
            panel.background(panel.autostart())
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        await asyncio.Event().wait()
    finally:
        await panel.close()
        await runner.cleanup()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="atelierx-control", description="AtelierX 로컬 운영 제어판 (127.0.0.1 전용)")
    parser.add_argument("--port", type=int, default=8180)
    parser.add_argument("--data-dir", help="제어판 데이터 폴더 (기본: <저장소>/.atelierx/control)")
    parser.add_argument("--no-autostart", action="store_true", help="설정된 자동 켜기를 이번 실행에서 건너뜀")
    parser.add_argument("--open-browser", action="store_true", help="준비되면 기본 브라우저로 제어판을 엶")
    args = parser.parse_args(argv)
    paths = ControlPaths(data_dir=args.data_dir)
    try:
        lock = ProcessLock(paths.lock)
    except RuntimeError:
        print("[control] 제어판이 이미 실행 중입니다.", file=sys.stderr, flush=True)
        if args.open_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}/")
        return 1
    try:
        asyncio.run(serve(paths, args.port, not args.no_autostart, args.open_browser))
    except KeyboardInterrupt:
        pass
    except OSError as error:
        print(f"[control] 시작 실패: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        lock.close()
    return 0
