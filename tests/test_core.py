import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.core import CORE, create_app

GEN = dict(diffusion_model="anima", text_encoder="encoder", vae="vae", width=512, height=512,
           seed=1, steps=24, cfg=4.5, sampler="euler", scheduler="normal")
PARTS = dict(appearance="blue eyes, silver hair, hairpin", upper="white shirt, brooch", lower="black trousers, boots, chain")


class CoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.posts, self.jobs = [], {}
        self.corrupt_response, self.error, self.corrupt_image = False, False, False
        self.png = b"\x89PNG\r\n\x1a\nfixture"
        app = web.Application()

        async def submit(request):
            self.assertEqual(request.headers["Authorization"], "Bearer gen-token")
            body = await request.json()
            key = request.headers["Idempotency-Key"]
            self.posts.append(body)
            job_id = str(uuid.uuid4())
            job = dict(job_id=job_id, state="running", inputs=body["inputs"], images=[], error=None)
            job["requested_postprocess"] = body.get("postprocess", {})
            self.jobs[key] = job
            if self.corrupt_response:
                return web.Response(text="lost JSON response")
            return web.json_response(job, status=202)

        async def by_key(request):
            job = self.jobs.get(request.headers["Idempotency-Key"])
            return web.json_response(job or {}, status=200 if job else 404)

        async def job(request):
            for item in self.jobs.values():
                if item["job_id"] == request.match_info["id"]:
                    item["state"] = "failed" if self.error else "completed"
                    item["error"] = {"code": "GEN_EXECUTION_FAILED"} if self.error else None
                    item["images"] = [] if self.error else [{"image_id": item["job_id"] + "-0", "bytes": len(self.png),
                        "sha256": hashlib.sha256(self.png).hexdigest(), "media_type": "image/png"}]
                    return web.json_response(item)
            return web.json_response({}, status=404)

        async def image(request):
            self.assertEqual(request.headers["Authorization"], "Bearer gen-token")
            return web.Response(body=b"changed" if self.corrupt_image else self.png)

        app.add_routes([web.post("/v1/nodes/anima/jobs", submit), web.get("/v1/jobs/by-key", by_key),
                        web.get("/v1/jobs/{id}", job), web.get("/v1/images/{id}", image)])
        self.generation = TestServer(app)
        await self.generation.start_server()
        self.client = await self.new_client()

    async def new_client(self):
        client = TestClient(TestServer(create_app(Path(self.tmp.name) / "core.sqlite3",
                    str(self.generation.make_url("/")), "core-token", "gen-token", .01)))
        await client.start_server()
        return client

    async def asyncTearDown(self):
        await self.client.close()
        await self.generation.close()
        self.tmp.cleanup()

    async def request(self, method, path, body=None, key=None):
        headers = {"Authorization": "Bearer core-token"}
        if key:
            headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        return response.status, await response.json()

    async def setup_group(self):
        _, work = await self.request("POST", "/v1/works", {"name": "NEVER_INSERT_WORK"})
        _, character = await self.request("POST", "/v1/characters", {"name": "NEVER_INSERT_CHARACTER", "parent_id": work["id"]})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "NEVER_INSERT_OUTFIT", "parent_id": character["id"], "components": PARTS})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        return work, character, outfit, group

    def payload(self, group):
        return dict(group_id=group["id"], framing="upper_body", expression="smiling", generation_inputs=GEN)

    async def test_character_appearance_is_always_composed_and_fragment_accessories_are_conditional(self):
        _, work = await self.request("POST", "/v1/works", {"name": "work"})
        _, character = await self.request("POST", "/v1/characters", {"name": "character", "parent_id": work["id"], "appearance_prompt": "silver hair"})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "outfit", "parent_id": character["id"], "components": {"upper": "white shirt", "lower": "boots", "accessories": "gold brooch"}})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        _, without = await self.request("POST", "/v1/prompt-fragments", {"name": "without", "number": "1", "body": "studio pose", "include": {"upper": True, "lower": False, "accessories": False}})
        _, with_accessories = await self.request("POST", "/v1/prompt-fragments", {"name": "with", "number": "2", "body": "studio pose", "include": {"upper": True, "lower": False, "accessories": True}})
        base = {"group_id": group["id"], "generation_inputs": GEN}
        _, hidden = await self.request("POST", "/v1/prompts/preview", {**base, "fragment": {"id": without["id"], "revision": 1}})
        _, shown = await self.request("POST", "/v1/prompts/preview", {**base, "fragment": {"id": with_accessories["id"], "revision": 1}})
        hidden_prompt = hidden["snapshot"]["generation_inputs"]["positive_prompt"]
        shown_prompt = shown["snapshot"]["generation_inputs"]["positive_prompt"]
        self.assertIn("silver hair", hidden_prompt)
        self.assertNotIn("gold brooch", hidden_prompt)
        self.assertIn("gold brooch", shown_prompt)
        _, changed = await self.request("PATCH", f"/v1/characters/{character['id']}", {"revision": 1, "appearance_prompt": "black hair"})
        self.assertEqual(changed["appearance_prompt"], "black hair")
        _, frozen = await self.request("GET", f"/v1/groups/{group['id']}")
        self.assertEqual(frozen["character_appearance_prompt"], "silver hair")

    async def test_common_fragments_are_frozen_and_do_not_change_variant_inclusion(self):
        _, _, _, group = await self.setup_group()
        _, variant = await self.request("POST", "/v1/prompt-fragments", {"name": "variant", "number": "1", "body": "standing pose", "include": {"upper": True, "lower": False, "accessories": False}})
        _, common = await self.request("POST", "/v1/prompt-fragments", {"name": "common", "body": "warm rim light", "common": True, "include": {"upper": False, "lower": False, "accessories": False}})
        base = {"group_id": group["id"], "generation_inputs": GEN}
        status, preview = await self.request("POST", "/v1/prompts/preview", {**base, "fragment": {"id": variant["id"], "revision": 1}, "common_fragments": [{"id": common["id"], "revision": 1}]})
        self.assertEqual(status, 200)
        prompt, inclusion = preview["snapshot"]["generation_inputs"]["positive_prompt"], preview["snapshot"]["inclusion"]
        self.assertIn("warm rim light", prompt)
        self.assertNotIn(PARTS["lower"], prompt)
        self.assertFalse(inclusion["accessories"]["included"])
        self.assertEqual(preview["snapshot"]["common_fragments"][0]["body"], "warm rim light")
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", {**base, "fragment": {"id": common["id"], "revision": 1}}))[0], 400)
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", {**base, "fragment": {"id": variant["id"], "revision": 1}, "common_fragments": [{"id": variant["id"], "revision": 1}]}))[0], 400)
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", {**base, "fragment": {"id": variant["id"], "revision": 1}, "common_fragments": [{"id": common["id"], "revision": 1}, {"id": common["id"], "revision": 1}]}))[0], 400)
        _, full_body = await self.request("POST", "/v1/prompt-fragments", {"name": "full", "body": "full body", "common": True, "include": {"upper": False, "lower": False}})
        conflict, _ = await self.request("POST", "/v1/prompts/preview", {**base, "framing": "custom", "framing_prompt": "upper body", "include": {"upper": True, "lower": False, "accessories": True}, "common_fragments": [{"id": full_body["id"], "revision": 1}]})
        self.assertEqual(conflict, 400)
        _, changed = await self.request("PATCH", f"/v1/prompt-fragments/{common['id']}", {"revision": 1, "body": "changed light"})
        self.assertEqual(changed["revision"], 2)
        stale, response = await self.request("POST", "/v1/prompts/preview", {**base, "fragment": {"id": variant["id"], "revision": 1}, "common_fragments": [{"id": common["id"], "revision": 1}]})
        self.assertEqual((stale, response["error"]["code"]), (409, "CORE_REVISION_CONFLICT"))

    async def wait_task(self, task_id, state):
        for _ in range(200):
            _, task = await self.request("GET", "/v1/tasks/" + task_id)
            if task["state"] == state:
                return task
            await asyncio.sleep(.01)
        self.fail(str(task))

    async def test_custom_framing_preserves_multiline_and_excludes_lower(self):
        _, _, _, group = await self.setup_group()
        body = dict(self.payload(group), framing="custom", framing_prompt="upper body, white background\nsimple background",
                    expression="smiling\nopen mouth", action="hand on hip\nlooking at viewer", situation="studio\nsoft light",
                    include={"appearance": True, "upper": True, "lower": False})
        status, preview = await self.request("POST", "/v1/prompts/preview", body)
        self.assertEqual(status, 200, preview)
        snapshot = preview["snapshot"]
        self.assertEqual(snapshot["composition_version"], 4)
        self.assertEqual(snapshot["prompt_inputs"]["framing_prompt"], body["framing_prompt"])
        prompt = snapshot["generation_inputs"]["positive_prompt"]
        self.assertIn(body["framing_prompt"], prompt)
        self.assertIn(body["expression"], prompt)
        self.assertNotIn("boots", prompt)
        changed = dict(body, framing_prompt="cowboy shot, white background")
        _, updated = await self.request("POST", "/v1/prompts/preview", changed)
        self.assertNotEqual(preview["preview_hash"], updated["preview_hash"])
        status, stale = await self.request("POST", "/v1/tasks", dict(changed, preview_hash=preview["preview_hash"]), "custom-stale")
        self.assertEqual(status, 409, stale)
        status, task = await self.request("POST", "/v1/tasks", dict(body, preview_hash=preview["preview_hash"]), "custom-accepted")
        self.assertEqual(status, 202, task)
        final = await self.wait_task(task["id"], "generated")
        self.assertEqual(final["snapshot"]["generation_inputs"]["positive_prompt"], prompt)

    async def test_custom_framing_rejects_ambiguous_inclusion_and_conflict(self):
        _, _, _, group = await self.setup_group()
        body = dict(self.payload(group), framing="custom", framing_prompt="upper body")
        status, _ = await self.request("POST", "/v1/prompts/preview", body)
        self.assertEqual(status, 400)
        body["include"] = {"appearance": True, "upper": True, "lower": True}
        status, conflict = await self.request("POST", "/v1/prompts/preview", body)
        self.assertEqual(status, 400)
        self.assertEqual(conflict["error"]["code"], "CORE_PROMPT_CONFLICT")
        status, conflict = await self.request("POST", "/v1/prompts/preview", dict(body,
            framing_prompt="(upper body:1.2), full body", include={"appearance": True, "upper": True, "lower": False}))
        self.assertEqual(status, 400)
        self.assertEqual(conflict["error"]["code"], "CORE_PROMPT_CONFLICT")
        for framing_prompt in ("", "  ", None):
            status, _ = await self.request("POST", "/v1/prompts/preview", dict(body, framing_prompt=framing_prompt))
            self.assertEqual(status, 400)
        status, _ = await self.request("POST", "/v1/prompts/preview", dict(self.payload(group), framing_prompt="cowboy shot"))
        self.assertEqual(status, 400)

    async def test_automatic_execution_is_charged_through_generation_rest(self):
        *_, group = await self.setup_group()
        _, initial = await self.request("POST", "/v1/tasks", self.payload(group), "auto-start")
        initial = await self.wait_task(initial["id"], "generated")
        store = self.client.app[CORE].store
        cycle = store.cycle(initial["regeneration"]["cycle_id"])
        store.update_cycle(cycle, state="active")
        child = store.create_task("auto-child", "fp", group["id"], initial["snapshot"], {
            "kind": "automatic", "parent_task_id": initial["id"], "lineage_id": initial["id"], "cycle_id": cycle["id"]})
        child = await self.wait_task(child["id"], "generated")
        self.assertEqual(child["automatic_attempts_used"], 1)
        self.assertTrue(child["automatic_started_counted"])

    async def test_manual_regeneration_rest_history_and_restart(self):
        *_, group = await self.setup_group()
        _, initial = await self.request("POST", "/v1/tasks", self.payload(group), "regen-original")
        initial = await self.wait_task(initial["id"], "generated")
        path = "/v1/tasks/" + initial["id"] + "/regenerations"
        status, child = await self.request("POST", path, {}, "regen-manual")
        self.assertEqual(status, 202)
        self.assertNotEqual(initial["snapshot"]["generation_inputs"]["seed"], child["snapshot"]["generation_inputs"]["seed"])
        self.assertEqual(child["regeneration"]["parent_task_id"], initial["id"])
        self.assertNotEqual(child["regeneration"]["cycle_id"], initial["regeneration"]["cycle_id"])
        child = await self.wait_task(child["id"], "generated")
        self.assertEqual(child["automatic_attempts_used"], 0)
        status, same = await self.request("POST", path, {}, "regen-manual")
        self.assertEqual((status, same["id"]), (200, child["id"]))
        await self.client.close()
        self.client = await self.new_client()
        _, history = await self.request("GET", path.replace("/regenerations", "/attempts"))
        self.assertEqual(history["total"], 2)
        self.assertEqual((await self.request("POST", path, {"generation_inputs": {"positive_prompt": "removed"}}, "bad-regen"))[0], 400)

    async def test_random_seed_is_resolved_once_after_preview_and_survives_reopen(self):
        *_, group = await self.setup_group()
        body = dict(self.payload(group), generation_inputs=dict(GEN, seed=-1))
        status, preview = await self.request("POST", "/v1/prompts/preview", body)
        self.assertEqual((status, preview["snapshot"]["generation_inputs"]["seed"]), (200, -1))
        status, task = await self.request("POST", "/v1/tasks", dict(body, preview_hash=preview["preview_hash"]), "random-seed")
        self.assertEqual(status, 202)
        seed = task["snapshot"]["generation_inputs"]["seed"]
        self.assertIsInstance(seed, int)
        self.assertGreaterEqual(seed, 0)
        await self.client.close()
        self.client = await self.new_client()
        status, restored = await self.request("GET", "/v1/tasks/" + task["id"])
        self.assertEqual((status, restored["snapshot"]["generation_inputs"]["seed"]), (200, seed))
        status, repeated = await self.request("POST", "/v1/tasks", dict(body, preview_hash=preview["preview_hash"]), "random-seed")
        self.assertEqual((status, repeated["id"], repeated["snapshot"]["generation_inputs"]["seed"]), (200, task["id"], seed))

    async def test_category_hierarchy_revision_and_no_cascade_archive(self):
        work, character, outfit, group = await self.setup_group()
        self.assertEqual((await self.client.get("/health")).status, 401)
        self.assertEqual((await self.request("POST", "/v1/characters", {"name": "x", "parent_id": outfit["id"]}))[0], 404)
        status, updated = await self.request("PATCH", "/v1/outfits/" + outfit["id"], {"revision": 1, "components": dict(PARTS, appearance="red eyes")})
        self.assertEqual((status, updated["revision"]), (200, 2))
        self.assertEqual((await self.request("PATCH", "/v1/outfits/" + outfit["id"], {"revision": 1, "name": "stale"}))[0], 409)
        _, history = await self.request("GET", "/v1/outfits/" + outfit["id"] + "/revisions")
        self.assertEqual(len(history["items"]), 2)
        self.assertEqual(history["items"][1]["components"], PARTS)
        await self.request("PATCH", "/v1/works/" + work["id"], {"revision": 1, "archived": True})
        self.assertEqual((await self.request("GET", "/v1/outfits/" + outfit["id"]))[1]["archived"], False)
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", self.payload(group)))[0], 409)
        self.assertEqual((await self.request("GET", "/v1/groups/" + group["id"]))[0], 200)

    async def test_prompt_order_framing_names_and_fixed_group(self):
        _, _, outfit, group = await self.setup_group()
        await self.request("PATCH", "/v1/settings", {"revision": 1, "positive_quality": "masterpiece", "negative": "blurry"})
        await self.request("PATCH", "/v1/outfits/" + outfit["id"], {"revision": 1, "components": dict(PARTS, appearance="red eyes")})
        status, preview = await self.request("POST", "/v1/prompts/preview", self.payload(group))
        self.assertEqual(status, 200)
        gen = preview["snapshot"]["generation_inputs"]
        self.assertEqual(gen["positive_prompt"], "masterpiece, " + PARTS["appearance"] + ", " + PARTS["upper"] + ", upper body, smiling")
        self.assertEqual(gen["negative_prompt"], "blurry")
        self.assertNotIn("NEVER_INSERT", gen["positive_prompt"])
        self.assertNotIn("boots", gen["positive_prompt"])
        self.assertEqual(preview["snapshot"]["inclusion"]["lower"]["reason"], "framing")
        status, full = await self.request("POST", "/v1/prompts/preview", dict(self.payload(group), framing="full_body"))
        self.assertIn(PARTS["lower"], full["snapshot"]["generation_inputs"]["positive_prompt"])
        self.assertEqual((await self.request("POST", "/v1/prompts/preview", dict(self.payload(group), include={"lower": True})))[0], 400)

    async def test_stale_preview_and_settings_limits(self):
        _, _, _, group = await self.setup_group()
        _, settings = await self.request("GET", "/v1/settings")
        self.assertEqual(settings["max_auto_regenerations"], 5)
        _, preview = await self.request("POST", "/v1/prompts/preview", self.payload(group))
        for value in (-1, True, 1.5):
            self.assertEqual((await self.request("PATCH", "/v1/settings", {"revision": 1, "max_auto_regenerations": value}))[0], 400)
        await self.request("PATCH", "/v1/settings", {"revision": 1, "negative": "new negative", "max_auto_regenerations": 0})
        self.assertEqual((await self.request("POST", "/v1/tasks", dict(self.payload(group), preview_hash=preview["preview_hash"]), "stale"))[0], 409)
        self.assertFalse(self.posts)

    async def test_generation_roundtrip_image_integrity_and_no_false_validation(self):
        _, _, _, group = await self.setup_group()
        status, task = await self.request("POST", "/v1/tasks", self.payload(group), "request")
        self.assertEqual(status, 202)
        task = await self.wait_task(task["id"], "generated")
        self.assertEqual(task["validation"], {"state": "not_requested", "outcome": None})
        self.assertEqual(task["automatic_attempts_used"], 0)
        image_id = task["images"][0]["id"]
        response = await self.client.get("/v1/images/" + image_id + "/content", headers={"Authorization": "Bearer core-token"})
        self.assertEqual(await response.read(), self.png)
        self.corrupt_image = True
        self.assertEqual((await self.request("GET", "/v1/images/" + image_id + "/content"))[0], 502)
        self.assertEqual(len(self.posts), 1)

    async def test_duplicate_requests_use_original_snapshot_after_edit_restart(self):
        _, _, _, group = await self.setup_group()
        responses = await asyncio.gather(*(self.request("POST", "/v1/tasks", self.payload(group), "repeat") for _ in range(5)))
        self.assertEqual(sorted(item[0] for item in responses), [200]*4 + [202])
        task = responses[0][1]
        await self.wait_task(task["id"], "generated")
        await self.request("PATCH", "/v1/settings", {"revision": 1, "positive_quality": "new quality"})
        self.assertEqual((await self.request("POST", "/v1/tasks", dict(self.payload(group), expression="different"), "repeat"))[0], 409)
        await self.client.close()
        self.client = await self.new_client()
        status, repeated = await self.request("POST", "/v1/tasks", self.payload(group), "repeat")
        self.assertEqual((status, repeated["id"]), (200, task["id"]))
        self.assertEqual(repeated["snapshot"], task["snapshot"])
        self.assertEqual(len(repeated["images"]), 1)
        self.assertEqual(len(self.posts), 1)

    async def test_lost_acceptance_response_queries_key_not_post_again(self):
        _, _, _, group = await self.setup_group()
        self.corrupt_response = True
        _, task = await self.request("POST", "/v1/tasks", self.payload(group), "lost")
        result = await self.wait_task(task["id"], "generated")
        self.assertIsNotNone(result["generation_job_id"])
        self.assertEqual(len(self.posts), 1)

    async def test_generation_failure_stops_without_regeneration(self):
        _, _, _, group = await self.setup_group()
        self.error = True
        _, task = await self.request("POST", "/v1/tasks", self.payload(group), "failed")
        result = await self.wait_task(task["id"], "failed")
        self.assertEqual(result["error"]["code"], "CORE_GENERATION_FAILED")
        self.assertEqual(result["images"], [])
        await asyncio.sleep(.05)
        self.assertEqual(len(self.posts), 1)

    async def test_recovery_of_previously_dispatching_missing_request_no_resubmit(self):
        _, _, _, group = await self.setup_group()
        core = self.client.server.app[CORE]
        task, _ = core.submit("recover", self.payload(group))
        task["state"] = "dispatching"
        core.store.update_task(task)
        result = await self.wait_task(task["id"], "failed")
        self.assertEqual(result["error"]["code"], "CORE_GENERATION_ACCEPTANCE_UNKNOWN")
        self.assertFalse(self.posts)

    async def test_second_owner_rejected_and_terminal_result_not_overwritten(self):
        from atelierx.core.store import Store
        with self.assertRaises(RuntimeError):
            Store(Path(self.tmp.name) / "core.sqlite3")
        _, _, _, group = await self.setup_group()
        _, task = await self.request("POST", "/v1/tasks", self.payload(group), "terminal")
        completed = await self.wait_task(task["id"], "generated")
        task.update(state="failed", error={"code": "stale"})
        self.client.server.app[CORE].store.update_task(task)
        self.assertEqual(self.client.server.app[CORE].store.task(task["id"]), completed)


    async def test_character_negative_snapshot_conflicts_and_stale_preview(self):
        work, character, outfit, group = await self.setup_group()
        await self.request("PATCH", "/v1/settings", {"revision": 1, "negative": "low quality"})
        status, updated = await self.request("PATCH", "/v1/characters/" + character["id"], {"revision": 1, "negative_prompt": "beard"})
        self.assertEqual(status, 200)
        _, preview = await self.request("POST", "/v1/prompts/preview", self.payload(group))
        self.assertEqual(preview["snapshot"]["negative_sources"], {"global": "low quality", "character": "beard"})
        self.assertEqual(preview["snapshot"]["generation_inputs"]["negative_prompt"], "low quality, beard")
        _, task = await self.request("POST", "/v1/tasks", self.payload(group), "negative-snapshot")
        await self.request("PATCH", "/v1/characters/" + character["id"], {"revision": 2, "negative_prompt": "hat"})
        status, _ = await self.request("POST", "/v1/tasks", dict(self.payload(group), preview_hash=preview["preview_hash"]), "stale-negative")
        self.assertEqual(status, 409)
        _, old = await self.request("GET", "/v1/tasks/" + task["id"])
        self.assertEqual(old["snapshot"]["negative_sources"]["character"], "beard")
        status, _ = await self.request("PATCH", "/v1/characters/" + character["id"], {"revision": 3, "negative_prompt": "low quality"})
        self.assertEqual(status, 400)
        await self.request("PATCH", "/v1/characters/" + character["id"], {"revision": 3, "negative_prompt": "upper body"})
        status, result = await self.request("POST", "/v1/prompts/preview", self.payload(group))
        self.assertEqual((status, result["error"]["code"]), (400, "CORE_PROMPT_CONFLICT"))


if __name__ == "__main__":
    unittest.main()
