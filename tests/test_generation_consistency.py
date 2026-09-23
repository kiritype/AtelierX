"""ADR-0027 P3/P7: Anima consistency method (anima-incontext-character)."""
import asyncio
import hashlib
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.generation import NODE, create_app
from atelierx.generation import consistency as consistency_methods

INPUT = {"diffusion_model": "anima", "text_encoder": "encoder", "vae": "vae", "positive_prompt": "character",
         "negative_prompt": "", "width": 512, "height": 512, "seed": 1, "steps": 24, "cfg": 4.5,
         "sampler": "euler", "scheduler": "normal"}

CONSISTENCY_NODES = ("AnimaRefEncode", "AnimaRefLatentBatch", "AnimaInContextApply")
LORA_NAME = "anima-incontext-character.safetensors"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfixture"
PNG_SHA256 = hashlib.sha256(PNG_BYTES).hexdigest()


def anima_schema(loras=(LORA_NAME,)):
    required = {}
    for key, value in INPUT.items():
        if key in {"positive_prompt", "negative_prompt"}: required[key] = ["STRING", {}]
        elif type(value) is int: required[key] = ["INT", {"min": 0, "max": 2 ** 64 - 1}]
        elif type(value) is float: required[key] = ["FLOAT", {"min": 0, "max": 20}]
        else: required[key] = [[value], {}]
    return {"input": {"required": required, "optional": {
        "lora_stack": ["STRING", {"atelierx_lora_stack": {"options": list(loras)}}]}}}


class ConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.posts, self.history, self.pending, self.uploads = [], {}, [], []
        self.schemas = {NODE: anima_schema(), "SaveImage": {}, "LoadImage": {},
                         "AnimaRefEncode": {}, "AnimaRefLatentBatch": {}, "AnimaInContextApply": {}}
        app = web.Application()

        async def info(request):
            key = request.match_info["name"]
            return web.json_response({key: self.schemas[key]} if key in self.schemas else {})

        async def queue(request):
            return web.json_response({"queue_running": [], "queue_pending": self.pending})

        async def prompt(request):
            value = await request.json()
            self.posts.append(value)
            self.pending = [[0, value["prompt_id"]]]
            return web.json_response({"prompt_id": value["prompt_id"]})

        async def history(request):
            return web.json_response(self.history)

        async def view(request):
            return web.Response(body=PNG_BYTES)

        async def upload(request):
            form = await request.post()
            self.uploads.append(form["image"].filename)
            return web.json_response({"name": form["image"].filename, "subfolder": "", "type": "input"})

        app.add_routes([web.get("/object_info/{name}", info), web.get("/queue", queue), web.post("/prompt", prompt),
                         web.get("/history/{id}", history), web.get("/view", view), web.post("/upload/image", upload)])
        self.comfy = TestServer(app)
        await self.comfy.start_server()
        self.client = TestClient(TestServer(create_app(self.temp.name, str(self.comfy.make_url("/")), "token", .01)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.comfy.close()
        self.temp.cleanup()

    def headers(self, key="post"):
        return {"Authorization": "Bearer token", "Idempotency-Key": key}

    async def state(self, identifier, expected):
        for _ in range(100):
            item = await (await self.client.get(f"/v1/jobs/{identifier}", headers=self.headers())).json()
            if item["state"] == expected:
                return item
            await asyncio.sleep(.01)
        self.fail(item)

    async def make_stored_image(self, key):
        """Submit and complete a plain job so its output becomes a Generation-stored image."""
        response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": INPUT}, headers=self.headers(key))
        job = await response.json()
        await self.state(job["job_id"], "submitted")
        self.pending = []
        self.history[job["job_id"]] = {"status": {"completed": True}, "outputs": {"2": {"images": [
            {"filename": f"{key}.png", "type": "output", "subfolder": ""}]}}}
        done = await self.state(job["job_id"], "completed")
        return done["images"][0]["image_id"], done["images"][0]["sha256"]

    def consistency_payload(self, full_id, full_sha, face_id, face_sha, **params):
        return {"method": "anima-incontext-character",
                "params": {"strength": 1.0, "end_percent": 0.5, "suppress_reference_background": True, **params},
                "references": [{"role": "full", "image_id": full_id, "sha256": full_sha},
                                {"role": "face", "image_id": face_id, "sha256": face_sha}]}

    async def test_resources_lists_availability_and_param_ranges(self):
        response = await self.client.get("/v1/resources", headers=self.headers())
        methods = (await response.json())["consistency_methods"]
        self.assertEqual(len(methods), 1)
        entry = methods[0]
        self.assertEqual(entry["id"], "anima-incontext-character")
        self.assertEqual(entry["families"], ["anima"])
        self.assertTrue(entry["available"])
        self.assertNotIn("unavailable_reason", entry)
        self.assertEqual(entry["params"]["strength"], {"type": "number", "default": 1.0, "min": 0.5, "max": 1.5})
        self.assertEqual(entry["params"]["end_percent"],
                          {"type": "number", "default": 0.5, "min": 0.3, "max": 1.0, "warn_below": 0.5})
        self.assertEqual(entry["params"]["suppress_reference_background"], {"type": "boolean", "default": True})

    async def test_resources_reports_unavailable_when_nodes_or_lora_missing(self):
        del self.schemas["AnimaRefEncode"]
        response = await self.client.get("/v1/resources", headers=self.headers())
        entry = (await response.json())["consistency_methods"][0]
        self.assertFalse(entry["available"])
        self.assertIn("AnimaRefEncode", entry["unavailable_reason"])
        self.schemas["AnimaRefEncode"] = {}
        self.schemas[NODE] = anima_schema(loras=())
        response = await self.client.get("/v1/resources", headers=self.headers())
        entry = (await response.json())["consistency_methods"][0]
        self.assertFalse(entry["available"])
        self.assertIn(LORA_NAME, entry["unavailable_reason"])

    async def test_backward_compatible_without_consistency_graph_is_unchanged(self):
        response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": INPUT}, headers=self.headers("plain"))
        job = await response.json()
        self.assertIsNone(job["consistency"])
        self.assertIsNone(job["requested_consistency"])
        await self.state(job["job_id"], "submitted")
        graph = self.posts[0]["prompt"]
        self.assertEqual(set(graph), {"1", "2"})
        self.assertNotIn("reference_full", graph["1"]["inputs"])
        self.assertNotIn("consistency", graph["1"]["inputs"])

    async def test_submit_with_consistency_wires_reference_graph_and_uploads(self):
        full_id, full_sha = await self.make_stored_image("full-src")
        face_id, face_sha = await self.make_stored_image("face-src")
        payload = {"inputs": dict(INPUT, consistency=self.consistency_payload(full_id, full_sha, face_id, face_sha, strength=1.2, end_percent=0.6))}
        response = await self.client.post("/v1/nodes/anima/jobs", json=payload, headers=self.headers("with-ref"))
        self.assertEqual(response.status, 202)
        job = await response.json()
        self.assertEqual(job["consistency"]["method"], "anima-incontext-character")
        self.assertEqual(job["consistency"]["params"], {"strength": 1.2, "end_percent": 0.6, "suppress_reference_background": True})
        await self.state(job["job_id"], "submitted")
        graph = self.posts[-1]["prompt"]
        self.assertEqual(graph["1"]["inputs"]["reference_full"], ["ref-full", 0])
        self.assertEqual(graph["1"]["inputs"]["reference_face"], ["ref-face", 0])
        self.assertEqual(graph["1"]["inputs"]["consistency"],
                          '{"method":"anima-incontext-character","params":{"end_percent":0.6,"strength":1.2}}')
        self.assertEqual(graph["ref-full"]["class_type"], "LoadImage")
        self.assertEqual(graph["ref-face"]["class_type"], "LoadImage")
        self.assertTrue(graph["ref-full"]["inputs"]["image"])
        self.assertTrue(graph["ref-face"]["inputs"]["image"])
        self.assertEqual(len(self.uploads), 2)

    async def test_unknown_or_cross_server_reference_image_is_rejected(self):
        full_id, full_sha = await self.make_stored_image("full-src")
        payload = {"inputs": dict(INPUT, consistency=self.consistency_payload("missing-image", full_sha, full_id, full_sha))}
        response = await self.client.post("/v1/nodes/anima/jobs", json=payload, headers=self.headers("missing-ref"))
        self.assertEqual(response.status, 404)
        self.assertEqual((await response.json())["error"]["code"], "GEN_IMAGE_NOT_FOUND")

    async def test_reference_sha256_mismatch_is_rejected_at_submit(self):
        full_id, full_sha = await self.make_stored_image("full-src")
        face_id, face_sha = await self.make_stored_image("face-src")
        payload = {"inputs": dict(INPUT, consistency=self.consistency_payload(full_id, "0" * 64, face_id, face_sha))}
        response = await self.client.post("/v1/nodes/anima/jobs", json=payload, headers=self.headers("bad-sha"))
        self.assertEqual(response.status, 422)
        self.assertEqual((await response.json())["error"]["code"], "GEN_IMAGE_INTEGRITY")

    async def test_malformed_consistency_shapes_are_rejected(self):
        full_id, full_sha = await self.make_stored_image("full-src")
        face_id, face_sha = await self.make_stored_image("face-src")
        bad_method = {"inputs": dict(INPUT, consistency={"method": "other", "references": []})}
        response = await self.client.post("/v1/nodes/anima/jobs", json=bad_method, headers=self.headers("bad-method"))
        self.assertEqual(response.status, 400)

        only_full = self.consistency_payload(full_id, full_sha, face_id, face_sha)
        only_full["references"] = [only_full["references"][0]]
        response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": dict(INPUT, consistency=only_full)},
                                          headers=self.headers("only-full"))
        self.assertEqual(response.status, 400)

        out_of_range = self.consistency_payload(full_id, full_sha, face_id, face_sha, strength=5.0)
        response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": dict(INPUT, consistency=out_of_range)},
                                          headers=self.headers("out-of-range"))
        self.assertEqual(response.status, 400)

        bad_bg = self.consistency_payload(full_id, full_sha, face_id, face_sha, suppress_reference_background="yes")
        response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": dict(INPUT, consistency=bad_bg)},
                                          headers=self.headers("bad-bg"))
        self.assertEqual(response.status, 400)

    async def test_node_unavailable_when_incontext_nodes_not_registered(self):
        del self.schemas["AnimaInContextApply"]
        full_id, full_sha = await self.make_stored_image("full-src")
        face_id, face_sha = await self.make_stored_image("face-src")
        payload = {"inputs": dict(INPUT, consistency=self.consistency_payload(full_id, full_sha, face_id, face_sha))}
        response = await self.client.post("/v1/nodes/anima/jobs", json=payload, headers=self.headers("node-missing"))
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"]["code"], "GEN_NODE_UNAVAILABLE")

    async def test_lora_unavailable_is_rejected(self):
        self.schemas[NODE] = anima_schema(loras=())
        full_id, full_sha = await self.make_stored_image("full-src")
        face_id, face_sha = await self.make_stored_image("face-src")
        payload = {"inputs": dict(INPUT, consistency=self.consistency_payload(full_id, full_sha, face_id, face_sha))}
        response = await self.client.post("/v1/nodes/anima/jobs", json=payload, headers=self.headers("lora-missing"))
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"]["code"], "GEN_NODE_UNAVAILABLE")

    async def test_idempotent_resubmit_with_same_consistency_returns_same_job(self):
        full_id, full_sha = await self.make_stored_image("full-src")
        face_id, face_sha = await self.make_stored_image("face-src")
        payload = {"inputs": dict(INPUT, consistency=self.consistency_payload(full_id, full_sha, face_id, face_sha))}
        first = await self.client.post("/v1/nodes/anima/jobs", json=payload, headers=self.headers("idem"))
        second = await self.client.post("/v1/nodes/anima/jobs", json=payload, headers=self.headers("idem"))
        self.assertEqual(second.status, 200)
        self.assertEqual((await first.json())["job_id"], (await second.json())["job_id"])

    def test_pure_registry_defaults_and_missing_family(self):
        info = {NODE: anima_schema()} | {name: {} for name in CONSISTENCY_NODES}
        self.assertIsNone(consistency_methods.validate_consistency(None, info))
        entries = consistency_methods.resources_entry(info, family="sdxl")
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
