"""Recovery boundaries that must not create a second backend execution."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError
from atelierx.generation import Generation, SERVICE, create_app


class BackendRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Generation(self.temp.name, "http://comfy.invalid", "token")
        self.image_id = "source-0"
        self.path = self.service.images_dir / f"{self.image_id}.png"
        self.path.write_bytes(b"original-image")
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.source = {"job_id": "source", "idempotency_key": "source-key", "images": [{"image_id": self.image_id, "sha256": self.digest, "media_type": "image/png"}], "inputs": {"seed": 1}, "node_inputs": {"lora_stack": "[]"}}
        self.service.jobs["source"] = self.source

    def tearDown(self):
        self.service.owner.close(); self.temp.cleanup()

    def test_image_id_cannot_be_replaced_with_a_path_or_unknown_id(self):
        for value in ("C:/input.png", "../source-0", "unknown"):
            with self.subTest(value=value), self.assertRaises(ApiError) as caught:
                self.service.image_source(value)
            self.assertEqual(caught.exception.code, "GEN_IMAGE_NOT_FOUND")

    def test_independent_postprocess_requires_preserved_anima_context(self):
        self.source.pop("node_inputs")
        source, _, _ = self.service.image_source(self.image_id)
        self.assertNotIn("node_inputs", source)
        # submit_independent rejects this before it can upload or submit a prompt.

    def test_completed_job_cancel_race_discards_late_outputs(self):
        job = {"job_id": "late", "state": "completed", "cancel_requested": True, "images": [{"image_id": "late-0"}], "error": None}
        self.service.save(job)
        self.assertEqual(job["state"], "cancelled")
        self.assertEqual(job["images"], [])

    def test_restart_keeps_existing_idempotency_key_without_new_execution(self):
        job = {"job_id": "known", "idempotency_key": "same-key", "state": "submitted", "images": [], "fingerprint": "f"}
        self.service.save(job); self.service.owner.close()
        restarted = Generation(self.temp.name, "http://comfy.invalid", "token")
        try:
            self.assertEqual(restarted.keys["same-key"], "known")
            self.assertEqual(restarted.jobs["known"]["state"], "submitted")
        finally:
            restarted.owner.close()

    def test_independent_source_mutation_is_visible_to_preupload_integrity_guard(self):
        """Lookup defers byte checking so retry lookup remains available."""
        self.path.write_bytes(b"mutated-image")
        # Lookup remains metadata-only so completed-key lookup stays available;
        # Generation rechecks this hash immediately before ComfyUI upload.
        _, image, path = self.service.image_source(self.image_id)
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), image["sha256"])


class IndependentPostprocessRestRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.uploads=[]; self.posts=[]; self.busy=True; self.pending=[]; self.lose_prompt_response=False
        comfy=web.Application()
        async def info(request):
            name=request.match_info["name"]
            schemas={"AtelierXAnimaGenerate": {"input":{"required":{}}}, "SaveImage":{}, "LoadImage":{}, "AtelierXEncodeSave":{}}
            return web.json_response({name: schemas[name]} if name in schemas else {})
        async def upload(request):
            fields=await request.post(); self.uploads.append(fields)
            return web.json_response({"name":fields["image"].filename,"subfolder":"","type":"input"})
        async def prompt(request):
            self.posts.append(await request.json()); self.pending=[[0,self.posts[-1]["prompt_id"]]]
            if self.lose_prompt_response: return web.Response(text="lost")
            return web.json_response({"prompt_id":self.posts[-1]["prompt_id"]})
        async def queue(request): return web.json_response({"queue_running":[[0,"other"]] if self.busy else [],"queue_pending":self.pending})
        async def history(request): return web.json_response({})
        comfy.add_routes([web.get("/object_info/{name}",info),web.post("/upload/image",upload),web.post("/prompt",prompt),web.get("/queue",queue),web.get("/history/{id}",history)])
        self.comfy=TestServer(comfy); await self.comfy.start_server()
        self.client=TestClient(TestServer(create_app(self.temp.name,str(self.comfy.make_url("/")),"token",.01))); await self.client.start_server()
        self.service=self.client.server.app[SERVICE]
        path=self.service.images_dir / "saved-0.png"; path.write_bytes(b"saved")
        self.service.jobs["saved"]={"job_id":"saved","idempotency_key":"saved-key","state":"completed","images":[{"image_id":"saved-0","sha256":hashlib.sha256(b"saved").hexdigest(),"media_type":"image/png"}],"inputs":{},"node_inputs":{"lora_stack":"[]"}}

    async def asyncTearDown(self): await self.client.close(); await self.comfy.close(); self.temp.cleanup()
    def headers(self,key): return {"Authorization":"Bearer token","Idempotency-Key":key}
    async def state(self, job_id, expected):
        for _ in range(100):
            value=await (await self.client.get("/v1/jobs/"+job_id,headers=self.headers("read"))).json()
            if value["state"]==expected: return value
            await __import__("asyncio").sleep(.01)
        self.fail(value)

    async def test_rest_accepts_saved_id_and_context_missing_is_explicit(self):
        response=await self.client.post("/v1/images/saved-0/postprocess-jobs",json={"postprocess":{"encode":{"webp_enabled":False}}},headers=self.headers("ok"))
        self.assertEqual(response.status,202, await response.text())
        duplicate=await self.client.post("/v1/images/saved-0/postprocess-jobs",json={"postprocess":{"encode":{"webp_enabled":False}}},headers=self.headers("ok"))
        self.assertEqual(duplicate.status,200)
        self.service.jobs["saved"].pop("node_inputs")
        missing=await self.client.post("/v1/images/saved-0/postprocess-jobs",json={"postprocess":{"encode":{}}},headers=self.headers("missing"))
        self.assertEqual((missing.status,(await missing.json())["error"]["code"]),(409,"GEN_POSTPROCESS_CONTEXT_MISSING"))

    async def test_mutated_source_fails_before_upload_or_prompt(self):
        response=await self.client.post("/v1/images/saved-0/postprocess-jobs",json={"postprocess":{"encode":{}}},headers=self.headers("mutate")); job=await response.json()
        (self.service.images_dir / "saved-0.png").write_bytes(b"changed")
        self.busy=False
        failed=await self.state(job["job_id"],"failed")
        self.assertEqual(failed["error"]["code"],"GEN_IMAGE_INTEGRITY")
        self.assertEqual((self.uploads,self.posts),([],[]))

    async def test_valid_source_uploads_and_uses_fixed_loadimage_graph(self):
        self.busy=False
        response=await self.client.post("/v1/images/saved-0/postprocess-jobs",json={"postprocess":{"encode":{}}},headers=self.headers("valid")); job=await response.json()
        await self.state(job["job_id"],"submitted")
        self.assertEqual((len(self.uploads),len(self.posts)),(1,1))
        self.assertEqual(self.posts[0]["prompt"]["1"],{"class_type":"LoadImage","inputs":{"image":self.uploads[0]["image"].filename}})

    async def test_lost_prompt_response_tracks_known_id_without_second_post(self):
        self.lose_prompt_response=True; self.busy=False
        response=await self.client.post("/v1/images/saved-0/postprocess-jobs",json={"postprocess":{"encode":{}}},headers=self.headers("lost")); job=await response.json()
        await self.state(job["job_id"],"submitted"); await __import__("asyncio").sleep(.05)
        self.assertEqual(len(self.posts),1)

    async def test_cancel_before_execution_never_uploads_or_posts(self):
        response=await self.client.post("/v1/images/saved-0/postprocess-jobs",json={"postprocess":{"encode":{}}},headers=self.headers("cancel")); job=await response.json()
        cancel=await self.client.post("/v1/jobs/"+job["job_id"]+"/cancel",headers=self.headers("read"))
        self.assertEqual((await cancel.json())["state"],"cancelled")
        self.busy=False; await __import__("asyncio").sleep(.05)
        self.assertEqual((self.uploads,self.posts),([],[]))


if __name__ == "__main__":
    unittest.main()
