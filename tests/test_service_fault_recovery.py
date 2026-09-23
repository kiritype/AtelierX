"""TCP recovery probes using isolated SQLite files and mock remote services.

These tests deliberately start and stop aiohttp runners instead of using a
``TestClient``.  They exercise the same HTTP boundary a separately launched
Core process uses, while keeping ComfyUI, LM Studio and the pilot data out of
the test.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

from atelierx.core import create_app as core_app
from _reference_fixture import confirm_reference_set


TOKEN = "service-fault-test-token"


async def start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, "http://127.0.0.1:" + str(runner.addresses[0][1])


class MockGeneration:
    """Accepts once, then lets Core recover through GET-by-key."""

    def __init__(self):
        self.posts, self.jobs, self.keys = 0, {}, {}
        self.lose_next_reply = False
        self.disconnect_next_reply = False
        self.delay_next_reply = False
        self.accepted = asyncio.Event()
        self.release_reply = asyncio.Event()

    def app(self):
        app = web.Application()

        async def submit(request):
            self.posts += 1
            key = request.headers["Idempotency-Key"]
            body = await request.json()
            job_id = self.keys.setdefault(key, str(uuid.uuid4()))
            image_id = job_id + "-0"
            self.jobs[job_id] = {
                "job_id": job_id, "state": "completed", "execution_started": True,
                "inputs": body["inputs"], "requested_postprocess": body.get("postprocess", {}),
                "images": [{"image_id": image_id, "sha256": hashlib.sha256(b"mock-image").hexdigest(),
                            "bytes": 10, "media_type": "image/png"}],
            }
            self.accepted.set()
            if self.delay_next_reply:
                self.delay_next_reply = False
                await self.release_reply.wait()
            if self.lose_next_reply:
                self.lose_next_reply = False
                # The remote service accepted the request, but its reply was lost.
                return web.Response(status=503)
            if self.disconnect_next_reply:
                self.disconnect_next_reply = False
                # Close the TCP connection after accepting the durable request.
                # This models a response lost between separately running services.
                request.transport.close()
                return web.Response()
            return web.json_response(self.jobs[job_id], status=202)

        async def by_key(request):
            job_id = self.keys.get(request.headers.get("Idempotency-Key"))
            return web.json_response(self.jobs[job_id]) if job_id else web.Response(status=404)

        async def job(request):
            value = self.jobs.get(request.match_info["id"])
            return web.json_response(value) if value else web.Response(status=404)

        app.add_routes([web.post("/v1/nodes/anima/jobs", submit), web.get("/v1/jobs/by-key", by_key),
                        web.get("/v1/jobs/{id}", job)])
        return app


class ServiceFaultRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.generation = MockGeneration()
        self.generation_runner, self.generation_url = await start(self.generation.app())
        self.core_runner = self.core_url = None
        await self.start_core()
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2))
        self.group_id = await self.create_group()

    async def asyncTearDown(self):
        await self.http.close()
        if self.core_runner:
            await self.core_runner.cleanup()
        await self.generation_runner.cleanup()
        self.temp.cleanup()

    async def start_core(self):
        config = {"url": "http://127.0.0.1:9", "profiles": {}, "providers": {}}
        app = core_app(Path(self.temp.name) / "core.sqlite3", self.generation_url, TOKEN,
                       TOKEN, poll=.005, validation_config=config, validation_token=TOKEN)
        self.core_runner, self.core_url = await start(app)

    async def restart_core(self):
        await self.core_runner.cleanup()
        self.core_runner = self.core_url = None
        await self.start_core()

    def headers(self, key=None):
        value = {"Authorization": "Bearer " + TOKEN}
        if key:
            value["Idempotency-Key"] = key
        return value

    async def request(self, method, path, body=None, key=None):
        async with self.http.request(method, self.core_url + path, json=body, headers=self.headers(key)) as response:
            return response.status, await response.json()

    async def create_group(self):
        _, work = await self.request("POST", "/v1/works", {"name": "fault work"})
        _, character = await self.request("POST", "/v1/characters", {"name": "fault character", "parent_id": work["id"], "appearance_prompt": "blue eyes"})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "fault outfit", "parent_id": character["id"],
            "components": {"upper": "shirt", "lower": "boots", "accessories": ""}})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        self.outfit_id = outfit["id"]
        await confirm_reference_set(self.request, outfit["id"], {
            "diffusion_model": "mock", "text_encoder": "mock", "vae": "mock", "seed": 1,
            "steps": 2, "cfg": 1, "sampler": "euler", "scheduler": "normal"})
        self.generation.posts = 0
        return group["id"]

    def payload(self):
        return {"group_id": self.group_id, "framing": "upper_body", "generation_inputs": {
            "diffusion_model": "mock", "text_encoder": "mock", "vae": "mock", "seed": 1,
            "steps": 2, "cfg": 1, "sampler": "euler", "scheduler": "normal"}}

    async def wait_task(self, task_id):
        for _ in range(200):
            _, task = await self.request("GET", "/v1/tasks/" + task_id)
            if task["state"] in {"generated", "failed", "cancelled"}:
                return task
            await asyncio.sleep(.01)
        self.fail("task did not settle")

    async def assert_core_port_closed(self):
        """Ensure killing the launcher also stopped its HTTP-serving child."""
        for _ in range(100):
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", int(self.core_url.rsplit(":", 1)[1])), .1)
            except (OSError, asyncio.TimeoutError):
                return
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(.01)
        self.fail("killed Core subprocess still accepts connections on its test port")

    async def test_lost_generation_reply_and_core_restart_do_not_submit_twice(self):
        self.generation.lose_next_reply = True
        status, task = await self.request("POST", "/v1/tasks", self.payload(), "lost-generation")
        self.assertEqual(status, 202)
        # Let the persisted dispatch intent survive a real runner teardown.
        for _ in range(100):
            _, current = await self.request("GET", "/v1/tasks/" + task["id"])
            if current["state"] == "dispatching":
                break
            await asyncio.sleep(.005)
        self.assertEqual(current["state"], "dispatching")
        await self.restart_core()
        settled = await self.wait_task(task["id"])
        self.assertEqual((settled["state"], self.generation.posts), ("generated", 1))
        self.assertEqual(len(settled["images"]), 1)

    async def test_generation_tcp_disconnect_after_acceptance_recovers_by_key_once(self):
        self.generation.disconnect_next_reply = True
        status, task = await self.request("POST", "/v1/tasks", self.payload(), "generation-tcp-disconnect")
        self.assertEqual(status, 202)
        for _ in range(100):
            _, current = await self.request("GET", "/v1/tasks/" + task["id"])
            if current["state"] == "dispatching":
                break
            await asyncio.sleep(.005)
        self.assertEqual(current["state"], "dispatching")
        await self.restart_core()
        settled = await self.wait_task(task["id"])
        self.assertEqual((settled["state"], self.generation.posts), ("generated", 1))

    async def test_late_generation_reply_after_core_restart_is_recovered_by_key_once(self):
        self.generation.delay_next_reply = True
        _, task = await self.request("POST", "/v1/tasks", self.payload(), "late-generation")
        await asyncio.wait_for(self.generation.accepted.wait(), timeout=1)
        # The remote request is accepted but has no HTTP reply yet.  This is
        # distinct from a simple result-poll delay: dispatching is durable.
        await self.restart_core()
        self.generation.release_reply.set()
        settled = await self.wait_task(task["id"])
        self.assertEqual((settled["state"], self.generation.posts), ("generated", 1))

    async def test_os_process_kill_after_accepted_post_recovers_by_key_without_a_second_post(self):
        """A real Core subprocess is killed between POST acceptance and its reply.

        The mock already has the idempotency key when it sends 503.  Restarting
        the Core executable on the same database must GET that key; it must not
        issue another POST merely because the first reply was unavailable.
        """
        await self.core_runner.cleanup()
        self.core_runner = None
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
        db = Path(self.temp.name) / "core.sqlite3"
        environment = dict(os.environ, ATELIERX_SERVICE_TOKEN=TOKEN, ATELIERX_GENERATION_TOKEN=TOKEN)
        command = [sys.executable, "-m", "atelierx.core", "--port", str(port), "--db", str(db),
                   "--generation-url", self.generation_url]
        process = await asyncio.create_subprocess_exec(*command, env=environment,
                                                        stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL)
        self.core_url = "http://127.0.0.1:" + str(port)
        try:
            for _ in range(200):
                try:
                    status, _ = await self.request("GET", "/health")
                    if status == 200: break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(.01)
            else:
                self.fail("subprocess Core did not start")
            self.generation.lose_next_reply = True
            status, task = await self.request("POST", "/v1/tasks", self.payload(), "subprocess-lost")
            self.assertEqual(status, 202, task)
            for _ in range(200):
                if self.generation.posts == 1: break
                await asyncio.sleep(.01)
            self.assertEqual(self.generation.posts, 1)
            process.kill(); await process.wait()
            await self.assert_core_port_closed()
            process = await asyncio.create_subprocess_exec(*command, env=environment,
                                                            stdout=asyncio.subprocess.DEVNULL,
                                                            stderr=asyncio.subprocess.DEVNULL)
            for _ in range(200):
                try:
                    settled = await self.wait_task(task["id"])
                    break
                except aiohttp.ClientError:
                    await asyncio.sleep(.01)
            else:
                self.fail("restarted subprocess Core did not settle task")
            self.assertEqual((settled["state"], self.generation.posts), ("generated", 1))
        finally:
            if process.returncode is None:
                process.kill(); await process.wait()
