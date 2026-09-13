import asyncio
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.api_client import CoreClient
from atelierx.common import ApiError


class CoreClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen, self.mutations = [], []
        app = web.Application()

        async def payload(request):
            self.seen.append((request.path, request.headers.get("Authorization"), dict(request.query), request.headers.get("Idempotency-Key")))
            return web.json_response({"path": request.path, "query": dict(request.query)})

        async def detail(request):
            self.seen.append((request.path, request.headers.get("Authorization"), {}, None))
            return web.json_response({"id": request.match_info["id"]})

        async def mutation(request):
            body = await request.json() if request.content_length else None
            self.mutations.append((request.path, request.headers.get("Idempotency-Key"), body))
            if request.headers.get("Idempotency-Key") == "conflict":
                return web.json_response({"error": {"code": "CORE_IDEMPOTENCY_CONFLICT"}}, status=409)
            return web.json_response({"path": request.path, "accepted": True}, status=202)

        async def service_error(request):
            return web.json_response({"error": {"code": "CORE_REVISION_CONFLICT", "message": "Bearer secret-reflected"}}, status=409)

        async def unsafe_code(request):
            return web.json_response({"error": {"code": "TOKEN_REFLECTED", "message": "ignored"}}, status=400)

        async def invalid_json(request):
            return web.Response(text="not json", content_type="text/plain")

        async def slow(request):
            await asyncio.sleep(.08)
            return web.json_response({"ok": True})

        async def redirect(request):
            raise web.HTTPFound("/redirect-target")

        async def redirect_target(request):
            self.seen.append((request.path, request.headers.get("Authorization"), {}, None))
            return web.json_response({"unexpected": True})

        app.add_routes([
            web.get("/health", payload), web.get("/v1/queue", payload), web.get("/v1/settings", payload),
            web.patch("/v1/settings", mutation),
            web.get("/v1/groups", payload), web.get("/v1/groups/{id}", detail),
            web.get("/v1/images", payload), web.get("/v1/images/{id}", detail),
            web.get("/v1/tasks", payload), web.get("/v1/tasks/{id}", detail),
            web.get("/v1/group-batches", payload), web.get("/v1/group-batches/{id}", detail),
            web.get("/v1/groups/{id}/batches", payload), web.post("/v1/groups/{id}/batches", mutation),
            web.post("/v1/group-batches/{id}/cancel", mutation),
            web.post("/v1/group-batches/{id}/confirm-reference", mutation),
            web.post("/v1/write", payload), web.get("/error", service_error), web.get("/unsafe-code", unsafe_code), web.get("/invalid", invalid_json),
            web.get("/slow", slow), web.get("/redirect", redirect), web.get("/redirect-target", redirect_target),
            web.post("/v1/prompts/preview", mutation), web.post("/v1/tasks", mutation), web.get("/v1/tasks/by-key", payload),
            web.post("/v1/images/{id}/validations", mutation), web.post("/v1/tasks/{id}/regenerations", mutation),
            web.post("/v1/tasks/{id}/cancel", mutation), web.post("/v1/validation-runs/{id}/cancel", mutation),
            web.get("/v1/validation-runs/{id}", detail), web.get("/v1/tasks/{id}/attempts", payload),
            web.get("/v1/regeneration-cycles/{id}", detail), web.post("/v1/regeneration-cycles/{id}/stop", mutation),
        ])
        self.server = TestServer(app)
        await self.server.start_server()
        self.base_url = str(self.server.make_url("/")).rstrip("/")

    async def asyncTearDown(self):
        await self.server.close()

    async def test_read_contract_query_auth_and_detail_methods(self):
        async with CoreClient(self.base_url, "client-token") as client:
            groups = await client.list_groups(outfit_id="group-filter", limit="20")
            self.assertEqual(groups["query"], {"outfit_id": "group-filter", "limit": "20"})
            self.assertEqual((await client.get_group("group-id"))["id"], "group-id")
            self.assertEqual((await client.get_image("image-id"))["id"], "image-id")
            self.assertEqual((await client.get_task("task-id"))["id"], "task-id")
            self.assertEqual((await client.get_group_batch("batch-id"))["id"], "batch-id")
            self.assertEqual((await client.health())["path"], "/health")
            self.assertEqual((await client.queue(state="queued"))["query"], {"state": "queued"})
            self.assertEqual((await client.get_settings())["path"], "/v1/settings")
        self.assertTrue(client._session.closed)
        self.assertTrue(all(item[1] == "Bearer client-token" for item in self.seen))

    async def test_generic_one_shot_idempotency_and_safe_service_error(self):
        async with CoreClient(self.base_url, "client-token") as client:
            result = await client.request("POST", "/v1/write", json={"a": 1}, idempotency_key="one-key")
            self.assertEqual(result["path"], "/v1/write")
            with self.assertRaises(ApiError) as raised:
                await client.request("GET", "/error")
        self.assertEqual((raised.exception.code, raised.exception.status), ("CORE_REVISION_CONFLICT", 409))
        self.assertNotIn("secret-reflected", raised.exception.message)
        async with CoreClient(self.base_url, "TOKEN_REFLECTED") as client:
            with self.assertRaises(ApiError) as raised:
                await client.request("GET", "/unsafe-code")
        self.assertEqual(raised.exception.code, "CLIENT_HTTP_ERROR")
        self.assertEqual([item[0] for item in self.seen].count("/v1/write"), 1)
        self.assertEqual(next(item[3] for item in self.seen if item[0] == "/v1/write"), "one-key")

    async def test_generation_validation_regeneration_and_cancel_contracts(self):
        async with CoreClient(self.base_url, "client-token") as client:
            self.assertEqual((await client.preview_prompt({"group_id": "group"}))["path"], "/v1/prompts/preview")
            self.assertEqual((await client.create_task({"group_id": "group"}, "task-key"))["path"], "/v1/tasks")
            self.assertEqual((await client.get_task_by_key("task-key"))["path"], "/v1/tasks/by-key")
            self.assertEqual((await client.validate_image("image", {"profile_id": "p"}, "validation-key"))["path"], "/v1/images/image/validations")
            self.assertEqual((await client.regenerate_task("task", {}, "regeneration-key"))["path"], "/v1/tasks/task/regenerations")
            self.assertEqual((await client.cancel_task("task"))["path"], "/v1/tasks/task/cancel")
            self.assertEqual((await client.cancel_validation("run"))["path"], "/v1/validation-runs/run/cancel")
            self.assertEqual((await client.get_validation_run("run"))["id"], "run")
            self.assertEqual((await client.list_task_attempts("task", limit="10"))["query"], {"limit": "10"})
            self.assertEqual((await client.get_cycle("cycle"))["id"], "cycle")
            self.assertEqual((await client.stop_cycle("cycle"))["path"], "/v1/regeneration-cycles/cycle/stop")
            with self.assertRaises(ApiError) as raised:
                await client.create_task({"group_id": "group"}, "conflict")
        self.assertEqual((raised.exception.code, raised.exception.status), ("CORE_IDEMPOTENCY_CONFLICT", 409))
        self.assertIn(("/v1/tasks", "task-key", {"group_id": "group"}), self.mutations)
        self.assertIn(("/v1/images/image/validations", "validation-key", {"profile_id": "p"}), self.mutations)
        self.assertIn(("/v1/tasks/task/regenerations", "regeneration-key", {}), self.mutations)
        self.assertIn(("/v1/tasks/task/cancel", None, None), self.mutations)

    async def test_group_batch_and_settings_mutation_contracts(self):
        body = {"items": [{"prompt": "portrait"}], "group_validation": {"profile_id": "group-profile"}}
        async with CoreClient(self.base_url, "client-token") as client:
            self.assertEqual((await client.update_settings({"revision": 1, "changes": {}}))["path"], "/v1/settings")
            listed = await client.list_group_batches_for_group("group")
            self.assertEqual(listed["path"], "/v1/groups/group/batches")
            self.assertEqual((await client.create_group_batch("group", body, "batch-key"))["path"], "/v1/groups/group/batches")
            self.assertEqual((await client.cancel_group_batch("batch"))["path"], "/v1/group-batches/batch/cancel")
            self.assertEqual((await client.confirm_group_batch_reference("batch", {"reference_revision": 2}, "confirm-key"))["path"], "/v1/group-batches/batch/confirm-reference")
            with self.assertRaises(ApiError) as raised:
                await client.create_group_batch("group", body, "conflict")
        self.assertEqual((raised.exception.code, raised.exception.status), ("CORE_IDEMPOTENCY_CONFLICT", 409))
        self.assertIn(("/v1/settings", None, {"revision": 1, "changes": {}}), self.mutations)
        self.assertIn(("/v1/groups/group/batches", "batch-key", body), self.mutations)
        self.assertIn(("/v1/group-batches/batch/cancel", None, None), self.mutations)
        self.assertIn(("/v1/group-batches/batch/confirm-reference", "confirm-key", {"reference_revision": 2}), self.mutations)

    async def test_protocol_timeout_transport_redirect_and_path_failures_are_distinct(self):
        async with CoreClient(self.base_url, "client-token") as client:
            for path, code, status in (("/invalid", "CLIENT_PROTOCOL_ERROR", 502),
                                       ("/redirect", "CLIENT_REDIRECT_BLOCKED", 302)):
                with self.subTest(path=path), self.assertRaises(ApiError) as raised:
                    await client.request("GET", path)
                self.assertEqual((raised.exception.code, raised.exception.status), (code, status))
            with self.assertRaises(ApiError) as raised:
                await client.request("GET", "https://elsewhere.invalid/path")
            self.assertEqual(raised.exception.code, "CLIENT_INVALID_PATH")
            for identifier in ("%2f", "%2e%2e", "has space", "line\nfeed"):
                with self.subTest(identifier=identifier), self.assertRaises(ApiError) as raised:
                    await client.get_group(identifier)
                self.assertEqual(raised.exception.code, "CLIENT_INVALID_PATH")
        self.assertNotIn("/redirect-target", [item[0] for item in self.seen])
        async with CoreClient(self.base_url, "client-token", timeout=.01) as client:
            with self.assertRaises(ApiError) as raised:
                await client.request("GET", "/slow")
        self.assertEqual((raised.exception.code, raised.exception.status), ("CLIENT_TIMEOUT", 504))
        class BrokenSession:
            closed = False
            async def close(self): self.closed = True
            def request(self, *args, **kwargs):
                raise aiohttp.ClientConnectionError("fixture transport failure")
        async with CoreClient(self.base_url, "client-token") as client:
            await client._session.close()
            client._session = BrokenSession()
            with self.assertRaises(ApiError) as raised:
                await client.health()
        self.assertEqual((raised.exception.code, raised.exception.status), ("CLIENT_TRANSPORT_ERROR", 503))

    async def test_closed_session_and_constructor_validation(self):
        client = CoreClient(self.base_url, "client-token")
        with self.assertRaises(ApiError) as raised:
            await client.health()
        self.assertEqual(raised.exception.code, "CLIENT_SESSION_CLOSED")
        for base_url, token in (("https://user:pass@example.test", "token"), ("https://example.test/path", "token"), (self.base_url, ""),
                                (self.base_url, "line\r\nbreak"), (None, "token")):
            with self.subTest(base_url=base_url):
                with self.assertRaises(ValueError):
                    CoreClient(base_url, token)
        for timeout in (float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                CoreClient(self.base_url, "token", timeout=timeout)


if __name__ == "__main__":
    unittest.main()
