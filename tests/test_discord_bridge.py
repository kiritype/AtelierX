import hashlib
import asyncio
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.discord_bridge import BRIDGE, Bridge, create_app
from atelierx.common import ApiError
from atelierx.core import CORE, create_app as core_app


class DiscordBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"TEST_BRIDGE": "bridge-secret", "TEST_CORE": "core-secret"})
        self.env.start()
        self.posts = 0
        self.patches = []
        self.image_bytes = b"test-image"
        self.job = {"id": "core-1", "state": "completed", "images": [
            {"image_id": "image-1", "bytes": len(self.image_bytes), "media_type": "image/png",
             "sha256": hashlib.sha256(self.image_bytes).hexdigest()}]}
        self.lookup_missing = False
        self.delivery_status = 200
        self.core_headers = []

        async def core(request):
            self.core_headers.append(request.headers.get("Authorization"))
            if request.method == "POST":
                self.posts += 1
                self.last_body = await request.json()
                self.last_key = request.headers.get("Idempotency-Key")
            if request.path.endswith("by-key") and self.lookup_missing:
                return web.Response(status=404)
            if request.path.endswith("content"):
                return web.Response(body=self.image_bytes, content_type="image/png")
            return web.json_response(self.job)

        async def discord(request):
            self.patches.append(await request.read())
            return web.json_response({}, status=self.delivery_status, headers={"Retry-After": "120"})

        core_app = web.Application()
        core_app.router.add_route("*", "/{path:.*}", core)
        self.core_server = TestServer(core_app)
        await self.core_server.start_server()
        discord_app = web.Application()
        discord_app.router.add_patch("/{path:.*}", discord)
        self.discord_server = TestServer(discord_app)
        await self.discord_server.start_server()
        self.config = dict(core_url=str(self.core_server.make_url("")), core_token_env="TEST_CORE",
                           bridge_token_env="TEST_BRIDGE", application_id="123", allowed_user_id="456")
        self.bridge = Bridge(self.tmp.name, self.config, discord_api=str(self.discord_server.make_url("")))
        self.session = aiohttp.ClientSession()
        self.bridge.session = self.session

    async def asyncTearDown(self):
        self.bridge.owner.close()
        await self.session.close()
        await self.core_server.close()
        await self.discord_server.close()
        self.env.stop()
        self.tmp.cleanup()

    def body(self, identifier="100", **changes):
        body = dict(interaction_id=identifier, application_id="123", interaction_token="test-token",
                    user_id="456", prompt="a blue bird", mode="direct", attachment_size_limit=10000,
                    received_at=time.time())
        body.update(changes)
        return body

    async def test_duplicate_and_completed_image_delivery(self):
        public, created = self.bridge.accept(self.body())
        self.assertTrue(created)
        self.assertNotIn("token", public)
        self.assertFalse(self.bridge.accept(self.body())[1])
        await self.bridge.tick()
        await self.bridge.tick()
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.last_body, {"prompt": "a blue bird", "mode": "direct"})
        self.assertEqual(self.last_key, "discord:100")
        self.assertEqual(len(self.patches), 2)
        self.assertIn(self.image_bytes, self.patches[-1])
        self.assertEqual(self.bridge.records["100"]["delivery"], "delivered")
        self.assertIsNone(self.bridge.records["100"]["token"])
        self.assertTrue(all(h == "Bearer core-secret" for h in self.core_headers))

    async def test_restart_after_dispatch_intent_uses_lookup_without_post(self):
        self.bridge.accept(self.body())
        record = self.bridge.records["100"]
        record["state"] = "dispatching"
        self.bridge.save(record)
        self.bridge.owner.close()
        self.bridge = Bridge(self.tmp.name, self.config, discord_api=str(self.discord_server.make_url("")))
        self.bridge.session = self.session
        await self.bridge.tick()
        self.assertEqual(self.posts, 0)
        self.assertEqual(self.bridge.records["100"]["state"], "completed")

    async def test_unknown_acceptance_never_reposts(self):
        self.bridge.accept(self.body())
        self.bridge.records["100"]["state"] = "dispatching"
        self.lookup_missing = True
        await self.bridge.tick()
        await self.bridge.tick()
        self.assertEqual(self.posts, 0)
        self.assertEqual(self.bridge.records["100"]["error"], "BRIDGE_ACCEPTANCE_UNKNOWN")

    async def test_expired_reply_can_be_retrieved_with_fresh_status_without_generation(self):
        self.bridge.accept(self.body())
        record = self.bridge.records["100"]
        await self.bridge.advance(record)
        record["created_at"] -= 901
        await self.bridge.deliver(record)
        self.assertEqual(record["delivery"], "expired")
        body = self.body("101")
        body.pop("prompt"); body.pop("mode"); body["request_id"] = "100"
        self.bridge.accept(body, status=True)
        await self.bridge.tick()
        self.assertEqual(self.posts, 1)
        self.assertEqual(len(self.patches), 1)
        self.assertIn(self.image_bytes, self.patches[0])

    async def test_rate_limit_waits_and_does_not_regenerate(self):
        self.delivery_status = 429
        self.bridge.accept(self.body())
        await self.bridge.tick()
        await self.bridge.tick()
        self.assertEqual(self.posts, 1)
        self.assertEqual(len(self.patches), 1)
        self.assertGreater(self.bridge.records["100"]["next_delivery_at"], time.time() + 100)

    async def test_attachment_limit_reports_result_without_oversized_upload(self):
        body = self.body()
        body["attachment_size_limit"] = 1
        self.bridge.accept(body)
        await self.bridge.tick()
        self.assertNotIn(self.image_bytes, self.patches[-1])
        self.assertIn(b"attachments", self.patches[-1])
        self.assertEqual(self.posts, 1)

    async def test_input_identity_conflict_and_expired_queued_request(self):
        body = self.body(); body["user_id"] = "999"
        with self.assertRaises(ApiError):
            self.bridge.accept(body)
        self.bridge.accept(self.body())
        body = self.body(); body["prompt"] = "different"
        with self.assertRaises(ApiError):
            self.bridge.accept(body)
        self.bridge.records["100"]["created_at"] -= 901
        await self.bridge.tick()
        self.assertEqual(self.posts, 0)
        self.assertEqual(self.bridge.records["100"]["error"], "BRIDGE_REQUEST_EXPIRED")

    async def test_http_requires_auth_and_does_not_return_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(TestServer(create_app(directory, self.config, poll=100)))
            await client.start_server()
            try:
                response = await client.post("/v1/discord/jobs", json=self.body())
                self.assertEqual(response.status, 401)
                response = await client.post("/v1/discord/jobs", json=self.body(), headers={"Authorization": "Bearer bridge-secret"})
                self.assertEqual(response.status, 202)
                self.assertNotIn("test-token", await response.text())
            finally:
                await client.close()

    async def test_allowlisted_friend_cannot_retrieve_another_users_result(self):
        self.bridge.allowed_users.append("789")
        self.bridge.accept(self.body())
        body = self.body("101"); body["user_id"] = "789"
        self.assertTrue(self.bridge.accept(body)[1])
        status = self.body("102")
        status.pop("prompt"); status.pop("mode")
        status.update(user_id="789", request_id="100")
        with self.assertRaises(ApiError) as failure:
            self.bridge.accept(status, status=True)
        self.assertEqual(failure.exception.status, 404)

    async def test_guild_mode_allows_nonowner_in_scope_and_denies_outside_or_dm(self):
        config = {**self.config, "access_mode": "guild", "allowed_guild_ids": ["900"], "allowed_channel_ids": ["901"]}
        config.pop("allowed_user_id")
        bridge = Bridge(Path(self.tmp.name) / "guild", config, discord_api=str(self.discord_server.make_url("")))
        try:
            body = self.body("200", user_id="789", guild_id="900", channel_id="901")
            self.assertTrue(bridge.accept(body)[1])
            saved = bridge.records["200"]
            self.assertEqual((saved["guild_id"], saved["channel_id"]), ("900", "901"))
            for changes in ({"guild_id":"999", "channel_id":"901"}, {"guild_id":"900", "channel_id":"999"}):
                with self.assertRaises(ApiError) as failure: bridge.accept(self.body(str(201 + len(changes)), user_id="789", **changes))
                self.assertEqual(failure.exception.status, 403)
            dm = self.body("204", user_id="789"); dm.pop("guild_id", None); dm.pop("channel_id", None)
            with self.assertRaises(ApiError): bridge.accept(dm)
        finally:
            bridge.owner.close()

    async def test_guild_mode_status_remains_requester_only_and_invalid_config_fails_closed(self):
        config = {**self.config, "access_mode": "guild", "allowed_guild_ids": ["900"]}; config.pop("allowed_user_id")
        bridge = Bridge(Path(self.tmp.name) / "guild-status", config, discord_api=str(self.discord_server.make_url("")))
        try:
            bridge.accept(self.body("210", user_id="789", guild_id="900", channel_id="901"))
            status = self.body("211", user_id="790", guild_id="900", channel_id="901"); status.pop("prompt"); status.pop("mode"); status["request_id"] = "210"
            with self.assertRaises(ApiError) as failure: bridge.accept(status, status=True)
            self.assertEqual(failure.exception.status, 404)
        finally:
            bridge.owner.close()
        for bad in ({**self.config, "access_mode":"guild", "allowed_guild_ids":[]}, {**self.config, "access_mode":"guild", "allowed_guild_ids":["900"], "allowed_channel_ids":[]}):
            bad.pop("allowed_user_id", None)
            with self.assertRaises(ValueError): Bridge(Path(self.tmp.name) / ("bad" + str(len(bad))), bad)

    async def test_real_core_rest_to_bridge_delivery_without_creating_a_group(self):
        submissions = []
        remote_jobs = {}

        async def submit(request):
            payload = await request.json()
            submissions.append(payload)
            job = dict(job_id="generation-1", state="completed", inputs=payload["inputs"],
                       requested_postprocess=payload["postprocess"], images=self.job["images"])
            remote_jobs[request.headers["Idempotency-Key"]] = job
            return web.json_response(job, status=202)

        async def by_key(request):
            job = remote_jobs.get(request.headers.get("Idempotency-Key"))
            return web.json_response(job) if job else web.Response(status=404)

        async def image(request):
            return web.Response(body=self.image_bytes, content_type="image/png")

        gen = web.Application()
        gen.add_routes([web.post("/v1/nodes/anima/jobs", submit), web.get("/v1/jobs/by-key", by_key),
                        web.get("/v1/images/image-1", image)])
        gen_server = TestServer(gen)
        await gen_server.start_server()
        with tempfile.TemporaryDirectory() as directory:
            config = {"generation_inputs": {"diffusion_model": "model", "text_encoder": "encoder", "vae": "vae",
                      "seed": 1, "steps": 1, "cfg": 1, "sampler": "euler", "scheduler": "normal", "negative_prompt": "bad"},
                      "postprocess": {}, "llm": {"url": "http://localhost:1234/v1/chat/completions", "model": "local",
                                                  "api_key_env": "TEST_LLM", "timeout_seconds": 1}}
            app = core_app(Path(directory) / "core.sqlite3", str(gen_server.make_url("")), "core-secret",
                           poll=.01, standalone_config=config)
            core_server = TestServer(app)
            await core_server.start_server()
            bridge = Bridge(Path(directory) / "bridge", {**self.config, "core_url": str(core_server.make_url(""))},
                            discord_api=str(self.discord_server.make_url("")))
            bridge.session = self.session
            try:
                bridge.accept(self.body())
                for _ in range(100):
                    await bridge.tick()
                    if bridge.records["100"]["delivery"] == "delivered":
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(bridge.records["100"]["state"], "completed")
                self.assertEqual(bridge.records["100"]["delivery"], "delivered")
                self.assertEqual(len(submissions), 1)
                self.assertEqual(submissions[0]["inputs"]["positive_prompt"], "a blue bird")
                self.assertIn(self.image_bytes, self.patches[-1])
                self.assertEqual(app[CORE].store.db.execute("SELECT COUNT(*) FROM groups").fetchone()[0], 0)
                self.assertEqual(app[CORE].store.db.execute("SELECT COUNT(*) FROM standalone_jobs").fetchone()[0], 1)
            finally:
                bridge.owner.close()
                await core_server.close()
                await gen_server.close()
