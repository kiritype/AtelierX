"""Exercise the batch routes and worker through the real Core app."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.core import CORE, create_app


class BatchRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_generation_is_aggregated_and_restart_keeps_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            async def reject(request):
                calls.append(await request.json())
                return web.json_response({"error": {"code": "GEN_FIXTURE_REJECTED"}}, status=422)
            generation_app = web.Application()
            generation_app.router.add_post("/v1/nodes/anima/jobs", reject)
            async with TestServer(generation_app) as generation:
                config = {"url": "http://validation.invalid", "profiles": {
                    "single": {"profile_id": "single", "revision": 1, "output_conditions": True,
                               "positive_prompt": True, "negative_prompt": True, "body_parts": [],
                               "metadata": False, "consistency": False},
                    "group": {"profile_id": "group", "revision": 1, "consistency": True}},
                    "providers": {"vision": {"provider_id": "vision", "revision": 1,
                                              "model": "fixture", "timeout_seconds": 1}}}
                def app():
                    return create_app(Path(directory) / "core.db", str(generation.make_url("/")),
                                      "token", poll=.005, validation_config=config)
                headers = {"Authorization": "Bearer token", "Idempotency-Key": "batch-rest"}
                async with TestClient(TestServer(app())) as client:
                    store = client.app[CORE].store
                    work = store.create_entity("works", "work", None)
                    character = store.create_entity("characters", "character", work["id"])
                    outfit = store.create_entity("outfits", "outfit", character["id"],
                                                 {"appearance": "hair", "upper": "shirt", "lower": "boots"})
                    group = store.create_group(outfit["id"])
                    item = {"framing": "upper_body", "generation_inputs": {
                        "diffusion_model": "anima", "text_encoder": "encoder", "vae": "vae",
                        "width": 512, "height": 512, "seed": 1, "steps": 24, "cfg": 4.5,
                        "sampler": "euler", "scheduler": "normal"},
                        "validation": {"profile_id": "single", "provider_id": "vision"}}
                    body = {"items": [item, dict(item, expression="surprised")],
                            "group_validation": {"profile_id": "group", "provider_id": "vision"}}
                    path = f'/v1/groups/{group["id"]}/batches'
                    response = await client.post(path, json=body, headers=headers)
                    batch = await response.json()
                    self.assertEqual(response.status, 202, batch)
                    for _ in range(200):
                        response = await client.get('/v1/group-batches/' + batch["id"], headers=headers)
                        current = await response.json()
                        if current["state"] == "insufficient_images":
                            break
                        await asyncio.sleep(.005)
                    self.assertEqual(current["state"], "insufficient_images", current)
                    self.assertEqual(current["summary"]["counts"]["generation_failed"], 2)
                    self.assertIsNone(current["group_run_id"])
                    self.assertEqual(len(calls), 2)
                async with TestClient(TestServer(app())) as client:
                    response = await client.post(path, json=body, headers=headers)
                    repeated = await response.json()
                    self.assertEqual((response.status, repeated["id"]), (200, batch["id"]))
                    self.assertEqual(client.app[CORE].store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
                    self.assertEqual(len(calls), 2)
