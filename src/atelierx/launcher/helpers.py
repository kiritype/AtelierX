"""Small, dependency-free helpers for the pilot service launcher."""
from __future__ import annotations

import json
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


LOCAL_PORTS = (8190, 8189, 8191)
_SECRET = re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|bearer\s+|[\"']?(?:token|api[_-]?key|password)[\"']?\s*[:=]\s*[\"']?)[^\s,}\]\"']+")
_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]+")
_PROMPT = re.compile(r"(?i)\b(?:positive_prompt|negative_prompt|prompt)\b")


def redact_log(value: object) -> str:
    """Remove values that must never reach a terminal or pilot log file."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    if _PROMPT.search(text):
        return "[redacted prompt-bearing log message]"
    text = _URL_QUERY.sub(r"\1?[redacted]", text)
    return _SECRET.sub(r"\1[redacted]", text)


def unavailable_ports(ports=LOCAL_PORTS, host="127.0.0.1") -> list[int]:
    """Check every required port before the pilot constructs any service resource."""
    unavailable = []
    probes = []
    try:
        for port in ports:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                probe.bind((host, port))
            except OSError:
                unavailable.append(port)
                probe.close()
            else:
                probes.append(probe)
    finally:
        for probe in probes:
            probe.close()
    return unavailable


class PilotLog:
    def __init__(self, data_dir: Path):
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        self.path = log_dir / f"frontend-pilot-{stamp}.log"
        self._file = self.path.open("a", encoding="utf-8")

    def write(self, service: str, message: object) -> None:
        line = f"[{service}] {redact_log(message)}"
        print(line, flush=True)
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def _service_url(value, key):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an http(s) URL or null")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError(f"{key} must be an http(s) service origin without credentials, query, or fragment")
    return value.rstrip("/")


def load_remote_config(path: str | Path) -> dict:
    """Read a private local launcher config without reading any token value."""
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"launcher config cannot be read: {error}") from error
    if data.get("mode") == "remote-ui":
        if not isinstance(data.get("ui_url"), str) or set(data) != {"mode", "ui_url"}:
            raise ValueError("remote UI launcher config contains only mode and ui_url")
        parsed = urlparse(data["ui_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("ui_url must be an http(s) URL without credentials, query, or fragment")
        return {"mode": "remote-ui", "ui_url": data["ui_url"]}
    allowed = {"mode", "generation_url", "generation_token_env", "validation_url", "validation_token_env"}
    if data.get("mode") != "local" or set(data) - allowed:
        raise ValueError("launcher config requires mode 'local' with optional Generation and Validation service fields")
    result = {"mode": "local", "generation_url": _service_url(data.get("generation_url"), "generation_url"),
              "validation_url": _service_url(data.get("validation_url"), "validation_url")}
    for service in ("generation", "validation"):
        key, url = service + "_token_env", result[service + "_url"]
        value = data.get(key)
        if url is None and value is not None:
            raise ValueError(f"{key} requires {service}_url")
        if url is not None and (not isinstance(value, str) or not value):
            raise ValueError(f"{key} is required when {service}_url is configured")
        result[key] = value
    return result


def startup_status(runtime_info=None) -> str:
    runtime_info = runtime_info or {}
    version = runtime_info.get("version", "source checkout")
    build = runtime_info.get("build", "unavailable")
    return f"AtelierX {version} · build {build} · Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
