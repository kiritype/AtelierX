"""CLI subprocess -> Client -> real Core contracts; workers stay paused, no GPU."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

from aiohttp.test_utils import TestServer
from atelierx.core import CORE, create_app


class CliCoreIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {"url": "http://127.0.0.1:1", "profiles": {"p": {"profile_id": "p", "revision": 1}},
                       "providers": {"v": {"provider_id": "v", "revision": 1}}}
        await self.start_core()
        store = self.core.store
        work = store.create_entity("works", "CLI fixture", None)
        character = store.create_entity("characters", "Character", work["id"])
        outfit = store.create_entity("outfits", "Outfit", character["id"],
                                    {"appearance": "blue eyes", "upper": "white shirt", "lower": "boots"})
        self.outfit = outfit
        self.group = store.create_group(outfit["id"])
        self.payload = {"group_id": self.group["id"], "framing": "upper_body", "postprocess": {},
                        "generation_inputs": {"diffusion_model": "fixture", "text_encoder": "fixture", "vae": "fixture",
                                              "seed": 1, "steps": 24, "cfg": 4.5, "sampler": "euler", "scheduler": "normal"}}
        self.confirm_reference_set_fixture(outfit)

    def confirm_reference_set_fixture(self, outfit):
        """ADR-0027 P5 fixture: the worker is disabled here, so build a reference
        set directly through store/reference_sets, bypassing HTTP and generation."""
        core = self.core
        gen = dict(self.payload["generation_inputs"], seed=1)
        images = {}
        for role, framing_prompt, include in (
                ("full", "full body ref", {"upper": True, "lower": True, "accessories": True, "hands": True}),
                ("face", "face ref", {"upper": True, "lower": False, "accessories": True, "hands": False})):
            snapshot = core.preview({"group_id": self.group["id"], "framing": "custom", "framing_prompt": framing_prompt,
                                     "include": include, "generation_inputs": gen, "consistency": None})["snapshot"]
            snapshot["purpose"] = "reference_sample"
            task = core.store.create_task("ref-" + role, "fp-" + role, self.group["id"], snapshot)
            image = {"id": str(uuid.uuid4()), "task_id": task["id"], "group_id": self.group["id"],
                     "generation_image_id": str(uuid.uuid4()) + "-0", "sha256": hashlib.sha256(task["id"].encode()).hexdigest(),
                     "bytes": 7, "media_type": "image/png", "validation_state": "not_requested"}
            core.store.finish_generation(task, [image])
            images[role] = image["id"]
        core.reference_sets.confirm(outfit["id"], "confirm-reference-fixture",
                                    {"full_image_id": images["full"], "face_image_id": images["face"]})

    async def start_core(self):
        app = create_app(self.root / "core.sqlite3", "http://127.0.0.1:1", "integration-token",
                         validation_config=self.config)
        self.core = app[CORE]
        async def idle():
            await asyncio.Event().wait()
        self.core.worker = idle
        self.server = TestServer(app)
        await self.server.start_server()

    async def asyncTearDown(self):
        await self.server.close()
        self.tmp.cleanup()

    async def cli(self, *args, body=None, code=0):
        arguments = list(args)
        if body is not None:
            arguments += ["--input", "-"]
        env = dict(os.environ, ATELIERX_CORE_URL=str(self.server.make_url("/")).rstrip("/"),
                   ATELIERX_CORE_TOKEN="integration-token", PYTHONIOENCODING="utf-8")
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-m", "atelierx.cli", *arguments,
                    env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(process.communicate(
                json.dumps(body).encode() if body is not None else None), 20)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise
        self.assertEqual(process.returncode, code, err.decode())
        self.assertNotIn(b"integration-token", out + err)
        self.assertEqual(err if code == 0 else out, b"")
        return json.loads(out if code == 0 else err)

    async def test_preview_acceptance_recovery_conflict_and_manual_cycle(self):
        preview = await self.cli("prompts", "preview", body=self.payload)
        self.assertNotIn("boots", preview["snapshot"]["generation_inputs"]["positive_prompt"])
        body = dict(self.payload, preview_hash=preview["preview_hash"])
        task = await self.cli("tasks", "create", "--idempotency-key", "initial", body=body)
        self.assertEqual(task["state"], "queued")
        self.assertEqual(task["snapshot"]["generation_inputs"]["width"], 1024)
        await self.server.close()
        await self.start_core()
        recovered = await self.cli("tasks", "by-key", "--idempotency-key", "initial")
        self.assertEqual(recovered["id"], task["id"])
        duplicate = await self.cli("tasks", "create", "--idempotency-key", "initial", body=body)
        self.assertEqual(duplicate["id"], task["id"])
        failure = await self.cli("tasks", "create", "--idempotency-key", "initial",
                                 body=dict(body, expression="smile"), code=1)
        self.assertEqual(failure["error"]["code"], "CORE_IDEMPOTENCY_CONFLICT")
        cancelled = await self.cli("tasks", "cancel", task["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        child = await self.cli("tasks", "regenerate", task["id"], "--idempotency-key", "manual", body={})
        self.assertNotEqual(child["id"], task["id"])
        self.assertNotEqual(child["regeneration"]["cycle_id"], task["regeneration"]["cycle_id"])
        attempts = await self.cli("tasks", "attempts", task["id"])
        self.assertEqual(attempts["total"], 2)
        cycle_id = child["regeneration"]["cycle_id"]
        cycle = await self.cli("cycles", "get", cycle_id)
        self.assertEqual(cycle["limit"], 5)
        stopped = await self.cli("cycles", "stop", cycle_id)
        self.assertEqual(stopped["state"], "stopped")

    async def test_validation_acceptance_idempotency_and_cancel(self):
        # Seed a completed image fixture; no Generation/VLM call is made.
        task, _ = self.core.submit("fixture-generation", self.payload)
        image = {"id": str(uuid.uuid4()), "task_id": task["id"], "group_id": self.group["id"],
                 "generation_image_id": str(uuid.uuid4()) + "-0", "sha256": hashlib.sha256(b"fixture").hexdigest(),
                 "bytes": 7, "media_type": "image/png", "validation_state": "not_requested"}
        self.core.store.finish_generation(task, [image])
        selection = {"provider_id": "v", "profile_id": "p"}
        run = await self.cli("images", "validate", image["id"], "--idempotency-key", "validation", body=selection)
        duplicate = await self.cli("images", "validate", image["id"], "--idempotency-key", "validation", body=selection)
        self.assertEqual(run["id"], duplicate["id"])
        self.assertEqual((await self.cli("validations", "get", run["id"]))["state"], "queued")
        cancelled = await self.cli("validations", "cancel", run["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(len(self.core.store.image_validations(image["id"])), 1)
