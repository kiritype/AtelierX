import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.core import create_app
from atelierx.core.operations_status import OperationsStatus, loopback_url, sanitize


PANEL_TOKEN = "panel-status-token"
CORE_AUTH = {"Authorization": "Bearer core-token"}


def valid_status():
    return {"version": 1, "generated_at": "2026-09-23T10:00:00+09:00",
            "items": [{"id": "services", "label": "서비스 묶음", "state": "running", "managed": True, "pid": 123,
                       "started_at": "2026-09-23T09:00:00+09:00", "ports": [8190, 8189], "autostart": True, "last_error": None,
                       "options": {"generation": True, "validation": False, "discord_bridge": False}},
                      {"id": "comfyui", "label": "ComfyUI", "state": "external", "managed": False, "pid": None,
                       "started_at": None, "ports": [8188], "autostart": False, "last_error": None},
                      {"id": "tunnel", "label": "Tunnel", "state": "error", "managed": True, "pid": None, "started_at": None,
                       "ports": [], "autostart": False, "last_error": "cloudflared 실행 파일이 없습니다."}],
            "dependencies": [{"id": "comfyui_nodes", "label": "AtelierX Node", "status": "ok", "detail": "등록됨"},
                             {"id": "cloudflared", "label": "cloudflared", "status": "missing", "detail": "실행 파일 없음"}]}


class FakePanel:
    def __init__(self):
        self.mode = "valid"
        self.seen = []
        app = web.Application()
        app.router.add_get("/status", self.status)
        app.router.add_get("/elsewhere", self.status)
        self.server = TestServer(app, host="127.0.0.1", port=0)

    async def status(self, request):
        self.seen.append(request.headers.get("Authorization"))
        if request.headers.get("Authorization") != "Bearer " + PANEL_TOKEN or self.mode == "unauthorized":
            return web.json_response({"error": "unauthorized"}, status=401)
        if self.mode == "slow":
            await asyncio.sleep(5)
        if self.mode == "malformed":
            return web.Response(text="{not json", content_type="application/json")
        if self.mode == "wrong_shape":
            return web.json_response({"version": 2, "items": [], "dependencies": []})
        if self.mode == "redirect":
            raise web.HTTPFound("/elsewhere")
        if self.mode == "server_error":
            return web.json_response({}, status=500)
        return web.json_response(valid_status())


class OperationsStatusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token_file = Path(self.temp.name) / "control" / "token.txt"
        self.panel = FakePanel()
        await self.panel.server.start_server()
        self.panel_url = "http://127.0.0.1:%d" % self.panel.server.port
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        await self.panel.server.close()
        self.temp.cleanup()

    async def core(self, operations_status):
        client = TestClient(TestServer(create_app(Path(self.temp.name) / ("core%d.sqlite3" % len(self.clients)),
                                                  "http://generation.invalid", "core-token", operations_status=operations_status)))
        await client.start_server()
        self.clients.append(client)
        return client

    async def status(self, client, headers=CORE_AUTH):
        response = await client.get("/v1/operations/status", headers=headers)
        return response.status, await response.json(), response

    def configured(self):
        return {"url": self.panel_url, "token_file": str(self.token_file)}

    def write_token(self):
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(PANEL_TOKEN + "\n", encoding="utf-8")

    async def test_available_status_is_whitelisted(self):
        self.write_token()
        client = await self.core(self.configured())
        code, body, response = await self.status(client)
        self.assertEqual(code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(body["control_panel"], "available")
        self.assertEqual(body["generated_at"], "2026-09-23T10:00:00+09:00")
        self.assertEqual([item["id"] for item in body["items"]], ["services", "comfyui", "tunnel"])
        self.assertEqual(body["items"][0]["options"], {"generation": True, "validation": False, "discord_bridge": False})
        self.assertNotIn("options", body["items"][1])
        self.assertEqual(body["dependencies"][1], {"id": "cloudflared", "label": "cloudflared", "status": "missing", "detail": "실행 파일 없음"})
        self.assertEqual(self.panel.seen, ["Bearer " + PANEL_TOKEN])
        text = json.dumps(body)
        self.assertNotIn(PANEL_TOKEN, text)
        self.assertNotIn(self.panel_url, text)

    async def test_token_file_created_after_start_is_read_per_request(self):
        client = await self.core(self.configured())
        self.assertEqual((await self.status(client))[1], {"control_panel": "unavailable", "reason": "token_missing", "items": [], "dependencies": []})
        self.write_token()
        self.assertEqual((await self.status(client))[1]["control_panel"], "available")

    async def test_unavailable_reasons(self):
        self.write_token()
        cases = [(None, "not_configured"), ({"url": self.panel_url}, "not_configured"),
                 ({"url": "https://127.0.0.1:1", "token_file": str(self.token_file)}, "not_configured"),
                 ({"url": "http://example.com:8180", "token_file": str(self.token_file)}, "not_configured"),
                 ({"url": self.panel_url, "token_file": str(self.token_file) + ".missing"}, "token_missing")]
        for config, reason in cases:
            client = await self.core(config)
            code, body, _ = await self.status(client)
            self.assertEqual(code, 200)
            self.assertEqual(body, {"control_panel": "unavailable", "reason": reason, "items": [], "dependencies": []})
        client = await self.core(self.configured())
        for mode, reason in (("unauthorized", "unauthorized"), ("malformed", "invalid_response"), ("wrong_shape", "invalid_response"),
                             ("redirect", "invalid_response"), ("server_error", "invalid_response"), ("slow", "unreachable")):
            self.panel.mode = mode
            code, body, _ = await self.status(client)
            self.assertEqual((code, body.get("reason")), (200, reason), mode)
        self.token_file.write_text("wrong-token", encoding="utf-8")
        self.panel.mode = "valid"
        self.assertEqual((await self.status(client))[1]["reason"], "unauthorized")
        await self.panel.server.close()
        self.write_token()
        self.assertEqual((await self.status(client))[1]["reason"], "unreachable")

    async def test_core_auth_required(self):
        self.write_token()
        client = await self.core(self.configured())
        self.assertEqual((await client.get("/v1/operations/status")).status, 401)
        self.assertEqual((await client.get("/v1/operations/status", headers={"Authorization": "Bearer wrong"})).status, 401)
        self.assertEqual(self.panel.seen, [])

    def test_sanitize_drops_unknown_fields_and_invalid_values(self):
        payload = valid_status()
        payload["secret"] = "panel-token"
        payload["logs"] = ["line"]
        payload["items"][0].update({"token": "x", "command_line": "python --token x", "env": {"A": "B"}, "pid": "123",
                                    "ports": [8190, "8189", True, 70000], "managed": "yes", "last_error": "e" * 1000,
                                    "options": {"generation": True, "validation": "no", "extra": True}})
        payload["items"][1]["options"] = {"generation": True}
        payload["items"].extend([{"id": "unknown", "label": "x", "state": "running"}, {"id": "lmstudio", "label": "LM", "state": "bogus"},
                                 {"id": "services", "label": "duplicate", "state": "stopped"}, "text"])
        payload["dependencies"].extend([{"id": "d", "label": "D", "status": "broken"}, {"label": "no id", "status": "ok"},
                                        {"id": "x", "status": "warning", "detail": 5, "path": "C:\\secret"}])
        result = sanitize(payload)
        services = result["items"][0]
        self.assertEqual(set(services), {"id", "label", "state", "managed", "pid", "started_at", "ports", "autostart", "last_error", "options"})
        self.assertIsNone(services["pid"])
        self.assertEqual(services["ports"], [8190])
        self.assertFalse(services["managed"])
        self.assertEqual(len(services["last_error"]), 300)
        self.assertEqual(services["options"], {"generation": True})
        self.assertNotIn("options", result["items"][1])
        self.assertEqual([item["id"] for item in result["items"]], ["services", "comfyui", "tunnel"])
        self.assertEqual(result["dependencies"][-1], {"id": "x", "label": "x", "status": "warning", "detail": None})
        self.assertEqual(len(result["dependencies"]), 3)
        text = json.dumps(result)
        for secret in ("panel-token", "command_line", "C:\\\\secret", "logs", "env"):
            self.assertNotIn(secret, text)

    def test_loopback_url_rules(self):
        for value in ("http://127.0.0.1:8180", "http://localhost:8180/", "http://[::1]:8180"):
            self.assertIsNotNone(loopback_url(value))
        for value in ("https://127.0.0.1:8180", "http://10.0.0.1:8180", "http://user:pw@127.0.0.1:8180", "http://127.0.0.1:8180/path",
                      "http://127.0.0.1:8180?x=1", "http://127.0.0.1:99999", "http://127.0.0.1.evil.com", None, 5):
            self.assertIsNone(loopback_url(value), value)
        self.assertIsNone(OperationsStatus({"url": "http://evil.com", "token_file": "x"}).url)


if __name__ == "__main__":
    unittest.main()
