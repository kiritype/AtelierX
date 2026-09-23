"""Managed items: service bundle, ComfyUI, LM Studio server and Cloudflare named tunnel."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import aiohttp

from . import procs
from .config import read_json, write_json


class OperationError(Exception):
    def __init__(self, message, active_work=None):
        super().__init__(message)
        self.message, self.active_work = message, active_work


def comfyui_args(launch_args) -> list[str]:
    """Stability Matrix LaunchArgs -> argv, always forcing loopback-only --listen and port 8188."""
    result = []
    for option in launch_args or []:
        if not isinstance(option, dict):
            continue
        tokens = str(option.get("Name") or "").split()
        if not tokens or tokens[0] in {"--listen", "--port"}:
            continue
        value = option.get("OptionValue")
        if option.get("Type") == "Bool":
            if value is True:
                result += tokens
        elif isinstance(value, bool):
            continue
        elif value is not None and str(value).strip():
            result += tokens + [str(value).strip()]
    return result + ["--listen", "127.0.0.1", "--port", "8188"]


def comfyui_launch(sm_settings: dict, sm_root, root_override=None) -> tuple[list[str], Path]:
    packages = sm_settings.get("InstalledPackages") if isinstance(sm_settings, dict) else None
    entry = next((item for item in packages or [] if isinstance(item, dict) and item.get("PackageName") == "ComfyUI"), None)
    if entry is None:
        raise ValueError("Stability Matrix 설정에 ComfyUI 패키지가 없습니다.")
    root = Path(root_override) if root_override else Path(sm_root) / (entry.get("LibraryPath") or "Packages\\ComfyUI")
    python = root / "venv" / "Scripts" / "python.exe"
    return [str(python), "main.py", *comfyui_args(entry.get("LaunchArgs"))], root


def lms_busy(activity) -> bool:
    """Same idle rule as the GPU coordinator: every loaded model idle with nothing queued."""
    if not isinstance(activity, list):
        return True
    return any(not isinstance(item, dict) or item.get("status") != "idle" or item.get("queued", 0) for item in activity)


def summarize_work(active_work) -> str:
    busy = {key: value for key, value in (active_work or {}).items() if value}
    return ", ".join(f"{key}={value}" for key, value in busy.items()) or "알 수 없음"


class Item:
    id = ""
    label = ""
    ready_timeout = 60.0

    def __init__(self, panel):
        self.panel = panel
        self.paths = panel.paths
        self.op = None
        self.last_error = None
        self.last_result = None
        self.active_work = None
        self.lock = asyncio.Lock()
        self.observed = {"state": "stopped", "managed": False, "pid": None, "started_at": None}

    @property
    def record(self):
        return self.panel.store.get(self.id)

    def save_record(self, record):
        self.panel.store.set(self.id, record)

    @property
    def settings(self):
        return self.panel.settings.value.get(self.id, {})

    def ports(self) -> list[int]:
        return []

    def adopt(self) -> None:
        pass

    def observe(self, ports, table) -> dict:
        return self.observed

    def log_path(self):
        record = self.record or {}
        return record.get("log") or self.panel.last_logs.get(self.id)

    def state(self) -> str:
        state = self.op or self.observed["state"]
        return "error" if state == "stopped" and self.last_error else state

    def options(self):
        return None

    async def is_ready(self) -> bool:
        return self.observed["state"] in {"running", "external"}

    async def still_starting(self) -> bool:
        return True

    async def wait_ready(self, timeout=None) -> None:
        deadline = time.monotonic() + (self.ready_timeout if timeout is None else timeout)
        while True:
            if await self.is_ready():
                return
            if not await self.still_starting():
                raise OperationError(f"{self.label} 프로세스가 준비 전에 종료되었습니다. 로그를 확인하세요.")
            if time.monotonic() >= deadline:
                raise OperationError(f"{self.label} 준비 확인 시간이 초과되었습니다.")
            await asyncio.sleep(self.panel.poll_interval)

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    def new_log(self) -> Path:
        path = self.paths.logs / f"{self.id}-{procs.utc_stamp()}.log"
        self.panel.last_logs[self.id] = str(path)
        return path


class ProcessItem(Item):
    """An item that is one child process started (and recorded) by the panel."""
    main_port = 0

    def __init__(self, panel):
        super().__init__(panel)
        self.process = None

    def ports(self):
        return [self.port()]

    def port(self):
        return self.panel.ports.get(self.id, self.main_port)

    def record_alive(self) -> bool:
        record = self.record
        return bool(record) and procs.process_alive(record.get("pid"), record.get("create_time"))

    def adopt(self) -> None:
        record = self.record
        if not record:
            return
        if not procs.process_alive(record.get("pid"), record.get("create_time")) or not procs.record_matches(record, procs.cim_process(record["pid"])):
            self.panel.last_logs[self.id] = record.get("log")
            self.save_record(None)

    def observe(self, ports, table) -> dict:
        record = self.record
        if record and procs.process_alive(record.get("pid"), record.get("create_time")):
            return {"state": "running", "managed": True, "pid": record["pid"], "started_at": record.get("started_at")}
        if record and self.op is None:
            self.panel.last_logs[self.id] = record.get("log")
            self.save_record(None)
            self.last_error = self.last_error or f"{self.label} 프로세스가 종료되었습니다."
        owner = ports.get(self.port())
        if owner:
            return {"state": "external", "managed": False, "pid": owner, "started_at": None}
        return {"state": "stopped", "managed": False, "pid": None, "started_at": None}

    async def still_starting(self) -> bool:
        return self.record_alive()

    def require_managed(self) -> dict:
        if not self.record_alive():
            raise OperationError(f"제어판이 시작한 {self.label} 프로세스가 아니므로 종료하지 않습니다.")
        return self.record

    async def spawn(self, command, cwd, env=None, check_after=1.0) -> dict:
        log = self.new_log()
        process, record = await asyncio.to_thread(procs.spawn, command, cwd, log, env)
        self.process = process
        self.save_record(record)
        await asyncio.sleep(check_after)
        if process.poll() is not None:
            self.save_record(None)
            raise OperationError(f"{self.label} 프로세스가 바로 종료되었습니다(코드 {process.returncode}). 로그를 확인하세요.")
        return record

    async def wait_exit(self, pid, create_time, timeout) -> bool:
        deadline = time.monotonic() + timeout
        while procs.process_alive(pid, create_time):
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self.panel.poll_interval)
        if self.process is not None and self.process.pid == pid:
            self.process.poll()
            self.process = None
        return True


class ServicesItem(ProcessItem):
    id = "services"
    label = "AtelierX 서비스"
    main_port = 8190
    ready_timeout = 90.0
    stop_response_timeout = 20.0
    exit_timeout = 60.0

    def current_options(self) -> dict:
        return {key: bool(self.settings.get(key)) for key in ("generation", "validation", "discord_bridge")}

    def options(self):
        record = self.record
        if record and self.observed.get("managed") and isinstance(record.get("options"), dict):
            return dict(record["options"])
        return self.current_options()

    def ports(self):
        options = self.options()
        return [8190] + ([8189] if options["generation"] else []) + ([8191] if options["validation"] else []) + ([8192] if options["discord_bridge"] else [])

    def python(self) -> str:
        configured = self.settings.get("python")
        if configured:
            return str(self.paths.resolve(configured))
        venv = self.paths.repo / ".venv" / "Scripts" / "python.exe"
        return str(venv) if venv.is_file() else sys.executable

    def command(self, options) -> list[str]:
        command = [self.python(), "-B", "-m", "atelierx.launcher", "--control-dir", str(self.paths.data)]
        if not options["generation"]:
            command.append("--no-generation")
        if not options["validation"]:
            command.append("--no-validation")
        if options["discord_bridge"]:
            command += ["--standalone-config", str(self.paths.resolve(self.settings["standalone_config"])),
                        "--discord-bridge-config", str(self.paths.resolve(self.settings["discord_bridge_config"]))]
        return command

    async def start(self):
        if self.record_alive():
            return
        if procs.port_open(self.port()):
            raise OperationError(f"{self.port()} 포트가 이미 사용 중입니다(외부 실행). 새로 시작하지 않습니다.")
        options = self.current_options()
        if options["discord_bridge"]:
            for key in ("standalone_config", "discord_bridge_config"):
                if not self.paths.resolve(self.settings[key]).is_file():
                    raise OperationError("Discord Bridge 설정 파일이 없습니다: " + key)
        record = await self.spawn(self.command(options), self.paths.repo, {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
        record["options"] = options
        self.save_record(record)

    async def is_ready(self):
        return await self.panel.http_status(self.panel.urls["core"] + "/health") in {200, 401}

    async def stop(self):
        record = self.require_managed()
        request_id = uuid.uuid4().hex
        await asyncio.to_thread(write_json, self.paths.stop_request, {"request_id": request_id, "at": procs.now_iso()})
        deadline = time.monotonic() + self.stop_response_timeout
        response = None
        while time.monotonic() < deadline:
            body = read_json(self.paths.stop_response)
            if isinstance(body, dict) and body.get("request_id") == request_id:
                response = body
                break
            if not self.record_alive():
                break
            await asyncio.sleep(self.panel.poll_interval)
        if response is None:
            current = read_json(self.paths.stop_request)
            if isinstance(current, dict) and current.get("request_id") == request_id:
                self.paths.stop_request.unlink(missing_ok=True)
            if not self.record_alive():
                self.save_record(None)
                return
            raise OperationError("서비스 실행기가 종료 요청에 응답하지 않았습니다. 서비스는 계속 실행 중입니다.")
        if not response.get("accepted"):
            work = response.get("active_work") if isinstance(response.get("active_work"), dict) else {}
            reason = "활성 작업이 있어 종료를 거절했습니다: " + summarize_work(work) if any(work.values()) else "실행기가 종료를 거절했습니다."
            raise OperationError(reason, work)
        if not await self.wait_exit(record["pid"], record.get("create_time"), self.exit_timeout):
            raise OperationError("종료가 수락되었지만 서비스 프로세스가 아직 종료되지 않았습니다.")
        self.panel.last_logs[self.id] = record.get("log")
        self.save_record(None)


class ComfyUIItem(ProcessItem):
    id = "comfyui"
    label = "ComfyUI"
    main_port = 8188
    ready_timeout = 180.0

    def launch(self):
        sm_path = Path(self.settings.get("stability_matrix_settings") or "C:\\StabilityMatrix\\settings.json")
        try:
            sm_settings = json.loads(sm_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise OperationError("Stability Matrix 설정 파일을 읽을 수 없습니다.") from None
        try:
            command, root = comfyui_launch(sm_settings, sm_path.parent, self.settings.get("root"))
        except ValueError as error:
            raise OperationError(str(error)) from None
        if not Path(command[0]).is_file() or not (root / "main.py").is_file():
            raise OperationError("ComfyUI venv python 또는 main.py를 찾을 수 없습니다.")
        return command, root

    async def start(self):
        if self.record_alive():
            return
        if procs.port_open(self.port()):
            raise OperationError(f"{self.port()} 포트가 이미 사용 중입니다(외부 실행 ComfyUI). 새로 시작하지 않습니다.")
        command, root = self.launch()
        await self.spawn(command, root, {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}, check_after=2.0)

    async def is_ready(self):
        return await self.panel.http_status(self.panel.urls["comfyui"] + "/system_stats") == 200

    async def stop(self):
        record = self.require_managed()
        if procs.port_open(self.port()):
            queue = await self.panel.http_json(self.panel.urls["comfyui"] + "/queue")
            if not isinstance(queue, dict):
                raise OperationError("ComfyUI 큐를 확인할 수 없어 종료하지 않았습니다.")
            if queue.get("queue_running") or queue.get("queue_pending"):
                raise OperationError(f"ComfyUI 큐에 작업이 있어 종료를 거절했습니다: 실행 {len(queue.get('queue_running') or [])}, 대기 {len(queue.get('queue_pending') or [])}")
        if await self.panel.core_gpu_busy():
            raise OperationError("Core GPU 사용 권한 보유·대기 작업이 있어 종료를 거절했습니다.")
        await asyncio.to_thread(procs.kill_tree, record["pid"])
        if not await self.wait_exit(record["pid"], record.get("create_time"), 30):
            raise OperationError("ComfyUI 프로세스가 종료되지 않았습니다.")
        self.panel.last_logs[self.id] = record.get("log")
        self.save_record(None)


class LmStudioItem(Item):
    id = "lmstudio"
    label = "LM Studio 서버"
    ready_timeout = 60.0

    def port(self):
        return self.panel.ports.get(self.id, 1234)

    def ports(self):
        return [self.port()]

    def lms(self):
        configured = self.settings.get("lms")
        candidates = [configured] if configured else []
        candidates += [shutil.which("lms"), str(Path(os.environ.get("USERPROFILE", "~")).expanduser() / ".lmstudio" / "bin" / "lms.exe")]
        return next((str(Path(item)) for item in candidates if item and Path(item).is_file()), None)

    def listening(self):
        return procs.port_open(self.port()) or procs.port_open(self.port(), "::1")

    def observe(self, ports, table):
        owner = ports.get(self.port())
        record = self.record
        if owner:
            managed = bool(record)
            return {"state": "running" if managed else "external", "managed": managed, "pid": owner,
                    "started_at": record.get("started_at") if managed else None}
        if record and self.op is None:
            self.panel.last_logs[self.id] = record.get("log")
            self.save_record(None)
        return {"state": "stopped", "managed": False, "pid": None, "started_at": None}

    async def is_ready(self):
        return await asyncio.to_thread(self.listening)

    async def run_lms(self, *arguments, timeout=120):
        lms = self.lms()
        if lms is None:
            raise OperationError("lms 실행 파일을 찾을 수 없습니다.")
        log = Path(self.log_path() or self.new_log())
        def call():
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("ab") as stream:
                stream.write(f"[control] lms {' '.join(arguments)}\n".encode("utf-8"))
                stream.flush()
                return subprocess.run([lms, *arguments], stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                      timeout=timeout, creationflags=procs.NO_WINDOW).returncode
        try:
            return await asyncio.to_thread(call)
        except subprocess.TimeoutExpired:
            raise OperationError("lms 명령이 시간 안에 끝나지 않았습니다.") from None

    async def start(self):
        if self.record and await self.is_ready():
            return
        if await self.is_ready():
            raise OperationError("LM Studio 서버가 이미 실행 중입니다(외부 실행). 제어판 관리 대상으로 표시하지 않습니다.")
        self.new_log()
        code = await self.run_lms("server", "start")
        if code != 0:
            raise OperationError(f"lms server start가 실패했습니다(코드 {code}). 로그를 확인하세요.")
        self.save_record({"managed": True, "started_at": procs.now_iso(), "log": self.panel.last_logs[self.id]})

    async def stop(self):
        if not self.record:
            raise OperationError("제어판이 시작한 LM Studio 서버가 아니므로 종료하지 않습니다.")
        lms = self.lms()
        if lms is None:
            raise OperationError("lms 실행 파일을 찾을 수 없습니다.")
        try:
            result = await asyncio.to_thread(subprocess.run, [lms, "ps", "--json"], capture_output=True, timeout=20, creationflags=procs.NO_WINDOW)
            activity = json.loads(result.stdout) if result.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            activity = None
        if activity is None:
            raise OperationError("LM Studio 모델 활동을 확인할 수 없어 종료하지 않았습니다.")
        if lms_busy(activity):
            raise OperationError("LM Studio 모델이 처리 중이거나 대기 요청이 있어 종료를 거절했습니다.")
        if await self.panel.core_gpu_busy():
            raise OperationError("Core GPU 사용 권한 보유·대기 작업이 있어 종료를 거절했습니다.")
        code = await self.run_lms("server", "stop", timeout=60)
        if code != 0:
            raise OperationError(f"lms server stop이 실패했습니다(코드 {code}).")
        deadline = time.monotonic() + 30
        while await self.is_ready() and time.monotonic() < deadline:
            await asyncio.sleep(self.panel.poll_interval)
        self.panel.last_logs[self.id] = self.record.get("log")
        self.save_record(None)


class TunnelItem(Item):
    id = "tunnel"
    label = "Cloudflare Tunnel"
    ready_timeout = 15.0

    def __init__(self, panel):
        super().__init__(panel)
        self.identified = {}

    def log_path(self):
        found = super().log_path()
        if found:
            return found
        logs = sorted(self.paths.cloudflare.glob("tunnel-*.stderr.log"), key=lambda path: path.stat().st_mtime) if self.paths.cloudflare.is_dir() else []
        return str(logs[-1]) if logs else None

    def cloudflared(self):
        candidates = [self.settings.get("cloudflared"), os.environ.get("ATELIERX_CLOUDFLARED"), shutil.which("cloudflared"),
                      str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "cloudflared" / "cloudflared.exe")]
        return next((str(Path(item).resolve()) for item in candidates if item and Path(item).is_file()), None)

    def read_pid(self):
        try:
            text = self.paths.tunnel_pid.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
        return int(text) if text.isdigit() and int(text) > 0 else -1

    def matches(self, info) -> bool:
        """Same rule as scripts/*_remote_tunnel.ps1: executable path and --token-file path; the token value is never read."""
        cloudflared = self.cloudflared()
        command_line = (info or {}).get("CommandLine") or ""
        return (cloudflared is not None and procs.same_path(info.get("ExecutablePath"), cloudflared)
                and "--token-file" in command_line and str(self.paths.tunnel_token.resolve()).lower() in command_line.lower())

    def identify(self, pid) -> bool:
        key = (pid, procs.process_create_time(pid))
        if key not in self.identified:
            self.identified = {key: self.matches(procs.cim_process(pid))}
        return self.identified[key]

    def managed_pid(self):
        pid = self.read_pid()
        if pid and pid > 0 and procs.process_alive(pid) and self.identify(pid):
            return pid
        return None

    def observe(self, ports, table):
        pid = self.read_pid()
        if pid and pid > 0 and procs.process_alive(pid):
            if self.identify(pid):
                record = self.record or {}
                return {"state": "running", "managed": True, "pid": pid,
                        "started_at": record.get("started_at") if record.get("pid") == pid else None}
            return {"state": "external", "managed": False, "pid": pid, "started_at": None}
        other = next((candidate for candidate, (_, name) in table.items() if name.lower() == "cloudflared.exe"), None)
        if other:
            return {"state": "external", "managed": False, "pid": other, "started_at": None}
        return {"state": "stopped", "managed": False, "pid": None, "started_at": None}

    async def is_ready(self):
        return await asyncio.to_thread(self.managed_pid) is not None

    async def still_starting(self):
        record = self.record or {}
        return procs.process_alive(record.get("pid"), record.get("create_time"))

    async def start(self):
        cloudflared = self.cloudflared()
        if cloudflared is None:
            raise OperationError("cloudflared 실행 파일을 찾을 수 없습니다.")
        token = self.paths.tunnel_token
        if not token.is_file() or token.stat().st_size == 0:
            raise OperationError("Tunnel token 파일이 없거나 비어 있습니다.")
        pid = self.read_pid()
        if pid == -1:
            raise OperationError("tunnel.pid 파일이 올바르지 않습니다. 확인 후 다시 시도하세요.")
        if pid and procs.process_alive(pid):
            if await asyncio.to_thread(self.identify, pid):
                return
            raise OperationError("tunnel.pid가 다른 프로세스를 가리킵니다. 새 Tunnel을 시작하지 않습니다.")
        if pid:
            self.paths.tunnel_pid.unlink(missing_ok=True)
        running = [row for row in await asyncio.to_thread(procs.cim_processes, "Name='cloudflared.exe'") if self.matches(row)]
        if len(running) > 1:
            raise OperationError("일치하는 Tunnel 프로세스가 둘 이상입니다. 하나를 고를 수 없어 시작하지 않습니다.")
        if running:
            self.paths.tunnel_pid.write_text(str(running[0]["ProcessId"]), encoding="ascii")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.paths.cloudflare.mkdir(parents=True, exist_ok=True)
        stdout = self.paths.cloudflare / f"tunnel-{stamp}.stdout.log"
        stderr = self.paths.cloudflare / f"tunnel-{stamp}.stderr.log"
        process, record = await asyncio.to_thread(
            procs.spawn, [cloudflared, "tunnel", "run", "--token-file", str(token.resolve())], self.paths.repo, stderr, None,
            stdout.open("ab"), stderr.open("ab"))
        await asyncio.sleep(1.0)
        if process.poll() is not None:
            raise OperationError("Tunnel 프로세스가 바로 종료되었습니다. 로그를 확인하세요.")
        self.paths.tunnel_pid.write_text(str(process.pid), encoding="ascii")
        self.save_record(record)
        self.panel.last_logs[self.id] = str(stderr)

    async def stop(self):
        pid = self.read_pid()
        if not pid or pid < 0 or not procs.process_alive(pid):
            raise OperationError("관리 대상 Tunnel(tunnel.pid)이 실행 중이 아닙니다.")
        if not await asyncio.to_thread(self.identify, pid):
            raise OperationError("tunnel.pid 프로세스가 관리 대상 Tunnel과 일치하지 않아 종료하지 않습니다.")
        create_time = procs.process_create_time(pid)
        await asyncio.to_thread(procs.kill_tree, pid)
        deadline = time.monotonic() + 15
        while procs.process_alive(pid, create_time) and time.monotonic() < deadline:
            await asyncio.sleep(self.panel.poll_interval)
        if procs.process_alive(pid, create_time):
            raise OperationError("Tunnel 프로세스가 종료되지 않았습니다.")
        self.paths.tunnel_pid.unlink(missing_ok=True)
        record = self.record or {}
        if record.get("log"):
            self.panel.last_logs[self.id] = record["log"]
        self.save_record(None)
