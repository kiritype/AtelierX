"""ADR-0025/0026 Core contract: hands, check items, fragment numbers and output names."""
import asyncio
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.core import CORE, Core, create_app
from atelierx.core._output_names import build_output_name, sanitize_segment
from atelierx.core.store import Store

GEN = dict(diffusion_model="anima", text_encoder="encoder", vae="vae", width=512, height=512,
           seed=1, steps=24, cfg=4.5, sampler="euler", scheduler="normal")
OUTFIT = {"upper": "white shirt", "lower": "black skirt", "accessories": "gold brooch", "hands": "white gloves"}


class OutputNameTests(unittest.TestCase):
    def test_segments_are_filename_safe(self):
        self.assertEqual(sanitize_segment(' a<b>:c"d/e\\f|g?h*i\x01 '), "a_b__c_d_e_f_g_h_i_")
        self.assertEqual(sanitize_segment("  two   words.. "), "two words")
        self.assertEqual((sanitize_segment(""), sanitize_segment(" . "), sanitize_segment("con"), sanitize_segment("LPT9")), ("_", "_", "con_", "LPT9_"))
        self.assertEqual(len(sanitize_segment("x" * 200)), 80)
        self.assertEqual(build_output_name("AtelierX", "작품: 1", "캐릭터", "의상/겨울", "01"), "AtelierX/작품_ 1/캐릭터/의상_겨울/01")


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(Path(self.tmp.name) / "core.sqlite3", "http://generation.invalid", "core", "generation", 60)
        self.core.store.update_settings(1, {"positive_quality": "masterpiece, score_9"})
        work = self.core.store.create_entity("works", "Work: One", None)
        self.character = self.core.store.create_entity("characters", "Alice", work["id"], appearance_prompt="silver hair, she is 17 years old",
                                                       check_features=["silver hair", "odd eyes"])
        outfit = self.core.store.create_entity("outfits", "Winter/Coat", self.character["id"], dict(OUTFIT))
        self.group = self.core.store.create_group(outfit["id"])
        self.common = self.core.fragments.create("Painter", "by famous artist", {"upper": True, "lower": True}, common=True)

    def tearDown(self):
        self.core.store.close()
        self.tmp.cleanup()

    def preview(self, include, number="07", **extra):
        fragment = self.core.fragments.create("Pose " + number, "waving, smile", include, number=number)
        return self.core.preview({"group_id": self.group["id"], "fragment": {"id": fragment["id"], "revision": 1},
                                  "common_fragments": [{"id": self.common["id"], "revision": 1}], "generation_inputs": GEN, **extra})["snapshot"]

    def test_hands_follow_accessories_and_default_to_included(self):
        snapshot = self.preview({"upper": True, "lower": True})
        prompt = snapshot["generation_inputs"]["positive_prompt"]
        self.assertEqual(prompt, "masterpiece, score_9, silver hair, she is 17 years old, white shirt, black skirt, gold brooch, white gloves, by famous artist, waving, smile")
        self.assertEqual(snapshot["inclusion"]["hands"], {"included": True, "reason": "fragment"})
        self.assertEqual(snapshot["composition_version"], 4)
        excluded = self.preview({"upper": True, "lower": False, "accessories": True, "hands": False}, number="08")
        self.assertNotIn("white gloves", excluded["generation_inputs"]["positive_prompt"])
        self.assertEqual(excluded["inclusion"]["hands"], {"included": False, "reason": "user_excluded"})

    def test_positive_check_uses_sources_and_excludes_quality_and_common(self):
        snapshot = self.preview({"upper": True, "lower": False, "accessories": True, "hands": True})
        self.assertEqual(snapshot["positive_check"], [
            {"text": "silver hair", "source": "character_features"}, {"text": "odd eyes", "source": "character_features"},
            {"text": "white shirt", "source": "outfit_upper"}, {"text": "gold brooch", "source": "outfit_accessories"},
            {"text": "white gloves", "source": "outfit_hands"}, {"text": "waving, smile", "source": "fragment"}])
        texts = json.dumps(snapshot["positive_check"])
        self.assertNotIn("score_9", texts)
        self.assertNotIn("famous artist", texts)
        self.core.store.update_entity(self.character["id"], "characters", self.character["revision"], {"check_features": []})
        fallback = self.preview({"upper": False, "lower": False, "accessories": False, "hands": False}, number="09")
        self.assertEqual(fallback["positive_check"], [{"text": "silver hair, she is 17 years old", "source": "character_appearance"},
                                                      {"text": "waving, smile", "source": "fragment"}])

    def test_legacy_prompt_inputs_are_fragment_checks_and_empty_parts_are_skipped(self):
        outfit = self.core.store.create_entity("outfits", "Plain", self.character["id"], {"upper": "shirt", "lower": "", "accessories": ""})
        group = self.core.store.create_group(outfit["id"])
        snapshot = self.core.preview({"group_id": group["id"], "framing": "upper_body", "expression": "smiling", "generation_inputs": GEN})["snapshot"]
        self.assertEqual([item["source"] for item in snapshot["positive_check"]],
                         ["character_features", "character_features", "outfit_upper", "fragment", "fragment"])
        self.assertEqual([item["text"] for item in snapshot["positive_check"][-2:]], ["upper body", "smiling"])
        self.assertNotIn("output_name", snapshot["generation_inputs"])
        self.assertEqual(snapshot["output_name_prefix"], ["AtelierX", "Work: One", "Alice", "Plain"])

    def test_fragment_output_name_is_frozen_at_acceptance(self):
        snapshot = self.preview({"upper": True, "lower": True}, number="A-01")
        self.assertEqual(snapshot["generation_inputs"]["output_name"], "AtelierX/Work_ One/Alice/Winter_Coat/A-01")
        self.assertEqual(snapshot["fragment"]["number"], "A-01")


