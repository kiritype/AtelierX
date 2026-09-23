import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError
from atelierx.core import create_app as core_app, generation_settings
from atelierx.core.presets import validate_postprocess_settings
from atelierx.core.standalone import StandaloneJobs
from atelierx.core.store import Store


class StandaloneJobsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); store = Store(Path(self.tmp.name) / "core.sqlite3")
        self.calls = []
        async def generation(method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return {"job_id": "job", "state": "completed", "inputs": kwargs["json"]["inputs"], "requested_postprocess": kwargs["json"]["postprocess"], "images": [{"image_id":"img","bytes":1,"sha256":"a" * 64,"media_type":"image/png"}]} if method == "POST" else None
        self.gpu_calls = []
        gpu = SimpleNamespace(config=None)
        async def acquire(*args): self.gpu_calls.append(("acquire", args)); return {"granted": True}
        async def release(*args): self.gpu_calls.append(("release", args)); return {"released": True}
        gpu.acquire, gpu.release = acquire, release
        self.core = SimpleNamespace(store=store, gpu=gpu, generation=generation, generation_url="http://generation", session=None)
        config = {"generation_inputs": {"diffusion_model":"m","text_encoder":"t","vae":"v","negative_prompt":"bad","seed":1,"steps":1,"cfg":1,"sampler":"s","scheduler":"s"}, "postprocess": {}, "llm":{"url":"http://127.0.0.1:1234/v1/chat/completions","model":"m","api_key_env":"TEST_KEY","timeout_seconds":1}}
        self.jobs = StandaloneJobs(self.core, config, generation_settings, validate_postprocess_settings)

    async def asyncTearDown(self):
        if self.core.session: await self.core.session.close()
        self.core.store.close(); self.tmp.cleanup()

    async def test_direct_is_idempotent_and_dispatches_once_after_durable_intent(self):
        job, created = self.jobs.create("key", {"prompt":"literal, prompt","mode":"direct"})
        same, repeated = self.jobs.create("key", {"prompt":"literal, prompt","mode":"direct"})
        self.assertTrue(created); self.assertFalse(repeated); self.assertEqual(job["id"], same["id"])
        await self.jobs.advance(job); self.assertEqual(self.jobs.get(job["id"])["state"], "ready_to_dispatch")
        await self.jobs.advance(job); self.assertEqual(self.jobs.get(job["id"])["state"], "completed")
        self.assertEqual(self.calls[0][2]["json"]["inputs"]["positive_prompt"], "literal, prompt")
        self.assertRegex(self.calls[0][2]["json"]["inputs"]["output_name"], r"^AtelierX/discord/\d{4}-\d{2}-\d{2}/\d{6}-" + job["id"][:6] + "$")
        self.assertEqual(job["generation_inputs"]["output_name"], self.calls[0][2]["json"]["inputs"]["output_name"])

    async def test_optional_mode_is_normalized_without_changing_legacy_fingerprint(self):
        direct, created = self.jobs.create("legacy-direct", {"prompt": "literal", "mode": "direct"})
        defaulted, repeated = self.jobs.create("legacy-direct", {"prompt": "literal"})
        self.assertTrue(created); self.assertFalse(repeated); self.assertEqual(direct["id"], defaulted["id"])
        natural, _ = self.jobs.create("normalized-natural", {"prompt": "literal", "mode": " Natural "})
        self.assertEqual(natural["request"]["mode"], "natural")

    async def test_optional_negative_is_snapshotted_and_combined_by_core(self):
        negative = "  low quality,  watermark\n"
        job, _ = self.jobs.create("negative", {"prompt": "literal", "negative_prompt": negative})
        self.assertEqual(job["request"], {"prompt": "literal", "mode": "direct", "negative_prompt": negative})
        self.assertEqual(job["generation_inputs"]["negative_prompt"], "bad, " + negative)
        omitted, _ = self.jobs.create("default-negative", {"prompt": "literal"})
        whitespace, _ = self.jobs.create("whitespace-negative", {"prompt": "literal", "negative_prompt": " \n "})
        self.assertEqual(omitted["generation_inputs"]["negative_prompt"], "bad")
        self.assertEqual(whitespace["generation_inputs"]["negative_prompt"], "bad")
        self.jobs.config["generation_inputs"]["negative_prompt"] = ""
        no_base, _ = self.jobs.create("no-base-negative", {"prompt": "literal", "negative_prompt": negative})
        self.assertEqual(no_base["generation_inputs"]["negative_prompt"], negative)
        for invalid in (123, "x" * 20001):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ApiError):
                    self.jobs.create("invalid-negative-" + str(type(invalid)), {"prompt": "literal", "negative_prompt": invalid})
        with self.assertRaises(ApiError):
            self.jobs.create("unknown-field", {"prompt": "literal", "unknown": "value"})

    async def test_checkpoint_is_allowlisted_and_snapshot_survives_config_change(self):
        self.jobs.config["allowed_checkpoints"] = ["m", "models/alternate.safetensors"]
        job, created = self.jobs.create("checkpoint", {"prompt": "literal", "checkpoint": "models/alternate.safetensors"})
        self.assertTrue(created)
        self.assertEqual(job["generation_inputs"]["diffusion_model"], "models/alternate.safetensors")
        self.assertEqual(self.jobs.public(job)["checkpoint"], "models/alternate.safetensors")
        self.jobs.config["allowed_checkpoints"] = ["m"]
        repeated, created = self.jobs.create("checkpoint", {"prompt": "literal", "checkpoint": "models/alternate.safetensors"})
        self.assertFalse(created); self.assertEqual(repeated["id"], job["id"])
        with self.assertRaises(ApiError):
            self.jobs.create("new-checkpoint", {"prompt": "literal", "checkpoint": "models/alternate.safetensors"})
        for invalid in ("", "x" * 256, 123):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ApiError):
                    self.jobs.create("invalid-checkpoint-" + str(type(invalid)), {"prompt": "literal", "checkpoint": invalid})

    async def test_checkpoint_configuration_and_listing(self):
        config = {**self.jobs.config, "allowed_checkpoints": ["m", "models/alternate.safetensors"]}
        app = core_app(Path(self.tmp.name) / "checkpoint-core.sqlite3", "http://generation", "token",
                       poll=100, standalone_config=config)
        client = TestClient(TestServer(app)); await client.start_server()
        try:
            response = await client.get("/v1/standalone-checkpoints", headers={"Authorization": "Bearer token"})
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), {"items": [{"name": "m", "value": "m"}, {"name": "models/alternate.safetensors", "value": "models/alternate.safetensors"}], "default": "m"})
        finally:
            await client.close()
        for allowed in ([], ["models/alternate.safetensors"], ["../escape.safetensors"], ["https://example.invalid/model"]):
            with self.subTest(allowed=allowed):
                with self.assertRaises(ValueError):
                    StandaloneJobs(self.core, {**self.jobs.config, "allowed_checkpoints": allowed}, generation_settings, validate_postprocess_settings)

    async def test_random_seed_is_safe_once_per_job_and_fixed_mode_remains_compatible(self):
        self.jobs.config["seed_mode"] = "random"
        with patch("atelierx.core.standalone.secrets.randbelow", return_value=9007199254740991) as random_seed:
            job, _ = self.jobs.create("random", {"prompt":"x","mode":"direct"})
            duplicate, created = self.jobs.create("random", {"prompt":"x","mode":"direct"})
        self.assertFalse(created); self.assertEqual(job["seed"], 9007199254740991)
        self.assertEqual(duplicate["seed"], job["seed"]); random_seed.assert_called_once_with(2**53)
        await self.jobs.advance(job); await self.jobs.advance(job)
        self.assertEqual(self.calls[-1][2]["json"]["inputs"]["seed"], job["seed"])

    async def test_legacy_queued_job_uses_saved_fixed_config_seed_without_rerandomizing(self):
        job, _ = self.jobs.create("legacy", {"prompt":"x","mode":"direct"})
        job.pop("seed"); job["generation_inputs"] = None; self.jobs.save(job)
        await self.jobs.advance(job)
        saved = self.jobs.get(job["id"])
        self.assertEqual((saved["seed"], saved["generation_inputs"]["seed"]), (1, 1))

    async def test_natural_uses_fake_llm_releases_planner_and_posts_once(self):
        async def llm(request):
            self.assertEqual((await request.json())["messages"][1]["content"], "draw cat")
            return web.json_response({"choices":[{"message":{"content":"cat, studio"}}]})
        server = TestServer(web.Application()); server.app.router.add_post("/chat", llm); await server.start_server()
        self.addAsyncCleanup(server.close)
        self.jobs.config["llm"]["url"] = str(server.make_url("/chat")); os.environ["TEST_KEY"] = "secret"
        self.core.session = aiohttp.ClientSession()
        job, _ = self.jobs.create("natural", {"prompt":"draw cat","mode":"natural"})
        await self.jobs.advance(job); saved = self.jobs.get(job["id"])
        self.assertEqual(saved["state"], "ready_to_dispatch"); self.assertEqual(saved["generation_inputs"]["positive_prompt"], "cat, studio")
        self.assertEqual([entry[0] for entry in self.gpu_calls], ["acquire", "release"])
        await self.jobs.advance(saved); self.assertEqual(len(self.calls), 1)

    async def test_gpu_denial_stays_queued_then_plans_on_next_tick(self):
        answers = iter(({"granted": False}, {"granted": True}))
        async def acquire(*args): return next(answers)
        self.core.gpu.acquire = acquire; self.jobs._plan = AsyncMock(return_value="converted")
        os.environ["TEST_KEY"] = "secret"
        job, _ = self.jobs.create("wait", {"prompt":"later","mode":"natural"})
        await self.jobs.advance(job); self.assertEqual(self.jobs.get(job["id"])["state"], "queued")
        await self.jobs.advance(job); self.assertEqual(self.jobs.get(job["id"])["state"], "ready_to_dispatch")
        self.jobs._plan.assert_awaited_once()

    async def test_planning_restart_fails_without_second_llm_and_completed_releases(self):
        os.environ["TEST_KEY"] = "secret"; job, _ = self.jobs.create("restart", {"prompt":"x","mode":"natural"})
        job["state"] = "planning"; self.jobs.save(job); self.jobs._plan = AsyncMock(return_value="never")
        await self.jobs.tick(); saved = self.jobs.get(job["id"])
        self.assertEqual(saved["error"]["code"], "CORE_PLANNER_ACCEPTANCE_UNKNOWN"); self.jobs._plan.assert_not_awaited()
        job, _ = self.jobs.create("completed", {"prompt":"x","mode":"natural"}); job.update(state="planner_completed", generation_inputs={**job["config"]["generation_inputs"], "positive_prompt":"done"}); self.jobs.save(job)
        await self.jobs.advance(job); self.assertEqual(self.jobs.get(job["id"])["state"], "ready_to_dispatch")
        self.assertIn("release", [entry[0] for entry in self.gpu_calls])

    async def test_acceptance_loss_recovers_by_key_without_second_post_and_malformed_fails(self):
        jobs = {}
        async def generation(method, path, **kwargs):
            if method == "POST":
                jobs["key"] = {"job_id":"accepted","state":"queued","inputs":kwargs["json"]["inputs"],"requested_postprocess":kwargs["json"]["postprocess"],"images":[]}
                raise ApiError("CORE_GENERATION_UNAVAILABLE", "lost", 503)
            if path.endswith("by-key"): return jobs.get("key")
            return {"job_id":"accepted", "state":"bad", "inputs": kwargs.get("json", {}).get("inputs")}
        self.core.generation = generation
        job, _ = self.jobs.create("lost", {"prompt":"x","mode":"direct"}); await self.jobs.advance(job)
        with self.assertRaises(ApiError): await self.jobs.advance(job)
        await self.jobs.advance(job)
        self.assertEqual(self.jobs.get(job["id"])["state"], "generation_pending")
        # A malformed terminal response marks this job failed while tick remains usable.
        job["state"] = "generation_pending"; job["generation_job_id"] = "accepted"; self.jobs.save(job)
        await self.jobs.tick(); self.assertEqual(self.jobs.get(job["id"])["state"], "failed")
