import asyncio
import hashlib
from pathlib import Path
import tempfile
import unittest
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.core import CORE, create_app


class CoreValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs, self.posts = {}, []
        self.outcome, self.lose_reply, self.corrupt = "passed", False, False
        provider = web.Application()

        async def submit(request):
            self.assertEqual(request.headers.get("Authorization"), "Bearer validation-token")
            payload = await request.json()
            self.posts.append(payload)
            key = request.headers["Idempotency-Key"]
            job = dict(job_id=str(uuid.uuid4()), state="queued", request=payload, outcome=None, result=None, error=None)
            self.jobs[key] = job
            if self.lose_reply:
                return web.Response(text="lost response")
            return web.json_response(job, status=202)

        async def lookup(request):
            job = self.jobs.get(request.headers.get("Idempotency-Key")) if request.path.endswith("by-key") else next(
                (job for job in self.jobs.values() if job["job_id"] == request.match_info["id"]), None)
            if not job:
                return web.json_response({}, status=404)
            job.update(state="failed" if self.outcome == "error" else "completed", outcome=self.outcome,
                       result=None if self.outcome == "error" else {"outcome": self.outcome, "findings": []},
                       error={"code": "VAL_PROVIDER_RESPONSE_INVALID"} if self.outcome == "error" else None)
            if self.corrupt:
                job["request"] = {}
            return web.json_response(job)

        provider.add_routes([web.post("/v1/validations/single", submit),
                             web.get("/v1/validation-jobs/by-key", lookup), web.get("/v1/validation-jobs/{id}", lookup)])
        self.backend = TestServer(provider)
        await self.backend.start_server()
        self.config = {"url": str(self.backend.make_url("/")), "profiles": {"p": {"profile_id": "p", "revision": 1}},
                       "providers": {"v": {"provider_id": "v", "revision": 1}}}
        self.client = await self.new_client()
        store = self.client.app[CORE].store
        work = store.create_entity("works", "not-a-prompt", None)
        character = store.create_entity("characters", "not-a-prompt", work["id"])
        outfit = store.create_entity("outfits", "not-a-prompt", character["id"], {"appearance": "blue eyes", "upper": "shirt", "lower": "boots"})
        group = store.create_group(outfit["id"])
        self.task = store.create_task("gen-key", "fingerprint", group["id"], {
            "generation_endpoint": "http://127.0.0.1:8189", "generation_inputs": {
                "positive_prompt": "blue eyes, shirt, upper body", "negative_prompt": "blurry", "width": 512, "height": 512}})
        self.image = {"id": str(uuid.uuid4()), "task_id": self.task["id"], "group_id": group["id"],
                      "generation_image_id": str(uuid.uuid4()) + "-0", "sha256": hashlib.sha256(b"image").hexdigest(),
                      "media_type": "image/png", "bytes": 5, "validation_state": "not_requested"}
        store.finish_generation(self.task, [self.image])

    async def new_client(self):
        client = TestClient(TestServer(create_app(Path(self.tmp.name) / "core.sqlite3", "http://127.0.0.1:8189", "core-token",
                            poll=.01, validation_config=self.config, validation_token="validation-token")))
        await client.start_server()
        return client

    async def asyncTearDown(self):
        await self.client.close()
        await self.backend.close()
        self.tmp.cleanup()

    async def request(self, method, path, body=None, key=None):
        headers = {"Authorization": "Bearer core-token"}
        if key:
            headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        return response.status, await response.json()

    async def submit(self, key="validation-key"):
        return await self.request("POST", "/v1/images/" + self.image["id"] + "/validations", {"profile_id": "p", "provider_id": "v"}, key)

    async def wait_run(self, run):
        for _ in range(100):
            _, run = await self.request("GET", "/v1/validation-runs/" + run["id"])
            if run["state"] in {"completed", "failed"}:
                return run
            await asyncio.sleep(.01)
        self.fail(str(run))

    async def test_saved_prompt_result_and_restart_idempotency(self):
        status, run = await self.submit()
        self.assertEqual(status, 202)
        result = await self.wait_run(run)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(self.posts[0]["image"]["positive_prompt"], "blue eyes, shirt, upper body")
        self.assertEqual(self.posts[0]["image"]["source"]["image_id"], self.image["generation_image_id"])
        _, image = await self.request("GET", "/v1/images/" + self.image["id"])
        self.assertEqual(image["validation"]["outcome"], "passed")
        await self.client.close()
        self.client = await self.new_client()
        status, duplicate = await self.submit()
        self.assertEqual((status, duplicate["id"], len(self.posts)), (200, run["id"], 1))

    async def test_error_is_recorded_without_regeneration_and_manual_revalidation(self):
        self.outcome = "error"
        _, run = await self.submit()
        result = await self.wait_run(run)
        self.assertEqual(result["error"]["code"], "VAL_PROVIDER_RESPONSE_INVALID")
        task = self.client.app[CORE].store.task(self.task["id"])
        self.assertEqual((task["state"], task["automatic_attempts_used"]), ("generated", 0))
        self.outcome = "failed"
        _, rerun = await self.submit("manual-new-key")
        self.assertNotEqual(rerun["id"], run["id"])
        self.assertEqual((await self.wait_run(rerun))["outcome"], "failed")
        self.assertEqual(len(self.posts), 2)

    async def test_lost_response_is_looked_up_without_posting_again(self):
        self.lose_reply = True
        _, run = await self.submit()
        self.assertEqual((await self.wait_run(run))["outcome"], "passed")
        self.assertEqual(len(self.posts), 1)

    async def test_mismatched_validation_job_is_not_applied(self):
        self.corrupt = True
        _, run = await self.submit()
        self.assertEqual((await self.wait_run(run))["error"]["code"], "CORE_VALIDATION_PROTOCOL_ERROR")

    async def test_duplicate_key_conflict_and_unknown_configuration(self):
        _, run = await self.submit()
        await self.wait_run(run)
        path = "/v1/images/" + self.image["id"] + "/validations"
        self.assertEqual((await self.request("POST", path, {"profile_id": "different", "provider_id": "v"}, "validation-key"))[0], 409)
        self.assertEqual((await self.request("POST", path, {"profile_id": "p", "provider_id": "unknown"}, "new-key"))[0], 400)

    async def test_automatic_followup_uses_frozen_selection_once(self):
        core = self.client.app[CORE]
        frozen = core.validation.freeze({"profile_id": "p", "provider_id": "v"})
        snapshot = dict(self.task["snapshot"], validation=frozen)
        core.store.task_metadata(self.task["id"], snapshot=snapshot)
        self.config["providers"]["v"]["revision"] = 2
        for _ in range(100):
            runs = core.store.image_validations(self.image["id"])
            if runs and runs[0]["state"] == "completed": break
            await asyncio.sleep(.01)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["outcome"], "passed")
        self.assertEqual(self.posts[0]["provider"]["revision"], 1)
        await core.validation.tick()
        self.assertEqual(len(self.posts), 1)
        await self.client.close(); self.client = await self.new_client()
        await self.client.app[CORE].validation.tick()
        self.assertEqual(len(self.posts), 1)

    async def test_cancel_queued_validation_and_late_result_guard(self):
        from unittest.mock import AsyncMock
        core = self.client.app[CORE]
        core.validation.advance = AsyncMock()
        run, _ = core.validation.submit(self.image["id"], "cancel-run", {"profile_id": "p", "provider_id": "v"})
        response = await self.client.post("/v1/validation-runs/" + run["id"] + "/cancel", headers={"Authorization": "Bearer core-token"})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["state"], "cancelled")
        run.update(state="completed", outcome="passed", result={})
        core.store.update_validation(run)
        self.assertEqual(core.store.validation_run(run["id"])["state"], "cancelled")
        self.assertEqual(self.posts, [])
