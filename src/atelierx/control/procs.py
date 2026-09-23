"""Windows process helpers for the control panel (stdlib only: ctypes, netstat, PowerShell CIM)."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WINDOWS = os.name == "nt"
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
NO_WINDOW = CREATE_NO_WINDOW if WINDOWS else 0

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    _kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    _kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    _kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def same_path(left, right) -> bool:
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def _open(pid):
    return _kernel32.OpenProcess(0x1000, False, int(pid)) if WINDOWS else None


def process_create_time(pid):
    if not WINDOWS:
        return None
    handle = _open(pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _kernel32.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        _kernel32.CloseHandle(handle)


def process_alive(pid, create_time=None) -> bool:
    if not pid:
        return False
    if not WINDOWS:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return False
        return True
    handle = _open(pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return False
    finally:
        _kernel32.CloseHandle(handle)
    # PID reuse guard: a recorded process is the same only if its creation time also matches.
    return create_time is None or process_create_time(pid) == create_time


def process_image(pid):
    if not WINDOWS:
        return None
    handle = _open(pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        _kernel32.CloseHandle(handle)


def process_table() -> dict:
    """pid -> (parent pid, executable name) from a Toolhelp snapshot."""
    if not WINDOWS:
        return {}
    snapshot = _kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return {}
    table = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return table


def descends_from(pid, ancestor, table) -> bool:
    seen = set()
    while pid and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = table.get(pid, (0, ""))[0]
    return False


def cim_processes(filter_text: str) -> list[dict]:
    """Win32_Process rows (ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine); [] if unavailable."""
    if not WINDOWS:
        return []
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
              f"@(Get-CimInstance Win32_Process -Filter \"{filter_text}\" -ErrorAction SilentlyContinue | "
              "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = result.stdout.decode("utf-8", "replace").strip()
    if not text:
        return []
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows = rows if isinstance(rows, list) else [rows]
    return [row for row in rows if isinstance(row, dict)]


def cim_process(pid):
    rows = cim_processes(f"ProcessId={int(pid)}")
    return rows[0] if rows else None


def listening_ports() -> dict:
    """port -> owning pid for listening TCP sockets (IPv4 and IPv6), via locale-independent netstat parsing."""
    owners = {}
    for protocol in ("TCP", "TCPv6"):
        try:
            result = subprocess.run(["netstat", "-ano", "-p", protocol], capture_output=True, timeout=15, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) != 5 or not parts[0].upper().startswith("TCP"):
                continue
            local, remote, pid = parts[1], parts[2], parts[4]
            if remote not in {"0.0.0.0:0", "[::]:0"} or not pid.isdigit():
                continue
            try:
                owners.setdefault(int(local.rsplit(":", 1)[1]), int(pid))
            except ValueError:
                continue
    return owners


def port_open(port, host="127.0.0.1", timeout=0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def spawn(command, cwd, log_path=None, env=None, stdout=None, stderr=None) -> tuple:
    """Start a child detached from the panel (own process group, no console window); returns (Popen, record)."""
    command = [str(part) for part in command]
    extra = dict(os.environ)
    extra.update(env or {})
    if stdout is None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        stdout = Path(log_path).open("ab")
        stderr = subprocess.STDOUT
    base = (CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW) if WINDOWS else 0
    try:
        try:
            process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=extra,
                                       creationflags=base | (CREATE_BREAKAWAY_FROM_JOB if WINDOWS else 0), close_fds=True)
        except PermissionError:
            process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=extra,
                                       creationflags=base, close_fds=True)
    finally:
        for stream in (stdout, stderr):
            if hasattr(stream, "close"):
                stream.close()
    exe = command[0] if Path(command[0]).is_absolute() else (shutil.which(command[0]) or command[0])
    record = {"pid": process.pid, "exe": os.path.abspath(exe), "command_line": subprocess.list2cmdline(command),
              "started_at": now_iso(), "log": str(log_path) if log_path else None, "create_time": process_create_time(process.pid)}
    return process, record


def record_matches(record, info) -> bool:
    """A live process is ours only if both executable and full command line equal the recorded ones."""
    if not info:
        return False
    command_line = (info.get("CommandLine") or "").strip()
    return same_path(info.get("ExecutablePath"), record.get("exe")) and command_line == (record.get("command_line") or "").strip()


def kill_tree(pid) -> bool:
    if WINDOWS:
        result = subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=30, creationflags=NO_WINDOW)
        return result.returncode == 0
    os.kill(int(pid), 15)
    return True
