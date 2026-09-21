import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import canonical
from atelierx.core import CORE, create_app


PARTS = {
    "appearance": "blue eyes and silver hair",
    "upper": "white shirt",
    "lower": "black boots",
}
PROFILE = {"profile_id": "group", "revision": 1, "consistency": True}
SINGLE_PROFILE = {"profile_id": "single", "revision": 1, "consistency": False}
PROVIDER = {"provider_id": "vision", "revision": 1, "model": "fixture", "timeout_seconds": 2}


class CoreGroupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs, self.posts, self.cancelled = {}, [], []
        self.mode = "matched"
        provider = web.Application()

        async def submit(request):
            payload = await request.json()
            key = request.headers["Idempotency-Key"]
            self.posts.append(payload)
            job = {
                "job_id": str(uuid.uuid4()),
                "state": "queued",
                "request": payload,
                "outcome": None,
                "result": None,
                "error": None,
            }
            self.jobs[key] = job
            return web.json_response(job, status=202)

        async def by_key(request):
            job = self.jobs.get(request.headers.get("Idempotency-Key"))
            return web.json_response(job or {}, status=200 if job else 404)

        async def detail(request):
            job = next((item for item in self.jobs.values() if item["job_id"] == request.match_info["id"]), None)
            if job is None:
                return web.json_response({}, status=404)
            if job["job_id"] in self.cancelled:
                job.update(state="cancelled", outcome=None, result=None, error=None)
            elif self.mode == "pending":
                job.update(state="running")
            else:
                job.update(state="completed", outcome=None, result=self.result_for(job["request"]), error=None)
            return web.json_response(job)

        async def cancel(request):
            self.cancelled.append(request.match_info["id"])
            return web.json_response({"accepted": True})

        provider.add_routes([
            web.post("/v1/validations/group", submit),
            web.get("/v1/validation-jobs/by-key", by_key),
            web.get("/v1/validation-jobs/{id}", detail),
            web.post("/v1/validation-jobs/{id}/cancel", cancel),
        ])
        self.provider = TestServer(provider)
        await self.provider.start_server()
        self.config = {
            "url": str(self.provider.make_url("/")),
            "profiles": {"group": PROFILE, "single": SINGLE_PROFILE},
            "providers": {"vision": PROVIDER},
        }
        self.client = await self.new_client()
        self.group, self.images = self.create_group_images()
        self.other_group, self.other_images = self.create_group_images()

    async def asyncTearDown(self):
        await self.client.close()
        await self.provider.close()
        self.tmp.cleanup()

    async def new_client(self):
        client = TestClient(TestServer(create_app(
            Path(self.tmp.name) / "core.sqlite3",
            "http://generation.fixture",
            "core-token",
            poll=.005,
            validation_config=self.config,
            validation_token="validation-token",
        )))
        await client.start_server()
        return client

    def create_group_images(self):
        store = self.client.app[CORE].store
        work = store.create_entity("works", "work", None)
        character = store.create_entity("characters", "character", work["id"])
        outfit = store.create_entity("outfits", "outfit", character["id"], PARTS)
        group = store.create_group(outfit["id"])
        images = []
        for index in range(4):
            task = store.create_task(
                f"generation-{group['id']}-{index}",
                f"fingerprint-{index}",
                group["id"],
                {
                    "generation_endpoint": "http://generation.fixture",
                    "generation_inputs": {
                        "positive_prompt": f"portrait {index}",
                        "negative_prompt": "blur",
                        "diffusion_model": "anima.safetensors", "text_encoder": "qwen.safetensors", "vae": "vae.safetensors",
                        "width": 512, "height": 512, "seed": index, "steps": 24, "cfg": 4.5,
                        "sampler": "euler_ancestral", "scheduler": "normal", "loras": [],
                    },
                },
            )
            data = f"image-{group['id']}-{index}".encode()
            image = {
                "id": str(uuid.uuid4()),
                "task_id": task["id"],
                "group_id": group["id"],
                "generation_image_id": str(uuid.uuid4()) + "-0",
                "sha256": hashlib.sha256(data).hexdigest(),
                "media_type": "image/png",
                "bytes": len(data),
                "validation_state": "completed",
                "validation": {"outcome": "passed"},
            }
            store.finish_generation(task, [image])
            with store.db:
                store.db.execute("UPDATE images SET document=? WHERE id=?", (canonical(image), image["id"]))
            images.append(image)
        return group, images

    def result_for(self, request):
        references = [request["representative"]["ref"], *[item["ref"] for item in request["auxiliaries"]]]
        items = []
        for index, target in enumerate(request["targets"]):
            if self.mode == "partial" and index == 1:
                items.append({"image_ref": target["ref"], "status": "error", "error": {"code": "VAL_PROVIDER_RESPONSE_INVALID"}})
                continue
            if self.mode == "reference_conflict":
                evidence = []
                for feature in request["identity"]:
                    if feature == "appearance":
                        evidence.append({"feature": feature, "status": "reference_conflict",
                                         "reference_observed": {references[0]: "Visible short hair", references[1]: "Visible long hair"},
                                         "target_observed": "Not compared due to reference conflict",
                                         "differences": [{"attribute": "hair_length", "description": "Reference hair lengths differ"}],
                                         "reference_refs": references})
                    else:
                        evidence.append({"feature": feature, "status": "insufficient", "reference_observed": {},
                                         "target_observed": "Not compared due to reference conflict", "differences": [], "reference_refs": []})
                items.append({"image_ref": target["ref"], "status": "reference_conflict", "evidence": evidence,
                              "reference_evidence": [{"reference_refs": references, "evidence": []}],
                              "target_not_compared": True, "error": None})
                continue
            evidence = [
                {"feature": feature, "status": "matched", "reference_observed": {ref: f"Visible {feature} in {ref}" for ref in references}, "target_observed": f"Visible {feature} in target", "differences": [], "reference_refs": references}
                for feature in request["identity"]
            ]
            items.append({"image_ref": target["ref"], "status": "matched", "evidence": evidence, "error": None})
        return {"items": items}

    async def request(self, method, path, body=None, key=None):
        headers = {"Authorization": "Bearer core-token"}
        if key:
            headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        return response.status, await response.json()

    async def reference(self, revision=0, representative=None, auxiliaries=None):
        return await self.request(
            "PUT",
            f"/v1/groups/{self.group['id']}/reference",
            {
                "revision": revision,
                "representative_id": representative or self.images[0]["id"],
                "auxiliary_ids": [self.images[1]["id"]] if auxiliaries is None else auxiliaries,
            },
        )

    async def submit(self, target_ids, key="group-key", revision=1):
        return await self.request(
            "POST",
            f"/v1/groups/{self.group['id']}/validations",
            {
                "reference_revision": revision,
                "target_ids": target_ids,
                "validation": {"profile_id": "group", "provider_id": "vision"},
            },
            key,
        )

    async def wait_run(self, run_id, states={"completed", "failed", "cancelled"}):
        for _ in range(200):
            _, run = await self.request("GET", "/v1/group-validation-runs/" + run_id)
            if run["state"] in states:
                return run
            await asyncio.sleep(.01)
        self.fail(run)

    async def test_reference_requires_current_revision_and_single_passed_group_images(self):
        status, reference = await self.reference()
        self.assertEqual((status, reference["reference"]["revision"]), (200, 1))
        self.assertEqual((await self.reference())[0], 409)

        failed = self.images[3]
        failed["validation"] = {"outcome": "failed"}
        store = self.client.app[CORE].store
        with store.db:
            store.db.execute("UPDATE images SET document=? WHERE id=?", (canonical(failed), failed["id"]))
        self.assertEqual((await self.reference(1, failed["id"], []))[0], 409)
        self.assertEqual((await self.reference(1, self.other_images[0]["id"], []))[0], 409)

    async def test_selected_targets_and_idempotency_preserve_the_frozen_request(self):
        await self.reference()
        target = self.images[2]["id"]
        status, run = await self.submit([target])
        self.assertEqual(status, 202)
        self.assertEqual([item["ref"] for item in run["request"]["targets"]], [target])
        status, repeated = await self.submit([target])
        self.assertEqual((status, repeated["id"]), (200, run["id"]))
        self.assertEqual((await self.submit([self.images[3]["id"]]))[0], 409)

    async def test_partial_target_error_is_preserved_after_core_restart(self):
        await self.reference()
        self.mode = "partial"
        _, run = await self.submit([self.images[2]["id"], self.images[3]["id"]])
        completed = await self.wait_run(run["id"])
        self.assertEqual((completed["state"], completed["outcome"]), ("completed", "incomplete"))
        self.assertEqual([item["status"] for item in completed["result"]["items"]], ["matched", "error"])
        self.assertEqual(completed["result"]["items"][1]["error"]["code"], "VAL_PROVIDER_RESPONSE_INVALID")
        await self.client.close()
        self.client = await self.new_client()
        _, restored = await self.request("GET", "/v1/group-validation-runs/" + run["id"])
        self.assertEqual(restored["result"], completed["result"])

    async def test_reference_precheck_conflict_evidence_is_accepted_by_core(self):
        await self.reference()
        self.mode = "reference_conflict"
        _, run = await self.submit([self.images[2]["id"]])
        completed = await self.wait_run(run["id"])
        item = completed["result"]["items"][0]
        self.assertEqual((completed["state"], completed["outcome"], item["status"]), ("completed", "incomplete", "reference_conflict"))
        self.assertEqual(item["evidence"][0]["target_observed"], "Not compared due to reference conflict")

    async def test_reference_change_marks_running_result_noncurrent_and_status_tracks_targets(self):
        await self.reference()
        self.mode = "pending"
        _, run = await self.submit([self.images[2]["id"]])
        pending = await self.wait_run(run["id"], {"pending"})
        self.assertEqual(pending["current_reference"], True)
        _, changed = await self.reference(1, self.images[1]["id"], [self.images[0]["id"]])
        self.assertEqual(changed["reference"]["revision"], 2)
        _, stale = await self.request("GET", "/v1/group-validation-runs/" + run["id"])
        self.assertFalse(stale["current_reference"])
        _, consistency = await self.request("GET", f"/v1/groups/{self.group['id']}/consistency")
        self.assertEqual((consistency["state"], consistency["counts"]["unvalidated"]), ("incomplete", 2))
        self.assertEqual(set(consistency["target_ids"]), {self.images[2]["id"], self.images[3]["id"]})

    async def test_cancelled_pending_run_survives_restart_without_resubmission(self):
        await self.reference()
        self.mode = "pending"
        _, run = await self.submit([self.images[2]["id"]], "cancel-key")
        pending = await self.wait_run(run["id"], {"pending"})
        status, cancelling = await self.request("POST", "/v1/group-validation-runs/" + run["id"] + "/cancel")
        self.assertEqual((status, cancelling["state"]), (200, "pending"))
        cancelled = await self.wait_run(run["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(self.cancelled, [pending["job_id"]])
        post_count = len(self.posts)
        await self.client.close()
        self.client = await self.new_client()
        await asyncio.sleep(.03)
        _, restored = await self.request("GET", "/v1/group-validation-runs/" + run["id"])
        self.assertEqual(restored["state"], "cancelled")
        self.assertEqual(len(self.posts), post_count)

    def set_evidence(self, image, requirements):
        image["validation"] = {"outcome": "passed", "result": {"evidence": [
            {"status": "matched", "requirement": requirement, "source_clause": requirement,
             "observed": "visible " + requirement, "location": "portrait"}
            for requirement in requirements
        ]}}
        store = self.client.app[CORE].store
        with store.db:
            store.db.execute("UPDATE images SET document=? WHERE id=?", (canonical(image), image["id"]))

    async def test_reference_candidate_uses_visible_evidence_fixed_tie_break_and_never_replaces_reference(self):
        # These candidates tie on every quality term.  The persisted creation/id
        # key is the stable final key rather than incidental database order.
        self.set_evidence(self.images[2], [PARTS["appearance"], PARTS["upper"], PARTS["lower"]])
        self.set_evidence(self.images[3], [PARTS["appearance"], PARTS["upper"], PARTS["lower"]])
        status, proposal = await self.request("GET", f"/v1/groups/{self.group['id']}/reference-candidate")
        self.assertEqual(status, 200)
        self.assertEqual((proposal["state"], proposal["representative_id"]), ("ready_for_confirmation", min(self.images[2]["id"], self.images[3]["id"])))
        self.assertEqual(proposal["missing_components"], [])
        self.assertIn("creation time", proposal["reason"])
        await self.reference(0, self.images[0]["id"], [])
        _, retained = await self.request("GET", f"/v1/groups/{self.group['id']}/reference-candidate")
        self.assertEqual((retained["state"], retained["reference"]["representative_id"]),
                         ("existing_reference_retained", self.images[0]["id"]))

    async def test_reference_candidate_reports_insufficient_visibility(self):
        self.set_evidence(self.images[2], [PARTS["appearance"]])
        _, proposal = await self.request("GET", f"/v1/groups/{self.group['id']}/reference-candidate")
        self.assertEqual(proposal["state"], "insufficient_reference_evidence")
        self.assertEqual(set(proposal["missing_components"]), {"upper", "lower"})

    async def test_reference_candidate_does_not_require_empty_identity_component(self):
        group = self.client.app[CORE].store.group(self.group["id"])
        group["components"]["lower"] = ""
        with self.client.app[CORE].store.db:
            self.client.app[CORE].store.db.execute("UPDATE groups SET document=? WHERE id=?", (canonical(group), group["id"]))
        self.set_evidence(self.images[2], [PARTS["appearance"], PARTS["upper"]])
        status, proposal = await self.request("GET", f"/v1/groups/{self.group['id']}/reference-candidate")
        self.assertEqual(status, 200)
        self.assertEqual((proposal["state"], proposal["missing_components"]), ("ready_for_confirmation", []))
        self.assertEqual(set(proposal["covered_components"]), {"appearance", "upper"})

    async def test_selected_replacement_freezes_reference_and_only_supersedes_selected_target(self):
        # The selected PNG belongs to an original PNG/WebP pair.  Selecting the
        # PNG must not erase its existing WebP sibling from current targets.
        core = self.client.app[CORE]
        source_task = core.store.task(self.images[2]["task_id"])
        sibling_data = b"original-webp"
        sibling = {"id": str(uuid.uuid4()), "task_id": source_task["id"], "group_id": self.group["id"],
                   "generation_image_id": str(uuid.uuid4()) + "-1", "generation_job_id": source_task["generation_job_id"],
                   "sha256": hashlib.sha256(sibling_data).hexdigest(), "bytes": len(sibling_data), "media_type": "image/webp",
                   "validation_state": "completed", "validation": {"outcome": "passed", "result": {"evidence": []}}}
        source_task["images"].append(sibling)
        with core.store.db:
            core.store.db.execute("INSERT INTO images VALUES(?,?,?,?)", (sibling["id"], sibling["task_id"], sibling["generation_image_id"], canonical(sibling)))
            core.store.db.execute("UPDATE tasks SET document=? WHERE id=?", (canonical(source_task), source_task["id"]))
        await self.reference(0, self.images[0]["id"], [self.images[1]["id"]])
        status, replacement = await self.request("POST", f"/v1/groups/{self.group['id']}/replacements", {
            "reference_revision": 1, "target_image_id": self.images[2]["id"],
            "regeneration": {"validation": {"profile_id": "single", "provider_id": "vision"}},
            "group_validation": {"profile_id": "group", "provider_id": "vision"},
        }, "replacement-key")
        self.assertEqual(status, 202)
        self.assertEqual(replacement["reference"]["revision"], 1)
        self.assertEqual(replacement["source_image_id"], self.images[2]["id"])
        self.assertEqual(replacement["state"], "generation_pending")
        # The same request cannot create another generation after a restart/key retry.
        status, repeated = await self.request("POST", f"/v1/groups/{self.group['id']}/replacements", {
            "reference_revision": 1, "target_image_id": self.images[2]["id"],
            "regeneration": {"validation": {"profile_id": "single", "provider_id": "vision"}},
            "group_validation": {"profile_id": "group", "provider_id": "vision"},
        }, "replacement-key")
        self.assertEqual((status, repeated["id"]), (200, replacement["id"]))
        # Complete only the matching PNG derivative, mark its single decision
        # passed, then let the durable replacement state submit exactly that new
        # image for a frozen-reference group comparison.
        replacement_task = core.store.task(replacement["replacement_task_id"])
        data = b"replacement-png"
        replacement_image = {"id": str(uuid.uuid4()), "task_id": replacement_task["id"], "group_id": self.group["id"],
                             "generation_image_id": str(uuid.uuid4()) + "-0", "generation_job_id": str(uuid.uuid4()),
                             "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "media_type": "image/png",
                             "validation_state": "completed", "validation": {"id": "fixture-single", "state": "completed", "outcome": "passed", "error": None, "result": {"evidence": []}}}
        webp = dict(replacement_image, id=str(uuid.uuid4()), generation_image_id=str(uuid.uuid4()) + "-1", media_type="image/webp")
        core.store.finish_generation(core.store.task(replacement_task["id"]), [replacement_image, webp])
        for image in (replacement_image, webp):
            run = core.store.create_validation(image["id"], "auto:" + replacement_task["id"] + ":" + image["id"], "fixture-pass-" + image["id"], {}, self.config["url"])
            run.update(state="completed", outcome="passed", error=None, result={"evidence": []})
            core.store.update_validation(run)
        await core.groups.tick(); await core.groups.tick()
        waiting = core.groups.replacement_get(replacement["id"])
        self.assertEqual((waiting["state"], waiting["group_run_id"]), ("single_validation_pending", None))
        core.store.update_cycle(core.store.cycle(replacement_task["regeneration"]["cycle_id"]), state="passed", reason="fixture passed")
        # This is a config edit after request acceptance.  The durable frozen
        # group profile remains revision 1 when the group job is built.
        core.validation.config["profiles"]["group"] = {"profile_id": "group", "revision": 99, "consistency": True}
        await core.groups.tick()
        await core.groups.tick()
        linked = core.groups.replacement_get(replacement["id"])
        self.assertEqual((linked["state"], linked["replacement_image_id"]), ("group_validation_pending", replacement_image["id"]))
        linked_run = core.groups.get(linked["group_run_id"])
        self.assertEqual([item["ref"] for item in linked_run["request"]["targets"]], [replacement_image["id"]])
        self.assertEqual(linked_run["request"]["profile"]["revision"], 1)
        self.assertNotIn(webp["id"], core.groups.current_target_ids(self.group["id"]))
        posts = len(self.posts)
        await core.groups.tick()
        self.assertEqual(len(self.posts), posts)  # retry/poll cannot duplicate the group request
        _, consistency = await self.request("GET", f"/v1/groups/{self.group['id']}/consistency")
        self.assertNotIn(self.images[2]["id"], consistency["target_ids"])
        self.assertIn(sibling["id"], consistency["target_ids"])
        self.assertIn(self.images[3]["id"], consistency["target_ids"])
        # A changed reference makes a stale confirmation fail before another task is made.
        await self.reference(1, self.images[1]["id"], [self.images[0]["id"]])
        stale, _ = await self.request("POST", f"/v1/groups/{self.group['id']}/replacements", {
            "reference_revision": 1, "target_image_id": self.images[3]["id"], "regeneration": {"validation": {"profile_id": "single", "provider_id": "vision"}},
            "group_validation": {"profile_id": "group", "provider_id": "vision"},
        }, "replacement-stale")
        self.assertEqual(stale, 409)

    async def test_replacement_restart_does_not_create_a_second_task(self):
        await self.reference(0, self.images[0]["id"], [self.images[1]["id"]])
        _, replacement = await self.request("POST", f"/v1/groups/{self.group['id']}/replacements", {
            "reference_revision": 1, "target_image_id": self.images[2]["id"],
            "regeneration": {"validation": {"profile_id": "single", "provider_id": "vision"}},
            "group_validation": {"profile_id": "group", "provider_id": "vision"},
        }, "replacement-restart")
        before = self.client.app[CORE].store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        await self.client.close()
        self.client = await self.new_client()
        await asyncio.sleep(.03)
        after = self.client.app[CORE].store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        _, saved = await self.request("GET", f"/v1/groups/{self.group['id']}/replacements")
        self.assertEqual((before, after), (9, 9))
        self.assertEqual([item["id"] for item in saved["items"]], [replacement["id"]])

    async def test_replacement_follows_single_validation_automatic_descendant(self):
        await self.reference(0, self.images[0]["id"], [self.images[1]["id"]])
        _, replacement = await self.request("POST", f"/v1/groups/{self.group['id']}/replacements", {
            "reference_revision": 1, "target_image_id": self.images[2]["id"],
            "regeneration": {"validation": {"profile_id": "single", "provider_id": "vision"}},
            "group_validation": {"profile_id": "group", "provider_id": "vision"},
        }, "replacement-auto-child")
        core = self.client.app[CORE]
        manual = core.store.task(replacement["replacement_task_id"])
        failed = {"id": str(uuid.uuid4()), "task_id": manual["id"], "group_id": self.group["id"], "generation_image_id": str(uuid.uuid4()) + "-0",
                  "generation_job_id": str(uuid.uuid4()), "sha256": hashlib.sha256(b"failed").hexdigest(), "bytes": 6, "media_type": "image/png", "validation_state": "not_requested"}
        core.store.finish_generation(manual, [failed])
        run = core.store.create_validation(failed["id"], "auto:" + manual["id"] + ":" + failed["id"], "fixture-failed", {}, self.config["url"])
        run.update(state="completed", outcome="failed", error=None, result={"findings": []})
        core.store.update_validation(run)
        cycle_id = manual["regeneration"]["cycle_id"]
        child = core.store.create_task("fixture-auto-child", "fixture-auto-child", self.group["id"], manual["snapshot"], {
            "kind": "automatic", "parent_task_id": manual["id"], "lineage_id": manual["regeneration"]["lineage_id"], "cycle_id": cycle_id, "source_run_ids": [run["id"]],
        })
        await core.groups.tick(); await core.groups.tick()
        followed = core.groups.replacement_get(replacement["id"])
        self.assertEqual((followed["state"], followed["replacement_task_id"]), ("generation_pending", child["id"]))
        data = b"auto-child"
        image = {"id": str(uuid.uuid4()), "task_id": child["id"], "group_id": self.group["id"], "generation_image_id": str(uuid.uuid4()) + "-0",
                 "generation_job_id": str(uuid.uuid4()), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "media_type": "image/png", "validation_state": "not_requested"}
        core.store.finish_generation(core.store.task(child["id"]), [image])
        passed = core.store.create_validation(image["id"], "auto:" + child["id"] + ":" + image["id"], "fixture-child-pass", {}, self.config["url"])
        passed.update(state="completed", outcome="passed", error=None, result={"evidence": []})
        core.store.update_validation(passed)
        core.store.update_cycle(core.store.cycle(cycle_id), state="passed", reason="fixture child passed")
        await core.groups.tick(); await core.groups.tick()
        linked = core.groups.replacement_get(replacement["id"])
        self.assertEqual(linked["state"], "group_validation_pending")
        self.assertEqual([target["ref"] for target in core.groups.get(linked["group_run_id"])["request"]["targets"]], [image["id"]])
        self.assertNotIn(failed["id"], core.groups.current_target_ids(self.group["id"]))

    async def test_creating_replacement_checks_changed_reference_before_task_creation(self):
        await self.reference(0, self.images[0]["id"], [self.images[1]["id"]])
        core = self.client.app[CORE]
        record = {"id": str(uuid.uuid4()), "group_id": self.group["id"], "request_key": "creating-stale", "created_at": 1,
                  "state": "creating", "reference": {"revision": 1, "representative_id": self.images[0]["id"], "auxiliary_ids": [self.images[1]["id"]]},
                  "source_image_id": self.images[2]["id"], "source_task_id": self.images[2]["task_id"], "replacement_task_id": None,
                  "source_generation_image_id": self.images[2]["generation_image_id"], "source_sha256": self.images[2]["sha256"], "source_media_type": self.images[2]["media_type"],
                  "regeneration": {}, "replacement_snapshot": {}, "group_validation": {"profile_id": "group", "provider_id": "vision"}, "group_validation_frozen": core.validation.freeze({"profile_id": "group", "provider_id": "vision"})}
        await self.reference(1, self.images[1]["id"], [self.images[0]["id"]])
        before = core.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        with core.store.db:
            core.store.db.execute("INSERT INTO group_replacements VALUES(?,?,?,?)", (record["id"], record["request_key"], "fixture", canonical(record)))
        core.groups.advance_replacement(record)
        after = core.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        saved = core.groups.replacement_get(record["id"])
        self.assertEqual((saved["state"], saved["error"]["code"], before, after), ("stale_reference", "CORE_GROUP_STALE", 8, 8))
        self.assertIn(self.images[2]["id"], core.groups.current_target_ids(self.group["id"]))


if __name__ == "__main__":
    unittest.main()
