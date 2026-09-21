"""Personal Discord delivery adapter. Core owns inference and generation state.

Only this narrow HTTP surface is intended for an authenticated tunnel. Delivery
records are local files; no SQL or Generation access is granted to this adapter.
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

from .common import ApiError, ProcessLock, canonical

BRIDGE = web.AppKey("discord_bridge", object)
DISCORD_API = "https://discord.com/api/v10"
TERMINAL = {"completed", "failed", "cancelled"}


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]{1,22}", value) is not None


def segment(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ApiError("BRIDGE_PROTOCOL_ERROR", "Invalid service identifier", 502)
    return value


class Bridge:
    def __init__(self, directory, config, *, discord_api=DISCORD_API):
        self.config = config
        self.token = os.environ.get(config["bridge_token_env"], "")
        self.core_token = os.environ.get(config["core_token_env"], "")
        if not self.token or not self.core_token:
            raise ValueError("Bridge and Core token environment variables are required")
        self.access_mode = config.get("access_mode", "users")
        self.allowed_users = config.get("allowed_user_ids", [config.get("allowed_user_id")])
        self.allowed_guilds = config.get("allowed_guild_ids")
        self.allowed_channels = config.get("allowed_channel_ids")
        if not identifier(config.get("application_id")) or self.access_mode not in {"users", "guild"}:
            raise ValueError("Discord application_id and access_mode are required")
        if self.access_mode == "users":
            if (not isinstance(self.allowed_users, list) or not self.allowed_users
                    or any(not identifier(user) for user in self.allowed_users)):
                raise ValueError("nonempty allowed_user_ids are required for users access")
        elif (not isinstance(self.allowed_guilds, list) or not self.allowed_guilds
              or any(not identifier(guild) for guild in self.allowed_guilds)
              or (self.allowed_channels is not None and (not isinstance(self.allowed_channels, list)
                  or not self.allowed_channels or any(not identifier(channel) for channel in self.allowed_channels)))):
            raise ValueError("valid allowed_guild_ids and optional allowed_channel_ids are required for guild access")
        parsed = urlsplit(config["core_url"])
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("core_url must be a service origin")
        self.core_url = config["core_url"].rstrip("/")
        self.discord_api = discord_api.rstrip("/")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.owner = ProcessLock(self.directory / "bridge.lock")
        self.records = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in self.directory.glob("*.json")}
        self.session = None

    def save(self, record):
        path = self.directory / (record["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(canonical(record)); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
        self.records[record["id"]] = record

    def accept(self, body, status=False):
        common = {"interaction_id", "application_id", "interaction_token", "user_id", "attachment_size_limit", "received_at"}
        if self.access_mode == "guild":
            common |= {"guild_id", "channel_id"}
        draw_required = common | {"prompt"}
        draw_optional = {"mode", "negative_prompt"}
        expected = common | {"request_id"} if status else draw_required
        if (not isinstance(body, dict) or (set(body) != expected if status else
                                          (not draw_required.issubset(body) or set(body) - (draw_required | draw_optional)))):
            raise ApiError("BRIDGE_INVALID_INPUT", "Unexpected request fields")
        if any(not identifier(body[k]) for k in ("interaction_id", "application_id", "user_id")):
            raise ApiError("BRIDGE_INVALID_INPUT", "Invalid Discord identifier")
        if body["application_id"] != self.config["application_id"]:
            raise ApiError("BRIDGE_FORBIDDEN", "Discord identity is not allowed", 403)
        if self.access_mode == "users":
            if body["user_id"] not in self.allowed_users:
                raise ApiError("BRIDGE_FORBIDDEN", "Discord identity is not allowed", 403)
        elif (not identifier(body["guild_id"]) or not identifier(body["channel_id"])
              or body["guild_id"] not in self.allowed_guilds
              or (self.allowed_channels is not None and body["channel_id"] not in self.allowed_channels)):
            raise ApiError("BRIDGE_FORBIDDEN", "Discord guild or channel is not allowed", 403)
        if (not isinstance(body["interaction_token"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,2048}", body["interaction_token"])):
            raise ApiError("BRIDGE_INVALID_INPUT", "Invalid response token")
        if type(body["received_at"]) not in (int, float) or not time.time() - 300 <= body["received_at"] <= time.time() + 30:
            raise ApiError("BRIDGE_INVALID_INPUT", "Stale request")
        if type(body["attachment_size_limit"]) is not int or body["attachment_size_limit"] <= 0:
            raise ApiError("BRIDGE_INVALID_INPUT", "Invalid attachment limit")
        if status:
            original = self.records.get(body.get("request_id")) if identifier(body.get("request_id")) else None
            if not original or original["kind"] != "draw" or original["user_id"] != body["user_id"]:
                raise ApiError("BRIDGE_NOT_FOUND", "Request not found", 404)
        else:
            mode = body.get("mode", "direct")
            if not isinstance(mode, str):
                raise ApiError("BRIDGE_INVALID_INPUT", "Mode must be natural or direct")
            mode = mode.strip().lower()
            if (mode not in ("natural", "direct") or not isinstance(body["prompt"], str)
                    or not body["prompt"].strip() or len(body["prompt"]) > 4000
                    or ("negative_prompt" in body and (not isinstance(body["negative_prompt"], str)
                                                        or len(body["negative_prompt"]) > 4000))):
                raise ApiError("BRIDGE_INVALID_INPUT", "A prompt, supported mode, and optional negative_prompt are required")
            # Match Core's canonical request shape.  This also retains the
            # historical hash for lowercase direct requests without a Negative.
            body = {**body, "mode": mode}
        fingerprint = hashlib.sha256(canonical({k: v for k, v in body.items()
                                               if k not in {"received_at", "interaction_token", "attachment_size_limit"}}).encode()).hexdigest()
        existing = self.records.get(body["interaction_id"])
        if existing:
            if existing["fingerprint"] != fingerprint or existing["kind"] != ("status" if status else "draw"):
                raise ApiError("BRIDGE_IDEMPOTENCY_CONFLICT", "Interaction content changed", 409)
            return self.public(existing), False
        record = dict(id=body["interaction_id"], kind="status" if status else "draw",
                      fingerprint=fingerprint, user_id=body["user_id"], created_at=body["received_at"],
                      token=body["interaction_token"], attachment_limit=min(body["attachment_size_limit"], 20 * 1024 * 1024),
                      state="queued", delivery="pending", delivery_attempts=0, next_delivery_at=0)
        if self.access_mode == "guild":
            record.update(guild_id=body["guild_id"], channel_id=body["channel_id"])
        if status:
            record["request_id"] = body["request_id"]
        else:
            record.update(prompt=body["prompt"], mode=body["mode"], core_id=None, images=[], error=None)
            if "negative_prompt" in body:
                record["negative_prompt"] = body["negative_prompt"]
        self.save(record)
        return self.public(record), True

    @staticmethod
    def public(record):
        return {"interaction_id": record["id"], "state": record["state"], "delivery": record["delivery"]}

    async def core(self, method, path, *, payload=None, key=None):
        headers = {"Authorization": "Bearer " + self.core_token}
        if key:
            headers["Idempotency-Key"] = key
        async with self.session.request(method, self.core_url + path, headers=headers, json=payload,
                                        allow_redirects=False) as response:
            if response.status == 404:
                return None
            if response.status not in (200, 202):
                raise ApiError("BRIDGE_CORE_UNAVAILABLE" if response.status >= 500 else "BRIDGE_CORE_REJECTED",
                               "Core request failed", response.status)
            result = await response.json()
            if not isinstance(result, dict):
                raise ApiError("BRIDGE_PROTOCOL_ERROR", "Invalid Core response", 502)
            return result

    async def advance(self, record):
        if record["state"] in TERMINAL:
            return
        key = "discord:" + record["id"]
        if record["state"] == "queued":
            # Never begin a new generation for a request that sat offline past expiry.
            if time.time() - record["created_at"] >= 14 * 60:
                record.update(state="failed", error="BRIDGE_REQUEST_EXPIRED")
                self.save(record); return
            record["state"] = "dispatching"
            self.save(record)
            payload = {"prompt": record["prompt"], "mode": record["mode"]}
            if "negative_prompt" in record:
                payload["negative_prompt"] = record["negative_prompt"]
            result = await self.core("POST", "/v1/standalone-jobs", key=key, payload=payload)
        elif not record.get("core_id"):
            result = await self.core("GET", "/v1/standalone-jobs/by-key", key=key)
            if result is None:
                record.update(state="failed", error="BRIDGE_ACCEPTANCE_UNKNOWN")
                self.save(record); return
        else:
            result = await self.core("GET", "/v1/standalone-jobs/" + segment(record["core_id"]))
        if result is None:
            raise ApiError("BRIDGE_PROTOCOL_ERROR", "Core job missing", 502)
        record["core_id"] = segment(result.get("id"))
        state = result.get("state")
        if state not in {"queued", "planning", "planner_completed", "ready_to_dispatch", "dispatching", "generation_pending", "running", "completed", "failed", "cancelled"}:
            raise ApiError("BRIDGE_PROTOCOL_ERROR", "Unknown Core state", 502)
        error = result.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{1,100}", code):
            code = "CORE_JOB_FAILED"
        images = result.get("images", [])
        if not isinstance(images, list) or any(not isinstance(item, dict) for item in images):
            raise ApiError("BRIDGE_PROTOCOL_ERROR", "Invalid image descriptors", 502)
        seed = result.get("seed")
        seed_fields = {"seed": seed} if type(seed) is int else {}
        record.update(state=state if state in TERMINAL else "core_pending", images=images,
                      error=code if state == "failed" else None)
        record.update(seed_fields)
        self.save(record)

    async def notify_received(self, record):
        if (record["state"] in TERMINAL or record.get("progress_sent") or not record.get("token")
                or record.get("progress_attempts", 0) >= 3
                or time.time() < max(record.get("progress_next_at", 0), record["next_delivery_at"])):
            return
        if time.time() - record["created_at"] >= 14 * 60:
            return
        url = f"{self.discord_api}/webhooks/{self.config['application_id']}/{record['token']}/messages/@original"
        payload = {"content": f"접수했습니다. 요청 ID: {record['id']}\n생성 대기·실행 중입니다. 오래 걸리면 /status request_id:{record['id']} 로 확인하세요.",
                   "allowed_mentions": {"parse": []}}
        record["progress_attempts"] = record.get("progress_attempts", 0) + 1
        record["progress_next_at"] = time.time() + 10
        self.save(record)
        try:
            async with self.session.patch(url, json=payload, allow_redirects=False) as response:
                record["progress_sent"] = response.status == 200
                if response.status == 429:
                    try:
                        delay = float(response.headers.get("Retry-After", "30"))
                    except ValueError:
                        delay = 30
                    record["next_delivery_at"] = time.time() + max(1, min(delay, 3600))
                self.save(record)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

    async def image(self, original, limit):
        candidates = sorted(original.get("images", []), key=lambda item: item.get("media_type") != "image/png")
        for descriptor in candidates:
            if descriptor.get("media_type") not in {"image/png", "image/webp"} or type(descriptor.get("bytes")) is not int:
                continue
            if not 0 < descriptor["bytes"] <= limit:
                continue
            image_id = segment(descriptor.get("image_id"))
            path = f"/v1/standalone-jobs/{segment(original['core_id'])}/images/{image_id}/content"
            async with self.session.get(self.core_url + path, headers={"Authorization": "Bearer " + self.core_token},
                                        allow_redirects=False) as response:
                if response.status != 200:
                    raise ApiError("BRIDGE_IMAGE_UNAVAILABLE", "Image download failed", 502)
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ApiError("BRIDGE_ATTACHMENT_TOO_LARGE", "Image exceeds attachment limit")
                if len(data) != descriptor["bytes"]:
                    raise ApiError("BRIDGE_PROTOCOL_ERROR", "Image size mismatch", 502)
                if descriptor.get("sha256") and hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
                    raise ApiError("BRIDGE_PROTOCOL_ERROR", "Image hash mismatch", 502)
                return bytes(data), descriptor["media_type"]
        return None

    async def deliver(self, record):
        if record["delivery"] != "pending":
            return
        if time.time() - record["created_at"] >= 14 * 60:
            record.update(delivery="expired", token=None)
            self.save(record); return
        if time.time() < record["next_delivery_at"]:
            return
        original = self.records[record["request_id"]] if record["kind"] == "status" else record
        if record["kind"] == "draw" and original["state"] not in TERMINAL:
            return
        content = f"요청 {original['id']} · {original['state']}"
        if original.get("core_id"):
            content += f" · Core {original['core_id']}"
        if type(original.get("seed")) is int:
            content += f"\nSeed: {original['seed']}"
        attachment = None
        if original["state"] == "completed":
            content += "\n생성 완료 · 품질 검증은 요청하지 않았습니다."
            attachment = await self.image(original, record["attachment_limit"])
            if attachment is None:
                content += "\n첨부 크기 제한으로 전달하지 못했습니다. 결과는 로컬에 보존되어 있습니다."
        elif original["state"] not in TERMINAL:
            content += f"\n진행 중입니다. /status request_id:{original['id']} 로 다시 확인할 수 있습니다."
        elif original.get("error"):
            content += "\n" + original["error"]
        payload = {"content": content, "allowed_mentions": {"parse": []}, "attachments": []}
        kwargs = {"json": payload}
        if attachment:
            data, media = attachment
            filename = "SPOILER_atelierx." + ("png" if media == "image/png" else "webp")
            payload["attachments"] = [{"id": 0, "filename": filename}]
            form = aiohttp.FormData()
            form.add_field("payload_json", json.dumps(payload))
            form.add_field("files[0]", data, filename=filename, content_type=media)
            kwargs = {"data": form}
        url = f"{self.discord_api}/webhooks/{self.config['application_id']}/{record['token']}/messages/@original"
        async with self.session.patch(url, allow_redirects=False, **kwargs) as response:
            if response.status == 200:
                record.update(delivery="delivered", token=None)
                if record["kind"] == "status":
                    record["state"] = "completed"
                self.save(record)
            elif response.status in (401, 404):
                record.update(delivery="expired", token=None); self.save(record)
            elif response.status == 429:
                delay = float(response.headers.get("Retry-After", "30"))
                record["next_delivery_at"] = time.time() + max(1, min(delay, 3600))
                self.save(record)
            else:
                raise ApiError("BRIDGE_DELIVERY_FAILED", "Discord delivery failed", response.status)

    async def tick(self):
        for record in list(self.records.values()):
            if record["kind"] == "draw" and record["state"] not in TERMINAL:
                try:
                    await self.notify_received(record)
                    await self.advance(record)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass  # Query the persisted intent next tick, never repeat POST.
                except ApiError as exc:
                    if exc.code != "BRIDGE_CORE_UNAVAILABLE":
                        record.update(state="failed", error=exc.code); self.save(record)
                except (ValueError, TypeError, KeyError):
                    record.update(state="failed", error="BRIDGE_PROTOCOL_ERROR"); self.save(record)
            try:
                await self.deliver(record)
            except (aiohttp.ClientError, asyncio.TimeoutError, ApiError, ValueError, KeyError, TypeError):
                record["delivery_attempts"] += 1
                record["next_delivery_at"] = time.time() + 30 * record["delivery_attempts"]
                if record["delivery_attempts"] >= 3:
                    record.update(delivery="failed", token=None)
                self.save(record)


def create_app(directory, config, *, discord_api=DISCORD_API, poll=2):
    bridge = Bridge(directory, config, discord_api=discord_api)

    @web.middleware
    async def authentication(request, handler):
        if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + bridge.token).encode()):
            return web.json_response({"error": {"code": "BRIDGE_UNAUTHORIZED"}}, status=401)
        try:
            return await handler(request)
        except ApiError as exc:
            return web.json_response({"error": {"code": exc.code}}, status=exc.status)
        except (ValueError, TypeError):
            return web.json_response({"error": {"code": "BRIDGE_INVALID_INPUT"}}, status=400)

    app = web.Application(middlewares=[authentication], client_max_size=64 * 1024)
    app[BRIDGE] = bridge

    async def accept(request):
        result, created = bridge.accept(await request.json(), request.path.endswith("/status"))
        return web.json_response(result, status=202 if created else 200)

    async def health(request):
        return web.json_response({"service": "discord-bridge", "status": "ok"})

    async def lifecycle(app):
        async def worker():
            while True:
                await bridge.tick()
                await asyncio.sleep(poll)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                bridge.session = session
                task = asyncio.create_task(worker())
                try:
                    yield
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        finally:
            bridge.owner.close()

    app.cleanup_ctx.append(lifecycle)
    app.add_routes([web.get("/health", health), web.post("/v1/discord/jobs", accept), web.post("/v1/discord/status", accept)])
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", default=".atelierx/discord-bridge")
    parser.add_argument("--port", type=int, default=8192)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    web.run_app(create_app(args.data_dir, config), host="127.0.0.1", port=args.port, access_log=None)


if __name__ == "__main__":
    main()
