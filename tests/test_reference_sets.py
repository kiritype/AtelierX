"""ADR-0027: reference sets, consistency composition and P5 enforcement."""
import tempfile
import unittest
import uuid
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from atelierx.core import CORE, create_app
from _reference_fixture import confirm_reference_set

GEN = dict(diffusion_model="anima", text_encoder="encoder", vae="vae", width=512, height=512,
           seed=1, steps=24, cfg=4.5, sampler="euler", scheduler="normal")
PARTS = {"upper": "white shirt", "lower": "black trousers", "accessories": "brooch"}


class ReferenceSetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.posts = []

        from aiohttp import web
        import hashlib
        app = web.Application()
        self.jobs = {}

        async def submit(request):
            body = await request.json()
            key = request.headers["Idempotency-Key"]
            job_id = str(uuid.uuid4())
            png = b"\x89PNG\r\n\x1a\nfixture"
            job = {"job_id": job_id, "state": "completed", "execution_started": True, "inputs": body["inputs"],
                   "requested_postprocess": body.get("postprocess", {}), "error": None,
                   "images": [{"image_id": job_id + "-0", "bytes": len(png), "sha256": hashlib.sha256(png).hexdigest(), "media_type": "image/png"}]}
            self.jobs[key] = job
            self.posts.append(body)
            return web.json_response(job, status=202)

        async def by_key(request):
            return web.json_response(self.jobs.get(request.headers["Idempotency-Key"], {}), status=200 if request.headers["Idempotency-Key"] in self.jobs else 404)

        async def job(request):
            for value in self.jobs.values():
                if value["job_id"] == request.match_info["id"]:
                    return web.json_response(value)
            return web.json_response({}, status=404)

        app.add_routes([web.post("/v1/nodes/anima/jobs", submit), web.get("/v1/jobs/by-key", by_key), web.get("/v1/jobs/{id}", job)])
        self.generation = TestServer(app)
        await self.generation.start_server()
        self.client = TestClient(TestServer(create_app(Path(self.tmp.name) / "core.sqlite3", str(self.generation.make_url("/")), "core-token", "gen-token", .01)))
        await self.client.start_server()
        self.core = self.client.server.app[CORE]

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

    async def setup_group(self, name="reference"):
        _, work = await self.request("POST", "/v1/works", {"name": name + "-work"})
        _, character = await self.request("POST", "/v1/characters", {"name": name + "-char", "parent_id": work["id"], "appearance_prompt": "silver hair"})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": name + "-outfit", "parent_id": character["id"], "components": PARTS})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        return character, outfit, group

    async def test_status_none_then_valid_after_confirm(self):
        _, outfit, group = await self.setup_group()
        status, before = await self.request("GET", f"/v1/outfits/{outfit['id']}/reference-set")
        self.assertEqual((status, before["status"], before["set"]), (200, "none", None))
        confirmed = await confirm_reference_set(self.request, outfit["id"], GEN)
        self.assertEqual(confirmed["revision"], 1)
        _, after = await self.request("GET", f"/v1/outfits/{outfit['id']}/reference-set")
        self.assertEqual(after["status"], "valid")

    async def test_sample_pair_shares_seed_and_uses_reference_output_path(self):
        _, outfit, group = await self.setup_group()
        status, pair = await self.request("POST", f"/v1/outfits/{outfit['id']}/reference-samples", {"generation_inputs": GEN}, "pair-1")
        self.assertEqual(status, 201)
        self.assertNotEqual(pair["full_task_id"], pair["face_task_id"])
        # Same key replays the same pair (idempotency).
        status2, pair2 = await self.request("POST", f"/v1/outfits/{outfit['id']}/reference-samples", {"generation_inputs": GEN}, "pair-1")
        self.assertEqual((status2, pair2), (200, pair))
        _, listed = await self.request("GET", f"/v1/outfits/{outfit['id']}/reference-samples")
        self.assertEqual(len(listed["items"]), 1)
        full_task, face_task = listed["items"][0]["full_task"], listed["items"][0]["face_task"]
        self.assertEqual(full_task["snapshot"]["generation_inputs"]["seed"], face_task["snapshot"]["generation_inputs"]["seed"])
        self.assertEqual(full_task["snapshot"]["purpose"], "reference_sample")
        self.assertIn("/reference/full-", full_task["snapshot"]["generation_inputs"]["output_name"])
        self.assertIn("/reference/face-", face_task["snapshot"]["generation_inputs"]["output_name"])

    async def test_needs_review_after_outfit_change_and_reconfirm(self):
        character, outfit, group = await self.setup_group()
        confirmed = await confirm_reference_set(self.request, outfit["id"], GEN)
        _, patched = await self.request("PATCH", f"/v1/outfits/{outfit['id']}", {"revision": 1, "components": dict(PARTS, upper="new shirt")})
        self.assertEqual(patched["revision"], 2)
        status, review = await self.request("GET", f"/v1/outfits/{outfit['id']}/reference-set")
        self.assertEqual((status, review["status"], review["stale"]), (200, "needs_review", ["outfit"]))
        # Blocked without reconfirm.
        status, blocked = await self.request("POST", "/v1/tasks",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN, "consistency": None}, "blocked-task")
        self.assertEqual((status, blocked["error"]["code"]), (409, "CORE_REFERENCE_SET_REQUIRED"))
        # "변경 확인 후 유지": reconfirm without new images.
        status, reconfirmed = await self.request("POST", f"/v1/outfits/{outfit['id']}/reference-set/reconfirm",
            {"revision": confirmed["revision"]}, "reconfirm-1")
        self.assertEqual((status, reconfirmed["revision"], reconfirmed["full"]), (201, 2, confirmed["full"]))
        _, valid_again = await self.request("GET", f"/v1/outfits/{outfit['id']}/reference-set")
        self.assertEqual(valid_again["status"], "valid")
        status, allowed = await self.request("POST", "/v1/tasks",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN, "consistency": None}, "allowed-task")
        self.assertIn(status, (200, 201, 202))

    async def test_reconfirm_stale_revision_conflicts(self):
        _, outfit, group = await self.setup_group()
        await confirm_reference_set(self.request, outfit["id"], GEN)
        status, error = await self.request("POST", f"/v1/outfits/{outfit['id']}/reference-set/reconfirm", {"revision": 99}, "bad-reconfirm")
        self.assertEqual((status, error["error"]["code"]), (409, "CORE_REVISION_CONFLICT"))

    async def test_history_lists_revisions_newest_first(self):
        character, outfit, group = await self.setup_group()
        first = await confirm_reference_set(self.request, outfit["id"], GEN)
        await self.request("PATCH", f"/v1/outfits/{outfit['id']}", {"revision": 1, "components": dict(PARTS, upper="new shirt")})
        second = await self.request("POST", f"/v1/outfits/{outfit['id']}/reference-set/reconfirm", {"revision": first["revision"]}, "history-reconfirm")
        status, history = await self.request("GET", f"/v1/outfits/{outfit['id']}/reference-set/revisions")
        self.assertEqual((status, [item["revision"] for item in history["items"]], history["total"]), (200, [2, 1], 2))

    async def test_production_plan_and_task_enforcement_and_exemptions(self):
        _, outfit, group = await self.setup_group()
        _, fragment = await self.request("POST", "/v1/prompt-fragments",
            {"name": "pose", "number": "1", "body": "standing", "include": {"upper": True, "lower": True}})
        # No reference set yet: blocked.
        status, error = await self.request("POST", "/v1/production-plans",
            {"group_id": group["id"], "fragments": [{"id": fragment["id"], "revision": 1}], "generation_inputs": GEN}, "plan-blocked")
        self.assertEqual((status, error["error"]["code"]), (409, "CORE_REFERENCE_SET_REQUIRED"))
        # Reference sample generation itself must not be blocked by its own missing reference set.
        status, pair = await self.request("POST", f"/v1/outfits/{outfit['id']}/reference-samples", {"generation_inputs": GEN}, "self-sample")
        self.assertEqual(status, 201)
        await confirm_reference_set(self.request, outfit["id"], GEN, key="reference-samples-for-plan")
        status, plan = await self.request("POST", "/v1/production-plans",
            {"group_id": group["id"], "fragments": [{"id": fragment["id"], "revision": 1}], "generation_inputs": GEN}, "plan-allowed")
        self.assertEqual(status, 201, plan)
        self.assertEqual(plan["state"], "draft")

    async def test_default_consistency_is_composed_when_reference_is_valid(self):
        _, outfit, group = await self.setup_group()
        await confirm_reference_set(self.request, outfit["id"], GEN)
        status, preview = await self.request("POST", "/v1/prompts/preview",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN})
        self.assertEqual(status, 200)
        consistency = preview["snapshot"]["consistency"]
        self.assertEqual(consistency["method"], "anima-incontext-character")
        self.assertEqual(consistency["params"], {"strength": 1.0, "end_percent": 0.5, "suppress_reference_background": True})
        self.assertEqual({item["role"] for item in consistency["references"]}, {"full", "face"})
        self.assertEqual(preview["snapshot"]["negative_sources"]["consistency"], "white background, simple background")
        self.assertTrue(preview["snapshot"]["generation_inputs"]["negative_prompt"].endswith("white background, simple background"))
        gen_consistency = preview["snapshot"]["generation_inputs"]["consistency"]
        self.assertEqual(set(gen_consistency["references"][0]), {"role", "image_id", "sha256"})
        # Explicit opt-out.
        status, opted_out = await self.request("POST", "/v1/prompts/preview",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN, "consistency": None})
        self.assertNotIn("consistency", opted_out["snapshot"])
        self.assertNotIn("consistency", opted_out["snapshot"]["negative_sources"])

    async def test_consistency_params_validated_against_ranges(self):
        _, outfit, group = await self.setup_group()
        await confirm_reference_set(self.request, outfit["id"], GEN)
        status, error = await self.request("POST", "/v1/prompts/preview",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN,
             "consistency": {"method": "anima-incontext-character", "params": {"strength": 5.0}}})
        self.assertEqual(status, 400)
        status, unknown = await self.request("POST", "/v1/prompts/preview",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN, "consistency": {"method": "unknown-method"}})
        self.assertEqual(status, 400)

    async def test_settings_mismatch_warns_then_can_be_accepted(self):
        _, outfit, group = await self.setup_group()
        await confirm_reference_set(self.request, outfit["id"], GEN)
        mismatched = dict(GEN, diffusion_model="other-model.safetensors")
        status, error = await self.request("POST", "/v1/tasks",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": mismatched, "consistency": None}, "mismatch-task")
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "CORE_REFERENCE_SETTINGS_MISMATCH")
        self.assertIn("diffusion_model", error["error"]["diff"])
        status, task = await self.request("POST", "/v1/tasks",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": mismatched, "consistency": None,
             "accept_reference_settings_mismatch": True}, "mismatch-accepted")
        self.assertIn(status, (200, 201, 202), task)
        self.assertTrue(task["snapshot"]["reference_settings_mismatch_accepted"]["accepted"])
        self.assertIn("diffusion_model", task["snapshot"]["reference_settings_mismatch_accepted"]["diff"])

    async def test_regeneration_keeps_original_snapshot_without_enforcement(self):
        _, outfit, group = await self.setup_group()
        await confirm_reference_set(self.request, outfit["id"], GEN)
        status, task = await self.request("POST", "/v1/tasks",
            {"group_id": group["id"], "framing": "upper_body", "generation_inputs": GEN}, "regen-source")
        self.assertEqual(status, 202, task)
        for _ in range(300):
            _, task = await self.request("GET", "/v1/tasks/" + task["id"])
            if task["state"] == "generated":
                break
        self.assertEqual(task["state"], "generated")
        original_consistency = task["snapshot"].get("consistency")
        self.assertIsNotNone(original_consistency)
        # Invalidate the reference set, then confirm regeneration is still exempt from
        # enforcement and keeps the original consistency block untouched.
        await self.request("PATCH", f"/v1/outfits/{outfit['id']}", {"revision": 1, "components": dict(PARTS, upper="new shirt")})
        status, review = await self.request("GET", f"/v1/outfits/{outfit['id']}/reference-set")
        self.assertEqual(review["status"], "needs_review")
        status, child = await self.request("POST", f"/v1/tasks/{task['id']}/regenerations", {}, "regen-child")
        self.assertEqual(status, 202, child)
        self.assertEqual(child["snapshot"]["consistency"], original_consistency)


if __name__ == "__main__":
    unittest.main()
