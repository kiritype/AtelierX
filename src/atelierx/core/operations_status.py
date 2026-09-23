"""Read-only operations status relayed from the local control panel."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp


ITEM_IDS = ("services", "comfyui", "lmstudio", "tunnel")
ITEM_STATES = ("running", "external", "stopped", "starting", "stopping", "error")
DEPENDENCY_STATUSES = ("ok", "warning", "missing", "unknown")
SERVICE_OPTIONS = ("generation", "validation", "discord_bridge")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_TEXT = 300
_MAX_ID = 64
_MAX_ITEMS = 32
_MAX_DEPENDENCIES = 64
_MAX_PORTS = 16
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_TOKEN_BYTES = 4096
_TIMEOUT_SECONDS = 2


def loopback_url(value):
    if not isinstance(value, str) or any(ord(char) < 33 for char in value):
        return None
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS or parsed.username or parsed.password or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        return None
    return value.rstrip("/")


def _text(value, limit=_MAX_TEXT):
    if not isinstance(value, str):
        return None
    cleaned = "".join(char for char in value if char >= " " or char == "\n")
    return cleaned[:limit]


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 31 else None


def _item(raw):
    if not isinstance(raw, dict) or raw.get("id") not in ITEM_IDS or raw.get("state") not in ITEM_STATES:
        return None
    ports = raw.get("ports")
    item = {"id": raw["id"], "label": _text(raw.get("label"), 100) or raw["id"], "state": raw["state"],
            "managed": raw.get("managed") if isinstance(raw.get("managed"), bool) else False,
            "pid": _int(raw.get("pid")), "started_at": _text(raw.get("started_at"), 64),
            "ports": [port for port in ports if _int(port) is not None and 0 < port < 65536][:_MAX_PORTS] if isinstance(ports, list) else [],
            "autostart": raw.get("autostart") if isinstance(raw.get("autostart"), bool) else False,
            "last_error": _text(raw.get("last_error"))}
    if raw["id"] == "services":
        options = raw.get("options")
        item["options"] = {key: options[key] for key in SERVICE_OPTIONS
                           if isinstance(options, dict) and isinstance(options.get(key), bool)}
    return item


def _dependency(raw):
    if not isinstance(raw, dict) or raw.get("status") not in DEPENDENCY_STATUSES:
        return None
    ident = _text(raw.get("id"), _MAX_ID)
    if not ident:
        return None
    return {"id": ident, "label": _text(raw.get("label"), 100) or ident, "status": raw["status"],
            "detail": _text(raw.get("detail"))}


def sanitize(payload):
    if (not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("items"), list) or
            not isinstance(payload.get("dependencies"), list)):
        return None
    items, seen = [], set()
    for raw in payload["items"][:_MAX_ITEMS]:
        item = _item(raw)
        if item and item["id"] not in seen:
            seen.add(item["id"]); items.append(item)
    dependencies = [dependency for dependency in map(_dependency, payload["dependencies"][:_MAX_DEPENDENCIES]) if dependency]
    return {"control_panel": "available", "generated_at": _text(payload.get("generated_at"), 64),
            "items": items, "dependencies": dependencies}


def unavailable(reason):
    return {"control_panel": "unavailable", "reason": reason, "items": [], "dependencies": []}


class OperationsStatus:
    def __init__(self, config):
        config = config if isinstance(config, dict) else {}
        self.url = loopback_url(config.get("url"))
        token_file = config.get("token_file")
        self.token_file = Path(token_file) if isinstance(token_file, (str, Path)) and str(token_file) else None

    def _token(self):
        try:
            data = self.token_file.read_bytes()[:_MAX_TOKEN_BYTES + 1]
        except OSError:
            return None
        if len(data) > _MAX_TOKEN_BYTES:
            return None
        try:
            token = data.decode("utf-8-sig").strip()
        except UnicodeDecodeError:
            return None
        if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
            return None
        return token

    async def fetch(self, session):
        if self.url is None or self.token_file is None:
            return unavailable("not_configured")
        token = self._token()
        if token is None:
            return unavailable("token_missing")
        try:
            timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)
            async with session.get(self.url + "/status", allow_redirects=False, timeout=timeout,
                                   headers={"Authorization": "Bearer " + token, "Accept": "application/json"}) as response:
                if response.status in (401, 403):
                    return unavailable("unauthorized")
                if response.status != 200:
                    return unavailable("invalid_response")
                data = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > _MAX_RESPONSE_BYTES:
                        return unavailable("invalid_response")
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return unavailable("unreachable")
        try:
            result = sanitize(json.loads(bytes(data).decode("utf-8")))
        except (UnicodeDecodeError, ValueError, RecursionError):
            result = None
        return result or unavailable("invalid_response")