class HandsMigrationTests(unittest.TestCase):
    def test_existing_outfits_gain_empty_hands_with_a_new_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "core.sqlite3"
            store = Store(path)
            work = store.create_entity("works", "w", None)
            character = store.create_entity("characters", "c", work["id"])
            outfit = store.create_entity("outfits", "o", character["id"], {"upper": "u", "lower": "l", "accessories": "a", "hands": "h"})
            old = dict(outfit, components={"upper": "u", "lower": "l", "accessories": "a"})
            with store.db:
                store.db.execute("UPDATE entities SET document=? WHERE id=?", (json.dumps(old), outfit["id"]))
                store.db.execute("UPDATE revisions SET document=? WHERE entity_id=?", (json.dumps(old), outfit["id"]))
            store.close()
            store = Store(path)
            migrated = store.entity(outfit["id"], "outfits")
            self.assertEqual((migrated["components"]["hands"], migrated["revision"]), ("", 2))
            self.assertNotIn("hands", store.history(outfit["id"], "outfits", 10, 0)[-1]["components"])
            store.close()
            store = Store(path)
            self.assertEqual(store.entity(outfit["id"], "outfits")["revision"], 2)
            store.close()


class CoreScopeRestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.posts, self.jobs = [], {}
        self.png = b"\x89PNG\r\n\x1a\nfixture"
        app = web.Application()

        async def submit(request):
            body = await request.json()
            self.posts.append(body)
            job = dict(job_id=str(uuid.uuid4()), state="running", inputs=body["inputs"], images=[], error=None,
                       requested_postprocess=body.get("postprocess", {}))
            self.jobs[request.headers["Idempotency-Key"]] = job
            return web.json_response(job, status=202)

        async def by_key(request):
            job = self.jobs.get(request.headers["Idempotency-Key"])
            return web.json_response(job or {}, status=200 if job else 404)

        async def job(request):
            for item in self.jobs.values():
                if item["job_id"] == request.match_info["id"]:
                    item["state"] = "completed"
                    item["images"] = [{"image_id": item["job_id"] + "-0", "bytes": len(self.png), "sha256": hashlib.sha256(self.png).hexdigest(),
                                       "media_type": "image/png", "output_path": item["inputs"].get("output_name", "x") + ".png"}]
                    return web.json_response(item)
            return web.json_response({}, status=404)

        app.add_routes([web.post("/v1/nodes/anima/jobs", submit), web.get("/v1/jobs/by-key", by_key), web.get("/v1/jobs/{id}", job)])
        self.generation = TestServer(app)
        await self.generation.start_server()
        self.client = TestClient(TestServer(create_app(Path(self.tmp.name) / "core.sqlite3", str(self.generation.make_url("/")), "core-token", "gen-token", .01,
                                                       validation_config={"url": "http://127.0.0.1:9"})))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.generation.close()
        self.tmp.cleanup()

    async def request(self, method, path, body=None, key=None):
        headers = {"Authorization": "Bearer core-token", **({"Idempotency-Key": key} if key else {})}
        response = await self.client.request(method, path, json=body, headers=headers)
        return response.status, await response.json()

    async def wait_task(self, task_id):
        for _ in range(300):
            _, task = await self.request("GET", "/v1/tasks/" + task_id)
            if task["state"] == "generated":
                return task
            await asyncio.sleep(.01)
        self.fail(str(task))

    async def test_character_check_features_crud(self):
        _, work = await self.request("POST", "/v1/works", {"name": "w"})
        status, character = await self.request("POST", "/v1/characters", {"name": "c", "parent_id": work["id"], "check_features": [" silver hair ", "", "odd eyes"]})
        self.assertEqual((status, character["check_features"]), (201, ["silver hair", "odd eyes"]))
        status, plain = await self.request("POST", "/v1/characters", {"name": "p", "parent_id": work["id"]})
        self.assertEqual(plain["check_features"], [])
        for bad in (["x"] * 51, ["x" * 201], [1], "silver hair"):
            status, error = await self.request("PATCH", "/v1/characters/" + character["id"], {"revision": 1, "check_features": bad})
            self.assertEqual((status, error["error"]["code"]), (400, "CORE_INVALID_INPUT"), bad)
        status, changed = await self.request("PATCH", "/v1/characters/" + character["id"], {"revision": 1, "check_features": ["ahoge"]})
        self.assertEqual((status, changed["check_features"], changed["revision"]), (200, ["ahoge"], 2))
        _, detail = await self.request("GET", "/v1/characters/" + character["id"])
        self.assertEqual(detail["check_features"], ["ahoge"])
        _, history = await self.request("GET", f"/v1/characters/{character['id']}/revisions")
        self.assertEqual([item["check_features"] for item in history["items"]], [["ahoge"], ["silver hair", "odd eyes"]])
        status, outfit = await self.request("POST", "/v1/outfits", {"name": "o", "parent_id": character["id"], "components": {"upper": "u", "lower": "l", "accessories": "a", "hands": "gloves"}})
        self.assertEqual((status, outfit["components"]["hands"]), (201, "gloves"))
        status, patched = await self.request("PATCH", "/v1/outfits/" + outfit["id"], {"revision": 1, "components": {"upper": "u", "lower": "l", "accessories": "a"}})
        self.assertEqual((status, patched["components"]["hands"]), (200, ""))

    async def test_output_names_output_paths_regeneration_and_validation_scope(self):
        core = self.client.server.app[CORE]
        _, work = await self.request("POST", "/v1/works", {"name": "Work"})
        _, character = await self.request("POST", "/v1/characters", {"name": "Char", "parent_id": work["id"], "appearance_prompt": "silver hair"})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "Outfit", "parent_id": character["id"], "components": OUTFIT})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        _, fragment = await self.request("POST", "/v1/prompt-fragments", {"name": "f", "number": "12", "body": "waving", "include": {"upper": True, "lower": True}})
        status, task = await self.request("POST", "/v1/tasks", {"group_id": group["id"], "fragment": {"id": fragment["id"], "revision": 1}, "generation_inputs": GEN}, "fragment")
        self.assertEqual(status, 202, task)
        name = "AtelierX/Work/Char/Outfit/12"
        self.assertEqual(task["snapshot"]["generation_inputs"]["output_name"], name)
        await self.request("PATCH", "/v1/works/" + work["id"], {"revision": 1, "name": "Renamed"})
        await self.request("PATCH", "/v1/prompt-fragments/" + fragment["id"], {"revision": 1, "number": "99"})
        task = await self.wait_task(task["id"])
        self.assertEqual(self.posts[0]["inputs"]["output_name"], name)
        image_id = task["images"][0]["id"]
        _, image = await self.request("GET", "/v1/images/" + image_id)
        self.assertEqual(image["output_path"], name + ".png")
        _, gallery = await self.request("GET", "/v1/images?task_id=" + task["id"])
        self.assertEqual(gallery["items"][0]["output_path"], name + ".png")
        status, regenerated = await self.request("POST", f"/v1/tasks/{task['id']}/regenerations", {}, "regen")
        self.assertEqual(status, 202, regenerated)
        self.assertEqual(regenerated["snapshot"]["generation_inputs"]["output_name"], name)
        status, legacy = await self.request("POST", "/v1/tasks", {"group_id": group["id"], "framing": "full_body", "generation_inputs": GEN}, "legacy")
        self.assertEqual(legacy["snapshot"]["generation_inputs"]["output_name"], "AtelierX/Renamed/Char/Outfit/task-" + legacy["id"][:8])
        _, legacy_retry = await self.request("POST", f"/v1/tasks/{(await self.wait_task(legacy['id']))['id']}/regenerations", {}, "legacy-regen")
        self.assertEqual(legacy_retry["snapshot"]["generation_inputs"]["output_name"], legacy["snapshot"]["generation_inputs"]["output_name"])
        frozen = {"profile": {"profile_id": "p", "revision": 1}, "provider": {"provider_id": "x", "revision": 1}, "endpoint": core.validation.url}
        run, _ = core.validation.submit(image_id, "validate", {"profile_id": "p", "provider_id": "x"}, frozen)
        request = run["request"]["image"]
        self.assertEqual(request["positive_check"], task["snapshot"]["positive_check"])
        self.assertEqual({item["source"] for item in request["positive_check"]},
                         {"character_appearance", "outfit_upper", "outfit_lower", "outfit_accessories", "outfit_hands", "fragment"})
        self.assertEqual(request["positive_prompt"], task["snapshot"]["generation_inputs"]["positive_prompt"])

    async def test_legacy_task_without_snapshot_name_gets_lineage_fallback_on_regeneration(self):
        core = self.client.server.app[CORE]
        _, work = await self.request("POST", "/v1/works", {"name": "W"})
        _, character = await self.request("POST", "/v1/characters", {"name": "C", "parent_id": work["id"]})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "O", "parent_id": character["id"], "components": OUTFIT})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        snapshot = core.preview({"group_id": group["id"], "framing": "full_body", "generation_inputs": GEN})["snapshot"]
        snapshot.pop("output_name_prefix")
        snapshot.pop("positive_check")
        task = core.store.create_task("old", "fp", group["id"], snapshot)
        self.assertEqual(task["snapshot"]["generation_inputs"]["output_name"], "AtelierX/W/C/O/task-" + task["id"][:8])
        old = json.loads(core.store.db.execute("SELECT document FROM tasks WHERE id=?", (task["id"],)).fetchone()[0])
        old["snapshot"]["generation_inputs"].pop("output_name")
        with core.store.db:
            core.store.db.execute("UPDATE tasks SET document=? WHERE id=?", (json.dumps(old), task["id"]))
        await self.wait_task(task["id"])
        _, retry = await self.request("POST", f"/v1/tasks/{task['id']}/regenerations", {}, "old-regen")
        self.assertEqual(retry["snapshot"]["generation_inputs"]["output_name"], "AtelierX/W/C/O/task-" + task["id"][:8])
        run, _ = core.validation.submit((await self.wait_task(task["id"]))["images"][0]["id"], "old-validate", {"profile_id": "p", "provider_id": "x"},
                                        {"profile": {"profile_id": "p"}, "provider": {"provider_id": "x"}, "endpoint": core.validation.url})
        self.assertNotIn("positive_check", run["request"]["image"])


if __name__ == "__main__":
    unittest.main()
