"""Panel state: items, periodic observation, operations, autostart and dependency cache."""
from __future__ import annotations

import asyncio
import os
import time

import aiohttp

from . import deps, procs
from .config import ITEM_IDS, ControlPaths, Settings, StateStore
from .items import ComfyUIItem, LmStudioItem, OperationError, ServicesItem, TunnelItem

AUTOSTART_STAGES = (("comfyui", "lmstudio"), ("services",), ("tunnel",))
DEFAULT_URLS = {"core": "http://127.0.0.1:8190", "comfyui": "http://127.0.0.1:8188"}


class Panel:
    def __init__(self, paths: ControlPaths, port=8180, urls=None, ports=None, item_classes=None, poll_interval=1.0):
        self.paths = paths
        self.port = port
        self.pid = os.getpid()
        self.urls = dict(DEFAULT_URLS, **(urls or {}))
        self.ports = dict(ports or {})
        self.poll_interval = poll_interval
        self.settings = Settings(paths)
        self.store = StateStore(paths)
        self.last_logs = {}
        classes = item_classes or (ServicesItem, ComfyUIItem, LmStudioItem, TunnelItem)
        self.items = {cls.id: cls(self) for cls in classes}
        self.session = None
        self.dependencies = []
        self.dependencies_at = 0.0
        self.dependency_lock = asyncio.Lock()
        self.refresh_lock = asyncio.Lock()
        self.autostart_status = {"state": "idle", "error": None}
        self.tasks = set()

    async def open(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        if self.session is not None:
            await self.session.close()
            self.session = None

    def background(self, coroutine):
        task = asyncio.ensure_future(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def http_status(self, url, headers=None, timeout=3):
        await self.open()
        try:
            async with self.session.get(url, headers=headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                return response.status
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return None

    async def http_json(self, url, headers=None, timeout=5):
        await self.open()
        try:
            async with self.session.get(url, headers=headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status != 200:
                    return None
                return await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            return None

    async def core_gpu_busy(self):
        """True/False from Core GPU owner/waiting; None when Core or its token is unavailable (check skipped)."""
        try:
            token = self.paths.pilot_token.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not token:
            return None
        state = await self.http_json(self.urls["core"] + "/v1/gpu", headers={"Authorization": "Bearer " + token}, timeout=3)
        if not isinstance(state, dict):
            return None
        return bool(state.get("owner") or state.get("waiting"))

    def adopt(self):
        for item in self.items.values():
            item.adopt()

    def observe(self):
        ports, table = procs.listening_ports(), procs.process_table()
        for item in self.items.values():
            item.observed = item.observe(ports, table)

    async def refresh(self):
        async with self.refresh_lock:
            await asyncio.to_thread(self.observe)

    async def monitor(self, interval=3.0):
        while True:
            try:
                await self.refresh()
                self.cached_dependencies()
            except Exception as error:  # keep monitoring; a single failed probe must not end the loop
                print(f"[control] status refresh failed: {type(error).__name__}", flush=True)
            await asyncio.sleep(interval)

    def busy(self, item_id) -> bool:
        return self.items[item_id].lock.locked()

    async def run_op(self, item_id, action):
        """Run start/stop/restart; returns None on success or a short Korean error."""
        item = self.items[item_id]
        if item.lock.locked():
            return f"{item.label}: 다른 작업이 진행 중입니다."
        async with item.lock:
            item.active_work = None
            try:
                if action in {"stop", "restart"}:
                    item.op = "stopping"
                    await item.stop()
                    item.last_result = f"{item.label} 종료됨"
                if action in {"start", "restart"}:
                    item.op = "starting"
                    await item.start()
                    await item.wait_ready()
                    item.last_result = f"{item.label} 준비됨"
                item.last_error = None
                return None
            except OperationError as error:
                item.last_error, item.active_work = error.message, error.active_work
                return item.last_error
            except Exception as error:
                item.last_error = f"{item.label} 작업 중 오류: {type(error).__name__}"
                return item.last_error
            finally:
                item.op = None
                await self.refresh()
                self.background(self.dependency_checks(refresh=True))

    def start_op(self, item_id, action):
        return self.background(self.run_op(item_id, action))

    async def ensure_ready(self, item_id):
        item = self.items[item_id]
        if await item.is_ready():
            return None
        return await self.run_op(item_id, "start")

    async def autostart(self, stages=AUTOSTART_STAGES):
        chosen_stages = [[item_id for item_id in stage if item_id in self.items and self.settings.value["autostart"].get(item_id)] for stage in stages]
        if not any(chosen_stages):
            return self.autostart_status
        self.autostart_status = {"state": "running", "error": None}
        await self.refresh()
        for stage in chosen_stages:
            if not stage:
                continue
            errors = await asyncio.gather(*(self.ensure_ready(item_id) for item_id in stage))
            failed = [error for error in errors if error]
            if failed:
                self.autostart_status = {"state": "failed", "error": "자동 시작 중단: " + " / ".join(failed)}
                return self.autostart_status
        self.autostart_status = {"state": "completed", "error": None}
        return self.autostart_status

    async def dependency_checks(self, refresh=False, ttl=30.0):
        async with self.dependency_lock:
            if refresh or not self.dependencies or time.monotonic() - self.dependencies_at > ttl:
                self.dependencies = await deps.collect(self)
                self.dependencies_at = time.monotonic()
            return self.dependencies

    def cached_dependencies(self, ttl=30.0):
        # Core polls /status with a 2 s timeout; checks take seconds, so never block on them here.
        stale = not self.dependencies or time.monotonic() - self.dependencies_at > ttl
        if stale and not self.dependency_lock.locked():
            self.background(self.dependency_checks(ttl=ttl))
        return self.dependencies

    def item_status(self, item_id) -> dict:
        item = self.items[item_id]
        observed = item.observed
        result = {"id": item.id, "label": item.label, "state": item.state(), "managed": bool(observed.get("managed")),
                  "pid": observed.get("pid"), "started_at": observed.get("started_at"), "ports": item.ports(),
                  "autostart": bool(self.settings.value["autostart"].get(item_id)), "last_error": item.last_error}
        options = item.options()
        if options is not None:
            result["options"] = options
        return result

    def status(self, dependencies) -> dict:
        return {"version": 1, "generated_at": procs.now_iso(), "items": [self.item_status(item_id) for item_id in self.items],
                "dependencies": dependencies}

    def ui_status(self) -> dict:
        items = []
        for item_id, item in self.items.items():
            row = self.item_status(item_id)
            row.update({"busy": self.busy(item_id), "last_result": item.last_result, "active_work": item.active_work,
                        "has_log": bool(item.log_path())})
            if item_id == "services":
                row["pending_options"] = item.current_options()
            items.append(row)
        return {"generated_at": procs.now_iso(), "items": items, "autostart": self.autostart_status,
                "settings": self.settings.public()}


def tail(path, lines=200) -> list[str]:
    try:
        with open(path, "rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 256 * 1024))
            data = stream.read()
    except OSError:
        return []
    return data.decode("utf-8", "replace").splitlines()[-lines:]


__all__ = ["Panel", "ITEM_IDS", "tail"]
