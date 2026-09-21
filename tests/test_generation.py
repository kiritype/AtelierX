import asyncio
import copy
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.generation import NODE, SERVICE, create_app

INPUT = dict(diffusion_model="anima", text_encoder="encoder", vae="vae",
             positive_prompt="adult character", negative_prompt="", width=512, height=512,
             seed=1, steps=24, cfg=4.5, sampler="euler", scheduler="normal")


def schema():
    required = {}
    for name, value in INPUT.items():
        if name in ("positive_prompt", "negative_prompt"):
            required[name] = ["STRING", {}]
        elif type(value) is int:
            required[name] = ["INT", {"min": 0, "max": 2**64-1}]
        elif type(value) is float:
            required[name] = ["FLOAT", {"min": 0, "max": 20}]
        else:
            required[name] = ["COMBO", {"options": [value]}]
    return {"input": {"required": required, "optional": {
        "lora_stack": ["STRING", {"atelierx_lora_stack": {"options": ["a", "b"]}}]}}}


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.posts, self.history, self.pending, self.running = [], {}, [], []
        self.busy, self.registered, self.reject, self.lose_response, self.wrong_prompt_id = True, True, False, False, False
        self.schema = schema()
        self.grants, self.releases = [], []
        fake = web.Application()

        async def info(request):
            name = request.match_info["name"]
            if name == NODE:
                return web.json_response({NODE: self.schema} if self.registered else {})
            return web.json_response({"SaveImage": {}})

        async def queue(request):
            running = [[0, "user-job"]] if self.busy else self.running
            return web.json_response({"queue_running": running, "queue_pending": self.pending})

        async def history(request):
            return web.json_response(self.history)

        async def post(request):
            data = await request.json()
            self.posts.append(data)
            if self.reject:
                return web.json_response({"error": "bad input"}, status=400)
            self.pending = [[0, data["prompt_id"]]]
            if self.lose_response:
                return web.Response(text="acceptance response corrupted")
            return web.json_response({"prompt_id": "another-prompt" if self.wrong_prompt_id else data["prompt_id"]})

        async def image(request):
            return web.Response(body=b"\x89PNG\r\n\x1a\nfixture", content_type="image/png")

        fake.add_routes([web.get("/object_info/{name}", info), web.get("/queue", queue),
                         web.get("/history/{id}", history), web.post("/prompt", post), web.get("/view", image)])
        self.comfy = TestServer(fake)
        await self.comfy.start_server()
        coordinator = web.Application()
        async def acquire(request):
            self.grants.append(await request.json())
            return web.json_response({"granted": True})
        async def release(request):
            self.releases.append(await request.json())
            return web.json_response({"released": True})
        coordinator.add_routes([web.post("/v1/gpu/acquire", acquire), web.post("/v1/gpu/release", release)])
        self.coordinator = TestServer(coordinator)
        await self.coordinator.start_server()
        self.client = await self.new_client()

    async def new_client(self):
        client = TestClient(TestServer(create_app(self.tmp.name, str(self.comfy.make_url("/")), "test-token", .01)))
        await client.start_server()
        return client

    async def asyncTearDown(self):
        await self.client.close()
        await self.comfy.close()
        await self.coordinator.close()
        self.tmp.cleanup()

    async def post(self, inputs=None, key="key"):
        return await self.client.post("/v1/nodes/anima/jobs", json={"inputs": INPUT if inputs is None else inputs},
                                      headers={"Authorization": "Bearer test-token", "Idempotency-Key": key})

    async def await_state(self, job_id, state):
        for _ in range(200):
            response = await self.client.get(f"/v1/jobs/{job_id}", headers={"Authorization": "Bearer test-token"})
            job = await response.json()
            if job["state"] == state:
                return job
            await asyncio.sleep(.01)
        self.fail(f"Expected {state}, last job {job}")

    async def test_auth_invalid_inputs_and_missing_node_do_not_submit(self):
        self.assertEqual((await self.client.get("/health")).status, 401)
        for field, value in [("width", 513), ("seed", True), ("diffusion_model", "missing"),
                             ("positive_prompt", " "), ("cfg", float("inf")), ("loras", [{"name": "missing", "strength": 1}])]:
            with self.subTest(field=field):
                self.assertEqual((await self.post(dict(INPUT, **{field: value}))).status, 400)
        self.registered = False
        self.assertEqual((await self.post()).status, 503)
        self.assertFalse(self.posts)
        self.assertFalse(list(Path(self.tmp.name).glob("jobs/*.json")))

    async def test_concurrent_idempotency_conflict_and_restart(self):
        responses = await asyncio.gather(*(self.post() for _ in range(6)))
        self.assertEqual(sorted(r.status for r in responses), [200]*5+[202])
        ids = {(await r.json())["job_id"] for r in responses}
        self.assertEqual(len(ids), 1)
        self.assertEqual((await self.post(dict(INPUT, seed=2))).status, 409)
        await self.client.close()
        self.client = await self.new_client()
        response = await self.post()
        self.assertEqual(response.status, 200)
        self.assertIn((await response.json())["job_id"], ids)
        self.assertFalse(self.posts)

    async def test_lora_translation_literal_prompts_and_user_queue_wait(self):
        value = dict(INPUT, loras=[{"name": "b", "strength": .4}, {"name": "a", "strength": .2}])
        job = await (await self.post(value)).json()
        await asyncio.sleep(.05)
        self.assertFalse(self.posts)
        self.busy = False
        await self.await_state(job["job_id"], "submitted")
        sent = self.posts[0]["prompt"]["1"]["inputs"]
        self.assertEqual(sent["lora_stack"], '[{"name":"b","strength":0.4},{"name":"a","strength":0.2}]')
        self.assertEqual(sent["positive_prompt"], INPUT["positive_prompt"])
        self.assertEqual(self.posts[0]["prompt"]["2"]["class_type"], "SaveImage")

    async def test_acceptance_response_loss_tracks_without_repost(self):
        self.lose_response = True
        job = await (await self.post()).json()
        self.busy = False
        await self.await_state(job["job_id"], "submitted")
        await self.client.close()
        self.client = await self.new_client()
        await asyncio.sleep(.05)
        self.assertEqual(len(self.posts), 1)
        self.pending = []
        self.history = {job["job_id"]: {"status": {"completed": True, "status_str": "success"},
                                       "outputs": {"2": {"images": [{"filename": "result.png", "type": "output", "subfolder": ""}]}}}}
        result = await self.await_state(job["job_id"], "completed")
        image = await self.client.get(result["images"][0]["url"], headers={"Authorization": "Bearer test-token"})
        self.assertEqual(image.status, 200)
        self.assertTrue((await image.read()).startswith(b"\x89PNG"))
        self.assertEqual(len(self.posts), 1)

    async def test_execution_error_does_not_retry(self):
        job = await (await self.post()).json()
        self.busy = False
        await self.await_state(job["job_id"], "submitted")
        self.pending = []
        self.history = {job["job_id"]: {"status": {"status_str": "error", "messages": [["execution_error", {"node_id": "1"}]]}}}
        result = await self.await_state(job["job_id"], "failed")
        self.assertEqual(result["error"]["code"], "GEN_EXECUTION_FAILED")
        await asyncio.sleep(.05)
        self.assertEqual(len(self.posts), 1)

    async def test_missing_execution_and_rejected_prompt_do_not_retry(self):
        self.reject = True
        job = await (await self.post()).json()
        self.busy = False
        result = await self.await_state(job["job_id"], "failed")
        self.assertEqual(result["error"]["code"], "GEN_COMFY_REJECTED")
        self.reject = False
        job = await (await self.post(key="next")).json()
        await self.await_state(job["job_id"], "submitted")
        self.pending = []
        result = await self.await_state(job["job_id"], "failed")
        self.assertEqual(result["error"]["code"], "GEN_EXECUTION_UNKNOWN")
        self.assertEqual(len(self.posts), 2)

    async def test_queue_race_releases_gpu_before_any_prompt_submission(self):
        self.client.app[SERVICE].coordinator_url = str(self.coordinator.make_url("/"))
        job = await (await self.post(key="queue-race")).json()
        await asyncio.sleep(.05)
        current = await (await self.client.get(f'/v1/jobs/{job["job_id"]}', headers={"Authorization": "Bearer test-token"})).json()
        self.assertEqual(current["state"], "queued")
        self.assertFalse(self.posts)
        self.assertTrue(self.grants)
        self.assertTrue(self.releases)

    async def test_wrong_prompt_identity_is_unknown_and_retains_gpu_lease(self):
        self.client.app[SERVICE].coordinator_url = str(self.coordinator.make_url("/"))
        self.busy = False
        self.wrong_prompt_id = True
        job = await (await self.post(key="wrong-prompt-id")).json()
        result = await self.await_state(job["job_id"], "failed")
        self.assertEqual(result["error"]["code"], "GEN_EXECUTION_UNKNOWN")
        self.assertTrue(result["gpu_requested"])
        await asyncio.sleep(.04)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.releases, [])


    async def test_cancel_queued_and_running_without_interrupting_user_job(self):
        first = await (await self.post(key="cancel-queued")).json()
        response = await self.client.post("/v1/jobs/" + first["job_id"] + "/cancel", headers={"Authorization": "Bearer test-token"})
        self.assertEqual((await response.json())["state"], "cancelled")
        self.assertEqual(self.posts, [])
        second = await (await self.post(key="cancel-running")).json()
        self.busy = False
        await self.await_state(second["job_id"], "submitted")
        response = await self.client.post("/v1/jobs/" + second["job_id"] + "/cancel", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(response.status, 202)
        self.assertTrue((await response.json())["cancel_requested"])
        self.pending = []
        self.history = {second["job_id"]: {"status": {"completed": True, "status_str": "success"}, "outputs": {"2": {"images": [{"filename": "result.png", "type": "output", "subfolder": ""}]}}}}
        result = await self.await_state(second["job_id"], "cancelled")
        self.assertEqual(result["images"], [])
        self.assertEqual(len(self.posts), 1)


if __name__ == "__main__":
    unittest.main()
