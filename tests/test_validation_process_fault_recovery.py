"""Validation subprocess recovery with a deliberately late mock VLM reply.

No configured local provider, GPU service, or pilot data is read.  The child
process receives a temporary data directory and talks only to this test's TCP
mock VLM.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

import aiohttp
from aiohttp import web


TOKEN = "validation-process-fault-token"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgZGIGAAAOAAfXb+R4AAAAAElFTkSuQmCC")
SINGLE = {"profile_id": "single", "revision": 1, "output_conditions": False,
          "positive_prompt": True, "negative_prompt": False, "body_parts": [],
          "metadata": False, "consistency": False}
GROUP = {"profile_id": "group", "revision": 1, "consistency": True}
PROVIDER = {"provider_id": "vision", "revision": 1, "model": "mock-vlm", "timeout_seconds": 10}


async def start(app):
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
    return runner, "http://127.0.0.1:" + str(runner.addresses[0][1])


def free_port():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); value = sock.getsockname()[1]; sock.close()
    return value


class ValidationProcessFaultRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.calls = 0
        self.accepted, self.release = asyncio.Event(), asyncio.Event()
        provider = web.Application()

        async def completion(request):
            self.calls += 1; body = await request.json(); self.accepted.set()
            await self.release.wait()
            first_text = body["messages"][1]["content"][0]["text"]
            if first_text.startswith("Shared identity: "):
                identity = json.loads(first_text.split(": ", 1)[1])
                references = [json.loads(item["text"])["ref"] for item in body["messages"][1]["content"]
                              if item["type"] == "text" and item["text"].startswith('{"positive_prompt"')]
                verdict = {"assessments": [{"feature": feature, "status": "matched",
                                               "reference_observed": {ref: "mock visual observation" for ref in references[:-1]},
                                               "target_observed": "mock visual observation", "differences": [],
                                               "reference_refs": references[:-1]} for feature in identity]}
            else:
                checks = json.loads(first_text.split(": ", 1)[1])
                verdict = {"assessments": [{"id": check["id"], "status": "matched",
                                            "observed": "mock visual observation", "location": "center"}
                                           for check in checks]}
            return web.json_response({"choices": [{"message": {"content": json.dumps(verdict)}}]})

        provider.router.add_post("/chat/completions", completion)
        self.provider_runner, self.provider_url = await start(provider)
        self.port = free_port(); self.data = Path(self.temp.name) / "validation"
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"providers": {"vision": {"url": self.provider_url, "api_key": "mock",
            "model": "mock-vlm", "revision": 1, "timeout_seconds": 10}}, "generation_sources": {},
            "profiles": {"single": SINGLE, "group": GROUP}}), encoding="utf-8")
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2))
        self.process = None
        await self.start_process()

    async def asyncTearDown(self):
        self.release.set()
        if self.process and self.process.returncode is None:
            self.process.kill(); await self.process.wait()
        await self.http.close(); await self.provider_runner.cleanup(); self.temp.cleanup()

    async def start_process(self):
        environment = dict(os.environ, ATELIERX_SERVICE_TOKEN=TOKEN)
        self.process = await asyncio.create_subprocess_exec(sys.executable, "-m", "atelierx.validation", "--port", str(self.port),
            "--data-dir", str(self.data), "--config", str(self.config), env=environment,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        self.url = "http://127.0.0.1:" + str(self.port)
        for _ in range(300):
            try:
                async with self.http.get(self.url + "/health", headers=self.headers()) as response:
                    if response.status == 200: return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(.01)
        self.fail("Validation subprocess did not start")

    async def assert_validation_port_closed(self):
        """Verify that kill stopped the actual HTTP-serving subprocess tree."""
        for _ in range(100):
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.port), .1)
            except (OSError, asyncio.TimeoutError):
                return
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(.01)
        self.fail("killed Validation subprocess still accepts connections on its test port")

    def headers(self, key=None):
        result = {"Authorization": "Bearer " + TOKEN}
        if key: result["Idempotency-Key"] = key
        return result

    async def upload(self):
        async with self.http.post(self.url + "/v1/uploads", data=PNG, headers=self.headers()) as response:
            self.assertEqual(response.status, 201, await response.text())
            return await response.json()

    @staticmethod
    def image(upload, ref):
        return {"ref": ref, "source": {"type": "upload", "upload_id": upload["upload_id"], "sha256": upload["sha256"]},
                "positive_prompt": "blue eyes", "negative_prompt": "", "negative_sources": {"global": "", "character": ""}}

    async def submit(self, kind):
        upload = await self.upload()
        if kind == "single":
            body = {"image": self.image(upload, "single"), "generation_attempt_id": "attempt", "profile": SINGLE,
                    "provider": PROVIDER, "expected_output": None, "generation_settings": None}
            endpoint = "/v1/validations/single"
        else:
            body = {"group_id": "group", "reference_revision": 1, "representative": self.image(upload, "representative"),
                    "auxiliaries": [], "targets": [self.image(upload, "target")], "identity": {"appearance": "blue eyes"},
                    "profile": GROUP, "provider": PROVIDER}
            endpoint = "/v1/validations/group"
        async with self.http.post(self.url + endpoint, json=body, headers=self.headers(kind + "-late")) as response:
            self.assertEqual(response.status, 202, await response.text())
            return await response.json()

    async def await_acceptance_unknown(self, job_id):
        for _ in range(300):
            try:
                async with self.http.get(self.url + "/v1/validation-jobs/" + job_id, headers=self.headers()) as response:
                    if response.status == 200:
                        job = await response.json()
                        if job["state"] == "failed": return job
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(.01)
        self.fail("restarted Validation job did not settle")

    async def await_cancelled_with_late_result(self, job_id):
        for _ in range(300):
            try:
                async with self.http.get(self.url + "/v1/validation-jobs/" + job_id, headers=self.headers()) as response:
                    if response.status == 200:
                        job = await response.json()
                        if job["state"] == "cancelled" and "late_result" in job:
                            return job
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(.01)
        self.fail("cancelled Validation job did not discard late provider result")

    async def exercise_kill_during_provider(self, kind):
        job = await self.submit(kind)
        await asyncio.wait_for(self.accepted.wait(), timeout=2)
        self.process.kill(); await self.process.wait()
        await self.assert_validation_port_closed()
        await self.start_process()
        recovered = await self.await_acceptance_unknown(job["job_id"])
        self.assertEqual((recovered["outcome"], recovered["error"]["code"], self.calls),
                         ("error", "VAL_PROVIDER_ACCEPTANCE_UNKNOWN", 1))
        self.release.set(); await asyncio.sleep(.05)
        self.assertEqual(self.calls, 1)

    async def exercise_cancel_during_provider(self, kind):
        job = await self.submit(kind)
        await asyncio.wait_for(self.accepted.wait(), timeout=2)
        async with self.http.post(self.url + "/v1/validation-jobs/" + job["job_id"] + "/cancel", headers=self.headers()) as response:
            self.assertEqual(response.status, 202, await response.text())
        self.release.set()
        cancelled = await self.await_cancelled_with_late_result(job["job_id"])
        self.assertEqual(cancelled["outcome"], None)
        self.assertEqual(cancelled["result"], None)
        self.assertEqual(cancelled["late_result"]["outcome"], "passed")
        self.assertEqual(self.calls, 1)

    async def test_single_kill_during_late_provider_reply_is_terminal_without_resend(self):
        await self.exercise_kill_during_provider("single")

    async def test_group_kill_during_late_provider_reply_is_terminal_without_resend(self):
        await self.exercise_kill_during_provider("group")

    async def test_single_cancel_discards_late_provider_result_over_tcp(self):
        await self.exercise_cancel_during_provider("single")

    async def test_group_cancel_discards_late_provider_result_over_tcp(self):
        await self.exercise_cancel_during_provider("group")
