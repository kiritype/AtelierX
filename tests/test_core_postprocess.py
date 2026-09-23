import asyncio
import hashlib
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from atelierx.common import ApiError
from atelierx.core.postprocess import CorePostprocess


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.image_value = {"id":"source", "task_id":"task", "generation_image_id":"gen-source", "sha256":"a" * 64, "media_type":"image/png"}
        self.task_value = {"snapshot":{"generation_endpoint":"http://generation", "generation_inputs":{"diffusion_model":"m"}}}
    def image(self, value):
        if value != "source": raise ApiError("CORE_NOT_FOUND", "missing", 404)
        return dict(self.image_value)
    def task(self, value): return dict(self.task_value)


class CorePostprocessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store()
        self.core = SimpleNamespace(store=self.store, generation_url="http://generation", presets=SimpleNamespace(snapshot=lambda *args: {"settings":{"encode":{"webp_enabled":True}}, "preset":{"id":"preset","revision":1}}))
        self.core.generation = AsyncMock()
        self.jobs = CorePostprocess(self.core)

    def tearDown(self): self.store.db.close()

    def remote(self, job, state="queued", images=None):
        return {"job_id":"123e4567-e89b-12d3-a456-426614174000", "kind":"postprocess", "state":state,
                "source_image_id":"gen-source", "source_sha256":"a" * 64, "source_media_type":"image/png",
                "inputs":{"diffusion_model":"m"}, "requested_postprocess":job["requested_postprocess"], "images":images or []}

    async def test_idempotency_preset_snapshot_and_source_unchanged(self):
        job, created = self.jobs.create("source", "key", {"preset":{"id":"preset","revision":1}})
        same, repeated = self.jobs.create("source", "key", {"preset":{"id":"preset","revision":1}})
        self.assertTrue(created); self.assertFalse(repeated); self.assertEqual(job["id"], same["id"])
        with self.assertRaises(ApiError): self.jobs.create("source", "key", {"postprocess":{"encode":{"webp_enabled":True}}})
        self.assertEqual(self.store.image_value["generation_image_id"], "gen-source")
        self.assertEqual(job["preset_source"], {"id":"preset","revision":1})
        self.core.presets.snapshot = lambda *args: {"settings":{"encode":{"webp_enabled":False}}, "preset":{"id":"preset","revision":2}}
        self.assertEqual(self.jobs.get(job["id"])["postprocess"], {"encode":{"webp_enabled":True}})

    async def test_lost_dispatch_recovers_by_key_without_second_post(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + "/core.sqlite"
            self.store.db.close(); self.store = Store(path); self.core.store = self.store; self.jobs = CorePostprocess(self.core)
            job, _ = self.jobs.create("source", "key", {"postprocess":{"encode":{"webp_enabled":True}}})
            self.core.generation.side_effect = [ApiError("CORE_GENERATION_UNAVAILABLE", "lost", 503)]
            await self.jobs.tick(); self.store.db.close()
            self.store = Store(path); self.core.store = self.store; self.jobs = CorePostprocess(self.core)
            self.core.generation = AsyncMock(return_value=self.remote(job))
            await self.jobs.tick()
            self.assertEqual(self.core.generation.await_args.args[:2], ("GET", "/v1/jobs/by-key"))
            self.store.db.close()

    async def test_cancelled_late_completion_hides_outputs(self):
        job, _ = self.jobs.create("source", "key", {"postprocess":{"encode":{"webp_enabled":True}}})
        image = {"image_id":"123e4567-e89b-12d3-a456-426614174000-0", "sha256":"b" * 64, "bytes":1, "media_type":"image/png"}
        started, release = asyncio.Event(), asyncio.Event()
        async def generation(method, path, **kwargs):
            if method == "POST": started.set(); await release.wait()
            return self.remote(job, "completed", [image])
        self.core.generation = generation
        running = asyncio.create_task(self.jobs.advance(job)); await started.wait()
        self.jobs.cancel(job["id"]); release.set(); await running
        result = self.jobs.get(job["id"])
        self.assertEqual((result["state"], result["images"]), ("cancelled", []))

    async def test_unavailable_is_bounded(self):
        job, _ = self.jobs.create("source", "key", {"postprocess":{"encode":{"webp_enabled":True}}})
        self.core.generation.side_effect = ApiError("CORE_GENERATION_UNAVAILABLE", "down", 503)
        with patch("atelierx.core.postprocess.time.time", return_value=0):
            await self.jobs.tick()
        with patch("atelierx.core.postprocess.time.time", return_value=301):
            await self.jobs.tick()
        self.assertEqual(self.jobs.get(job["id"])["error"]["code"], "CORE_GENERATION_ACCEPTANCE_UNKNOWN")


if __name__ == "__main__": unittest.main()
