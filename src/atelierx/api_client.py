"""Small asynchronous Core REST adapter for the CLI and internal tools.

This is an initial Python slice, not a browser SDK or an orchestration layer.
"""
from __future__ import annotations

import asyncio
import math
import re
from urllib.parse import urlsplit

import aiohttp

from .common import ApiError


class CoreClient:
    """Authenticated, no-retry client for Core's initial read-only browse API."""

    def __init__(self, base_url, token, timeout=30):
        if not isinstance(base_url, str):
            raise ValueError("base_url must be a string")
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("base_url must be an origin without credentials, query, or path")
        if not isinstance(token, str) or not token or any(ord(char) < 32 or ord(char) == 127 for char in token):
            raise ValueError("token is required")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self._session = None

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.close()

    async def open(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=self.base_url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"Authorization": "Bearer " + self._token, "Accept": "application/json"},
            )
        return self

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()

    @staticmethod
    def _path(path):
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ApiError("CLIENT_INVALID_PATH", "Request path must be local and absolute", 400)
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in path:
            raise ApiError("CLIENT_INVALID_PATH", "Request path must be local and absolute", 400)
        if any(part in {"", ".", ".."} for part in parsed.path.split("/")[1:]):
            raise ApiError("CLIENT_INVALID_PATH", "Request path must be local and absolute", 400)
        return path

    @staticmethod
    def _segment(value, label):
        if (not isinstance(value, str) or not value or "/" in value or "\\" in value or "?" in value or "#" in value
                or "%" in value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ApiError("CLIENT_INVALID_PATH", label + " must be a single path segment", 400)
        return value

    async def request(self, method, path, *, params=None, json=None, idempotency_key=None):
        """Perform exactly one JSON request and preserve service error code/status.

        Redirects are refused so the bearer token can never be forwarded to a
        different URL.  Server-provided error messages are not copied into the
        exception because an untrusted service could reflect credentials.
        """
        if not isinstance(method, str) or not method.isalpha():
            raise ApiError("CLIENT_INVALID_METHOD", "HTTP method is invalid", 400)
        path = self._path(path)
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200
                                            or any(ord(char) < 32 or ord(char) == 127 for char in idempotency_key)):
            raise ApiError("CLIENT_INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 1..200 characters", 400)
        if self._session is None or self._session.closed:
            raise ApiError("CLIENT_SESSION_CLOSED", "Open the client with async with before requesting", 400)
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key is not None else None
        try:
            async with self._session.request(method.upper(), path, params=params, json=json, headers=headers,
                                             allow_redirects=False) as response:
                if 300 <= response.status < 400:
                    raise ApiError("CLIENT_REDIRECT_BLOCKED", "Redirected service responses are blocked", response.status)
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError, UnicodeDecodeError) as exc:
                    raise ApiError("CLIENT_PROTOCOL_ERROR", "Service returned invalid JSON", 502) from exc
                if not isinstance(payload, dict):
                    raise ApiError("CLIENT_PROTOCOL_ERROR", "Service returned an invalid JSON payload", 502)
                if response.status < 200 or response.status >= 300:
                    error = payload.get("error")
                    code = error.get("code") if isinstance(error, dict) else None
                    safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code) and self._token not in code else "CLIENT_HTTP_ERROR"
                    raise ApiError(safe_code,
                                   "Service request failed", response.status)
                return payload
        except asyncio.TimeoutError as exc:
            raise ApiError("CLIENT_TIMEOUT", "Service request timed out", 504) from exc
        except aiohttp.ClientError as exc:
            raise ApiError("CLIENT_TRANSPORT_ERROR", "Service transport failed", 503) from exc

    async def health(self):
        return await self.request("GET", "/health")

    async def queue(self, **filters):
        return await self.request("GET", "/v1/queue", params=filters or None)

    async def get_settings(self):
        return await self.request("GET", "/v1/settings")

    async def update_settings(self, body):
        return await self.request("PATCH", "/v1/settings", json=body)

    async def list_groups(self, **filters):
        return await self.request("GET", "/v1/groups", params=filters or None)

    async def get_group(self, group_id):
        return await self.request("GET", "/v1/groups/" + self._segment(group_id, "group_id"))

    async def list_images(self, **filters):
        return await self.request("GET", "/v1/images", params=filters or None)

    async def get_image(self, image_id):
        return await self.request("GET", "/v1/images/" + self._segment(image_id, "image_id"))

    async def list_tasks(self, **filters):
        return await self.request("GET", "/v1/tasks", params=filters or None)

    async def get_task(self, task_id):
        return await self.request("GET", "/v1/tasks/" + self._segment(task_id, "task_id"))

    async def list_group_batches(self, **filters):
        return await self.request("GET", "/v1/group-batches", params=filters or None)

    async def get_group_batch(self, batch_id):
        return await self.request("GET", "/v1/group-batches/" + self._segment(batch_id, "batch_id"))

    async def list_group_batches_for_group(self, group_id):
        return await self.request("GET", "/v1/groups/" + self._segment(group_id, "group_id") + "/batches")

    async def create_group_batch(self, group_id, body, idempotency_key):
        return await self.request("POST", "/v1/groups/" + self._segment(group_id, "group_id") + "/batches",
                                  json=body, idempotency_key=idempotency_key)

    async def cancel_group_batch(self, batch_id):
        return await self.request("POST", "/v1/group-batches/" + self._segment(batch_id, "batch_id") + "/cancel")

    async def confirm_group_batch_reference(self, batch_id, body, idempotency_key):
        return await self.request("POST", "/v1/group-batches/" + self._segment(batch_id, "batch_id") + "/confirm-reference",
                                  json=body, idempotency_key=idempotency_key)

    async def preview_prompt(self, body):
        return await self.request("POST", "/v1/prompts/preview", json=body)

    async def create_task(self, body, idempotency_key):
        return await self.request("POST", "/v1/tasks", json=body, idempotency_key=idempotency_key)

    async def get_task_by_key(self, idempotency_key):
        return await self.request("GET", "/v1/tasks/by-key", idempotency_key=idempotency_key)

    async def validate_image(self, image_id, body, idempotency_key):
        return await self.request("POST", "/v1/images/" + self._segment(image_id, "image_id") + "/validations",
                                  json=body, idempotency_key=idempotency_key)

    async def regenerate_task(self, task_id, body, idempotency_key):
        return await self.request("POST", "/v1/tasks/" + self._segment(task_id, "task_id") + "/regenerations",
                                  json=body, idempotency_key=idempotency_key)

    async def cancel_task(self, task_id):
        return await self.request("POST", "/v1/tasks/" + self._segment(task_id, "task_id") + "/cancel")

    async def cancel_validation(self, run_id):
        return await self.request("POST", "/v1/validation-runs/" + self._segment(run_id, "run_id") + "/cancel")

    async def get_validation_run(self, run_id):
        return await self.request("GET", "/v1/validation-runs/" + self._segment(run_id, "run_id"))

    async def list_task_attempts(self, task_id, **filters):
        return await self.request("GET", "/v1/tasks/" + self._segment(task_id, "task_id") + "/attempts", params=filters or None)

    async def get_cycle(self, cycle_id):
        return await self.request("GET", "/v1/regeneration-cycles/" + self._segment(cycle_id, "cycle_id"))

    async def stop_cycle(self, cycle_id):
        return await self.request("POST", "/v1/regeneration-cycles/" + self._segment(cycle_id, "cycle_id") + "/stop")
