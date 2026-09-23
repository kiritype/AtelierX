from __future__ import annotations

import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError
from atelierx.core import CORE, create_app, generation_settings
from atelierx.core.presets import CorePresets
from _reference_fixture import confirm_reference_set_offline


GENERATION = {
    "diffusion_model": "anima.safetensors", "text_encoder": "anima-te.safetensors",
    "vae": "anima-vae.safetensors", "width": 768, "height": 1024, "seed": 7,
    "steps": 24, "cfg": 4.5, "sampler": "euler_ancestral", "scheduler": "normal",
    "loras": [{"name": "style.safetensors", "strength": 0.8}],
}


class CorePresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "core.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.presets = CorePresets(self.db, generation_settings)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_generation_revision_history_and_snapshot_are_immutable(self):
        created = self.presets.create("generation", "Anima portrait", GENERATION)
        snap = self.presets.snapshot("generation", created["id"], 1)
        changed = self.presets.update("generation", created["id"], 1, {
            "settings": dict(GENERATION, seed=99),
        })

        self.assertEqual(changed["revision"], 2)
        self.assertEqual(snap["preset"]["revision"], 1)
        self.assertEqual(snap["settings"]["seed"], 7)
        history = self.presets.history("generation", created["id"])
        self.assertEqual([entry["revision"] for entry in history], [2, 1])
        self.assertEqual(history[1]["settings"]["seed"], 7)
        with self.assertRaisesRegex(ApiError, "refresh before editing"):
            self.presets.update("generation", created["id"], 1, {"name": "stale"})

    def test_archive_excludes_preset_from_application_but_keeps_history(self):
        created = self.presets.create("postprocess", "Alpha", {"alpha": {"segmentation_model": "segm/person.pt"}})
        archived = self.presets.update("postprocess", created["id"], 1, {"archived": True})

        self.assertTrue(archived["archived"])
        self.assertEqual(self.presets.list("postprocess", archived=False), [])
        self.assertEqual(self.presets.list("postprocess", archived=True)[0]["id"], created["id"])
        with self.assertRaisesRegex(ApiError, "Archived preset"):
            self.presets.snapshot("postprocess", created["id"], 2)
        self.assertEqual(self.presets.history("postprocess", created["id"])[-1]["revision"], 1)

    def test_rejects_prompt_secret_path_and_invalid_postprocess_values(self):
        with self.assertRaisesRegex(ApiError, "Missing or unknown fields"):
            self.presets.create("generation", "bad", dict(GENERATION, positive_prompt="not stored"))
        with self.assertRaisesRegex(ApiError, "registered model name, not a path"):
            self.presets.create("generation", "bad", dict(GENERATION, diffusion_model="C:\\secret\\model.safetensors"))
        with self.assertRaisesRegex(ApiError, "registered model name, not a path"):
            self.presets.create("postprocess", "bad", {"alpha": {"segmentation_model": "C:\\secret\\model.pt"}})
        with self.assertRaisesRegex(ApiError, "alpha requires"):
            self.presets.create("postprocess", "bad", {"alpha": {"confidence": 0.4}})
        with self.assertRaisesRegex(ApiError, "unknown settings"):
            self.presets.create("postprocess", "bad", {"encode": {"api_key": "secret"}})

    def test_preserves_registered_relative_windows_model_name(self):
        created = self.presets.create("postprocess", "Alpha", {"alpha": {"segmentation_model": "segm\\person.pt"}})
        self.assertEqual(created["settings"]["alpha"]["segmentation_model"], "segm\\person.pt")

    def test_presets_and_revisions_survive_reopen(self):
        created = self.presets.create("generation", "Restart", GENERATION)
        self.presets.update("generation", created["id"], 1, {"name": "Restart revised"})
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.presets = CorePresets(self.db, generation_settings)

        restored = self.presets.get("generation", created["id"])
        self.assertEqual((restored["name"], restored["revision"]), ("Restart revised", 2))
        self.assertEqual(len(self.presets.history("generation", created["id"])), 2)


class PresetRestTaskIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs = {}
        generation = web.Application()

        async def submit(request):
            body = await request.json()
            job_id = str(uuid.uuid4())
            job = {"job_id": job_id, "state": "submitted", "inputs": body["inputs"],
                   "requested_postprocess": body.get("postprocess", {}), "images": [], "error": None}
            self.jobs[job_id] = job
            return web.json_response(job, status=202)

        async def job(request):
            value = self.jobs.get(request.match_info["id"])
            return web.json_response(value or {}, status=200 if value else 404)

        async def by_key(request):
            return web.json_response({}, status=404)

        generation.add_routes([web.post("/v1/nodes/anima/jobs", submit), web.get("/v1/jobs/{id}", job), web.get("/v1/jobs/by-key", by_key)])
        self.generation = TestServer(generation)
        await self.generation.start_server()
        self.client = TestClient(TestServer(create_app(Path(self.tmp.name) / "core.sqlite3", str(self.generation.make_url("/")), "core-token", "generation-token", 60)))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer core-token"}

    async def asyncTearDown(self):
        await self.client.close()
        await self.generation.close()
        self.tmp.cleanup()

    async def request(self, method, path, body=None, key=None):
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        return response.status, await response.json()

    async def group(self):
        _, work = await self.request("POST", "/v1/works", {"name": "work"})
        _, character = await self.request("POST", "/v1/characters", {"name": "character", "parent_id": work["id"]})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "outfit", "parent_id": character["id"], "components": {"appearance": "blue eyes", "upper": "shirt", "lower": "boots"}})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        confirm_reference_set_offline(self.client.server.app[CORE], group["id"], outfit["id"], GENERATION)
        return group

    async def test_authenticated_rest_and_versioned_preset_task_snapshot(self):
        unauthenticated = await self.client.get("/v1/presets/generation")
        self.assertEqual(unauthenticated.status, 401)
        status, preset = await self.request("POST", "/v1/presets/generation", {"name": "Anima", "settings": GENERATION})
        self.assertEqual(status, 201)
        self.assertEqual((await self.request("GET", "/v1/presets/generation"))[1]["items"][0]["id"], preset["id"])
        group = await self.group()
        task_input = {"group_id": group["id"], "framing": "upper_body", "presets": {"generation": {"id": preset["id"], "revision": 1}}}
        status, preview = await self.request("POST", "/v1/prompts/preview", task_input)
        self.assertEqual(status, 200)
        self.assertEqual(preview["snapshot"]["generation_inputs"]["seed"], 7)
        self.assertEqual(preview["snapshot"]["preset_sources"]["generation"], {"id": preset["id"], "kind": "generation", "name": "Anima", "revision": 1})
        status, task = await self.request("POST", "/v1/tasks", task_input, "preset-task")
        self.assertEqual(status, 202)
        _, changed = await self.request("PATCH", "/v1/presets/generation/" + preset["id"], {"revision": 1, "settings": dict(GENERATION, seed=99)})
        self.assertEqual(changed["revision"], 2)
        _, original = await self.request("GET", "/v1/tasks/" + task["id"])
        self.assertEqual(original["snapshot"]["generation_inputs"]["seed"], 7)
        status, repeated = await self.request("POST", "/v1/tasks", task_input, "preset-task")
        self.assertEqual((status, repeated["id"]), (200, task["id"]))
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", task_input))[0], 409)
        self.assertEqual((await self.request("POST", "/v1/tasks", task_input, "new-key"))[0], 409)

    async def test_direct_settings_conflicts_with_preset_and_missing_generation_is_invalid(self):
        _, preset = await self.request("POST", "/v1/presets/generation", {"name": "Anima", "settings": GENERATION})
        group = await self.group()
        both = {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GENERATION, "presets": {"generation": {"id": preset["id"], "revision": 1}}}
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", both))[0], 400)
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", {"group_id": group["id"], "framing": "upper_body"}))[0], 400)


if __name__ == "__main__":
    unittest.main()
