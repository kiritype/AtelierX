"""Control panel paths, settings and persisted process records under `.atelierx/control/`."""
from __future__ import annotations

import copy
import json
import os
import secrets
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ITEM_IDS = ("services", "comfyui", "lmstudio", "tunnel")
SERVICE_OPTIONS = ("generation", "validation", "discord_bridge")

DEFAULT_SETTINGS = {
    "autostart": {item: False for item in ITEM_IDS},
    "services": {"generation": True, "validation": True, "discord_bridge": False,
                 "standalone_config": ".atelierx/discord/standalone.json",
                 "discord_bridge_config": ".atelierx/discord/bridge.json", "python": None},
    "comfyui": {"stability_matrix_settings": "C:\\StabilityMatrix\\settings.json", "root": None},
    "lmstudio": {"lms": None},
    "tunnel": {"cloudflared": None},
}


def _merge(base, override):
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        elif key in result:
            result[key] = value
    return result


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class ControlPaths:
    def __init__(self, repo_root=None, data_dir=None):
        self.repo = Path(repo_root or REPO_ROOT).resolve()
        self.data = Path(data_dir or self.repo / ".atelierx" / "control").resolve()
        self.settings = self.data / "settings.json"
        self.state = self.data / "state.json"
        self.token = self.data / "token.txt"
        self.logs = self.data / "logs"
        self.lock = self.data / "control.lock"
        self.stop_request = self.data / "bundle-stop-request.json"
        self.stop_response = self.data / "bundle-stop-response.json"
        self.private = self.repo / ".atelierx"
        self.pilot_token = self.private / "pilot" / "token.txt"
        self.cloudflare = self.private / "cloudflare"
        self.tunnel_token = self.cloudflare / "tunnel-token.txt"
        self.tunnel_pid = self.cloudflare / "tunnel.pid"
        self.gpu_config = self.private / "gpu-config.json"
        self.validation_config = self.private / "validation-coordinated-config.json"
        self.custom_nodes = self.repo / "custom_nodes"

    def resolve(self, value) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.repo / path

    def ensure(self) -> None:
        self.logs.mkdir(parents=True, exist_ok=True)

    def read_token(self) -> str:
        if not self.token.is_file() or not self.token.read_text(encoding="utf-8").strip():
            self.data.mkdir(parents=True, exist_ok=True)
            self.token.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        return self.token.read_text(encoding="utf-8").strip()


class Settings:
    def __init__(self, paths: ControlPaths):
        self.paths = paths
        self.value = _merge(DEFAULT_SETTINGS, read_json(paths.settings, {}))

    def save(self) -> None:
        write_json(self.paths.settings, self.value)

    def public(self) -> dict:
        return {"autostart": dict(self.value["autostart"]),
                "services": {key: self.value["services"][key] for key in SERVICE_OPTIONS}}

    def update(self, body) -> dict:
        """Only boolean autostart flags and service start options are writable through the API."""
        if not isinstance(body, dict) or set(body) - {"autostart", "services"}:
            raise ValueError("autostart 또는 services만 변경할 수 있습니다.")
        autostart, services = body.get("autostart", {}), body.get("services", {})
        if not isinstance(autostart, dict) or not isinstance(services, dict):
            raise ValueError("설정 형식이 올바르지 않습니다.")
        for key, value in autostart.items():
            if key not in ITEM_IDS or not isinstance(value, bool):
                raise ValueError("autostart 값은 항목별 true/false여야 합니다.")
        for key, value in services.items():
            if key not in SERVICE_OPTIONS or not isinstance(value, bool):
                raise ValueError("서비스 옵션은 generation/validation/discord_bridge의 true/false여야 합니다.")
        self.value["autostart"].update(autostart)
        self.value["services"].update(services)
        self.save()
        return self.public()


class StateStore:
    """Per-item process records; re-adopted on panel start only when the live process still matches."""
    def __init__(self, paths: ControlPaths):
        self.paths = paths
        data = read_json(paths.state, {})
        items = data.get("items") if isinstance(data, dict) else None
        self.items = {key: value for key, value in (items or {}).items() if key in ITEM_IDS and isinstance(value, dict)}

    def get(self, item):
        return self.items.get(item)

    def set(self, item, record) -> None:
        if record is None:
            self.items.pop(item, None)
        else:
            self.items[item] = record
        write_json(self.paths.state, {"version": 1, "items": self.items})
