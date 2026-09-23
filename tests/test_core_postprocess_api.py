"""Core REST boundary tests for independent postprocess jobs; no GPU or ComfyUI."""
import asyncio
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from atelierx.core import CORE, create_app


def png_bytes(color=(20, 40, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", (2, 3), color).save(buffer, format="PNG")
    return buffer.getvalue()


GEN_INPUTS = {"diffusion_model": "anima", "text_encoder": "encoder", "vae": "vae", "width": 512, "height": 512,
              "seed": 1, "steps": 24, "cfg": 4.5, "sampler": "euler", "scheduler": "normal"}
PARTS = {"appearance": "silver hair", "upper": "white shirt", "lower": "black trousers"}


class CorePostprocessApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = png_bytes(); self.output = png_bytes((70, 80, 90))
        self.posts, self.jobs, self.lost_posts = [], {}, 0
        app = web.Application()

        def public(job):
            return {key: value for key, value in job.items() if key != "key"}

        async def anima(request):
            body = await request.json(); key = request.headers["Idempotency-Key"]
            job_id = str(uuid.uuid4())
            job = {"job_id": job_id, "state": "completed", "inputs": body["inputs"],
                   "requested_postprocess": body.get("postprocess", {}), "images": [{"image_id": "gen-source", "bytes": len(self.source),
                   "sha256": hashlib.sha256(self.source).hexdigest(), "media_type": "image/png"}], "error": None, "key": key}
            job["images"][0]["image_id"] = job_id + "-0"
            self.source_inputs = body["inputs"]
            self.source_generation_image_id = job["images"][0]["image_id"]
            self.jobs[key] = job
            return web.json_response(public(job), status=202)

        async def postprocess(request):
            body = await request.json(); key = request.headers["Idempotency-Key"]
            self.posts.append((request.match_info["id"], body, key))
            job_id = str(uuid.uuid4())
            job = {"job_id": job_id, "kind": "postprocess", "state": "completed", "source_image_id": request.match_info["id"],
                   "source_sha256": hashlib.sha256(self.source).hexdigest(), "source_media_type": "image/png", "inputs": self.source_inputs,
                   "requested_postprocess": body["postprocess"], "images": [{"image_id": job_id + "-0", "bytes": len(self.output),
                   "sha256": hashlib.sha256(self.output).hexdigest(), "media_type": "image/png"}], "error": None, "key": key}
            self.jobs[key] = job
            if self.lost_posts:
                self.lost_posts -= 1
                return web.Response(status=503, text="response lost")
            return web.json_response(public(job), status=202)

        async def by_key(request):
            job = self.jobs.get(request.headers["Idempotency-Key"])
            return web.json_response(public(job) if job else {"error": "missing"}, status=200 if job else 404)

        async def job(request):
            found = next((item for item in self.jobs.values() if item["job_id"] == request.match_info["id"]), None)
            return web.json_response(public(found) if found else {"error": "missing"}, status=200 if found else 404)

        async def image(request):
            value = self.source if request.match_info["id"] == self.source_generation_image_id else self.output
            return web.Response(body=value, content_type="image/png")

        app.add_routes([web.post("/v1/nodes/anima/jobs", anima), web.post("/v1/images/{id}/postprocess-jobs", postprocess),
                        web.get("/v1/jobs/by-key", by_key), web.get("/v1/jobs/{id}", job), web.get("/v1/images/{id}", image)])
        self.generation = TestServer(app); await self.generation.start_server()
        self.client = await self.new_client()
        self.source_inputs = dict(GEN_INPUTS, loras=[], positive_prompt="silver hair, white shirt, upper body", negative_prompt="")
        self.group, self.source_image_id = await self.create_source()

    async def asyncTearDown(self):
        await self.client.close(); await self.generation.close(); self.tmp.cleanup()

    async def new_client(self):
        client = TestClient(TestServer(create_app(Path(self.tmp.name) / "core.sqlite3", str(self.generation.make_url("/")), "core-token", "gen-token", .01)))
        await client.start_server()
        return client

    async def request(self, method, path, body=None, key=None):
        headers = {"Authorization": "Bearer core-token"}
        if key: headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        return response.status, await response.json()

    async def create_source(self):
        _, work = await self.request("POST", "/v1/works", {"name": "Source work"})
        _, character = await self.request("POST", "/v1/characters", {"name": "Source character", "parent_id": work["id"]})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "Source outfit", "parent_id": character["id"], "components": PARTS})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        _, task = await self.request("POST", "/v1/tasks", {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN_INPUTS, "postprocess": {}}, "source")
        for _ in range(200):
            _, task = await self.request("GET", "/v1/tasks/" + task["id"])
            if task["state"] == "generated":
                return group, task["images"][0]["id"]
            await asyncio.sleep(.01)
        self.fail(task)

    async def wait(self, job_id):
        for _ in range(200):
            _, job = await self.request("GET", "/v1/postprocess-jobs/" + job_id)
            if job["state"] in {"completed", "failed", "cancelled"}: return job
            await asyncio.sleep(.01)
        self.fail(job)

    async def image_bytes(self, path):
        response = await self.client.get(path, headers={"Authorization": "Bearer core-token"})
        return response.status, await response.read()

    async def test_metadata_group_queue_and_content_boundary(self):
        _, original = await self.request("GET", "/v1/images/" + self.source_image_id)
        _, group_before = await self.request("GET", "/v1/groups/" + self.group["id"])
        body = {"postprocess": {"encode": {"webp_enabled": False}}}
        status, accepted = await self.request("POST", f"/v1/images/{self.source_image_id}/postprocess-jobs", body, "post")
        self.assertEqual(status, 202, accepted)
        _, queue = await self.request("GET", "/v1/queue?limit=100")
        self.assertIn(("postprocess", accepted["id"]), {(item["kind"], item["id"]) for item in queue["items"]})
        job = await self.wait(accepted["id"])
        self.assertEqual((job["source_image_id"], job["state"], job["source_sha256"]), (self.source_image_id, "completed", original["sha256"]))
        self.assertEqual(job["requested_postprocess"], body["postprocess"])
        self.assertRegex(job["output_name"], r"^AtelierX/postprocess/\d{4}-\d{2}-\d{2}/" + self.source_image_id[:8] + "$")
        self.assertEqual(self.posts[-1][1], {"postprocess": body["postprocess"], "output_name": job["output_name"]})
        status, duplicate = await self.request("POST", f"/v1/images/{self.source_image_id}/postprocess-jobs", body, "post")
        self.assertEqual((status, duplicate["id"]), (200, job["id"]))
        status, listed = await self.request("GET", f"/v1/postprocess-jobs?source_image_id={self.source_image_id}")
        self.assertEqual((status, listed["total"], listed["items"][0]["id"]), (200, 1, job["id"]))
        image = job["images"][0]
        status, content = await self.image_bytes(image["content_url"])
        self.assertEqual((status, hashlib.sha256(content).hexdigest()), (200, image["sha256"]))
        self.output = b"x" * len(self.output)
        self.assertEqual((await self.image_bytes(image["content_url"]))[0], 502)
        self.output = b"x" * (2 * image["bytes"])
        self.assertEqual((await self.image_bytes(image["content_url"]))[0], 502)
        self.client.server.app[CORE].generation_url = "http://127.0.0.1:9"
        response = await self.client.get(image["content_url"], headers={"Authorization": "Bearer core-token"})
        self.assertEqual((response.status, (await response.json())["error"]["code"]),
                         (409, "CORE_GENERATION_ENDPOINT_CHANGED"))
        _, group_after = await self.request("GET", "/v1/groups/" + self.group["id"])
        _, original_after = await self.request("GET", "/v1/images/" + self.source_image_id)
        self.assertEqual((group_after, original_after), (group_before, original))

    async def test_source_endpoint_change_is_rejected_before_post(self):
        core = self.client.server.app[CORE]
        core.generation_url = "http://127.0.0.1:9"
        status, error = await self.request("POST", f"/v1/images/{self.source_image_id}/postprocess-jobs", {"postprocess": {"encode": {}}}, "wrong-endpoint")
        self.assertEqual((status, error["error"]["code"], self.posts), (409, "CORE_GENERATION_ENDPOINT_CHANGED", []))

    async def test_preset_snapshot_is_immutable_after_update_and_restart(self):
        status, preset = await self.request("POST", "/v1/presets/postprocess", {"name": "Encode old", "settings": {"encode": {"webp_enabled": False}}})
        self.assertEqual(status, 201)
        body = {"preset": {"id": preset["id"], "revision": preset["revision"]}}
        _, accepted = await self.request("POST", f"/v1/images/{self.source_image_id}/postprocess-jobs", body, "preset-key")
        job = await self.wait(accepted["id"])
        self.assertEqual(job["postprocess"]["encode"]["webp_enabled"], False)
        status, updated = await self.request("PATCH", "/v1/presets/postprocess/" + preset["id"], {"revision": preset["revision"], "settings": {"encode": {"webp_enabled": True}}})
        self.assertEqual((status, updated["revision"]), (200, preset["revision"] + 1))
        status, retry = await self.request("POST", f"/v1/images/{self.source_image_id}/postprocess-jobs", body, "preset-key")
        self.assertEqual((status, retry["id"], retry["postprocess"]["encode"]["webp_enabled"]), (200, job["id"], False))
        await self.client.close(); self.client = await self.new_client()
        _, restored = await self.request("GET", "/v1/postprocess-jobs/" + job["id"])
        self.assertEqual(restored, job)

    async def test_response_loss_recovers_by_key_without_second_generation_post(self):
        self.lost_posts = 1
        _, accepted = await self.request("POST", f"/v1/images/{self.source_image_id}/postprocess-jobs", {"postprocess": {"encode": {}}}, "lost")
        job = await self.wait(accepted["id"])
        self.assertEqual(job["state"], "completed")
        self.assertEqual((len(self.posts), self.lost_posts), (1, 0))


if __name__ == "__main__":
    unittest.main()
