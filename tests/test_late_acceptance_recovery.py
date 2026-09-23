"""TCP regressions for dispatch acceptance windows; no local GPU or provider."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from atelierx.common import ApiError
from atelierx.core.validation import CoreValidation
from atelierx.generation import NODE, create_app as generation_app
from atelierx.gpu import permission


TOKEN = "late-acceptance-token"
INPUT = {"diffusion_model": "anima", "text_encoder": "encoder", "vae": "vae",
         "positive_prompt": "adult character", "negative_prompt": "", "width": 512,
         "height": 512, "seed": 1, "steps": 24, "cfg": 4.5,
         "sampler": "euler", "scheduler": "normal"}


def anima_schema():
    required = {}
    for name, value in INPUT.items():
        if name in {"positive_prompt", "negative_prompt"}:
            required[name] = ["STRING", {}]
        elif type(value) is int:
            required[name] = ["INT", {"min": 0, "max": 2**64 - 1}]
        elif type(value) is float:
            required[name] = ["FLOAT", {"min": 0, "max": 20}]
        else:
            required[name] = ["COMBO", {"options": [value]}]
    return {"input": {"required": required, "optional": {
        "lora_stack": ["STRING", {"atelierx_lora_stack": {"options": []}}]}}}


class LateAcceptanceRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.anima_schema_requests = 0
        comfy = web.Application()

        async def info(request):
            name = request.match_info["name"]
            if name == NODE:
                self.anima_schema_requests += 1
                self.entered.set()
                await self.release.wait()
                return web.json_response({NODE: anima_schema()})
            return web.json_response({name: {}})

        comfy.router.add_get("/object_info/{name}", info)
        async def queue(request):
            # Keep the worker from reaching /prompt; this test only exercises
            # durable acceptance and the recovery lookup boundary.
            return web.json_response({"queue_running": [[0, "external"]], "queue_pending": []})
        comfy.router.add_get("/queue", queue)
        self.comfy = TestServer(comfy)
        await self.comfy.start_server()
        self.generation = TestServer(generation_app(Path(self.tmp.name) / "generation",
                                                    str(self.comfy.make_url("/")), TOKEN, .01))
        await self.generation.start_server()
        self.session = aiohttp.ClientSession()

    async def asyncTearDown(self):
        self.release.set()
        await self.session.close()
        await self.generation.close()
        await self.comfy.close()
        self.tmp.cleanup()

    def headers(self, key="late"):
        return {"Authorization": "Bearer " + TOKEN, "Idempotency-Key": key}

    async def test_by_key_waits_for_late_generation_submission_to_persist(self):
        """A recovery lookup cannot see a false 404 while POST owns submit lock."""
        url = str(self.generation.make_url("/"))[:-1]
        post = asyncio.create_task(self.session.post(url + "/v1/nodes/anima/jobs",
                                                     headers=self.headers(), json={"inputs": INPUT}))
        await asyncio.wait_for(self.entered.wait(), 1)
        lookup = asyncio.create_task(self.session.get(url + "/v1/jobs/by-key", headers=self.headers()))
        await asyncio.sleep(.03)
        self.assertFalse(lookup.done(), "lookup escaped the submit lock with a transient result")
        self.release.set()
        response = await post
        self.assertEqual(response.status, 202)
        submitted = await response.json()
        response = await lookup
        self.assertEqual(response.status, 200)
        job = await response.json()
        self.assertEqual(job["state"], "queued")
        self.assertEqual(job["job_id"], submitted["job_id"])
        async with self.session.post(url + "/v1/nodes/anima/jobs", headers=self.headers(), json={"inputs": INPUT}) as repeated:
            self.assertEqual(repeated.status, 200)
            self.assertEqual((await repeated.json())["job_id"], submitted["job_id"])
        self.assertEqual(self.anima_schema_requests, 1)

    async def test_validation_gateway_503_is_retryable_but_validation_503_is_explicit(self):
        app = web.Application()
        state = {"validation_error": False}

        async def endpoint(request):
            if state["validation_error"]:
                return web.json_response({"error": {"code": "VAL_PROVIDER_UNAVAILABLE", "message": "provider down"}}, status=503)
            return web.Response(status=503)

        app.router.add_get("/probe", endpoint)
        server = TestServer(app)
        await server.start_server()
        try:
            probe = SimpleNamespace(core=SimpleNamespace(session=self.session), token=TOKEN,
                                    url=str(server.make_url("/"))[:-1])
            with self.assertRaisesRegex(ApiError, "temporarily unavailable") as raised:
                await CoreValidation.call(probe, "GET", "/probe")
            self.assertEqual(raised.exception.code, "CORE_VALIDATION_UNAVAILABLE")
            state["validation_error"] = True
            with self.assertRaises(ApiError) as raised:
                await CoreValidation.call(probe, "GET", "/probe")
            self.assertEqual(raised.exception.code, "VAL_PROVIDER_UNAVAILABLE")
        finally:
            await server.close()

    async def test_numeric_release_ack_cannot_clear_durable_gpu_request(self):
        app = web.Application()
        async def numeric_release(request):
            return web.json_response({"released": 1})
        app.router.add_post("/v1/gpu/release", numeric_release)
        server = TestServer(app)
        await server.start_server()
        saved = []
        service = SimpleNamespace(coordinator_url=str(server.make_url("/")), token=TOKEN,
                                  session=self.session, save=lambda job: saved.append(dict(job)))
        job = {"job_id": "release", "gpu_requested": True}
        try:
            self.assertFalse(await permission(service, job, "generation", release=True))
            self.assertTrue(job["gpu_requested"])
            self.assertEqual(saved, [])
        finally:
            await server.close()
