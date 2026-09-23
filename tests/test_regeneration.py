import tempfile
import unittest
import uuid
import hashlib
from pathlib import Path
from types import SimpleNamespace
from atelierx.core.store import Store
from atelierx.core.regeneration import Regeneration
from atelierx.core import generation_settings
from atelierx.common import ApiError, canonical
from atelierx.regeneration_contract import validate_changes

GEN = dict(diffusion_model="anima", text_encoder="encoder", vae="vae", width=512, height=512,
           seed=1, steps=24, cfg=4.5, sampler="euler", scheduler="normal", loras=[])

class RegenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "core.db"
        self.store = Store(self.path)
        w = self.store.create_entity("works", "w", None)
        c = self.store.create_entity("characters", "c", w["id"])
        o = self.store.create_entity("outfits", "o", c["id"], {})
        self.group = self.store.create_group(o["id"])
        self.bind()

    def bind(self):
        core = SimpleNamespace(store=self.store, validation=SimpleNamespace(freeze=lambda x: {"selection": x}, cancel=lambda x: None))
        self.engine = Regeneration(core, generation_settings)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def initial(self, limit=5, enabled=True):
        return self.store.create_task(str(uuid.uuid4()), "fp", self.group["id"], {
            "generation_inputs": dict(GEN, positive_prompt="blue eyes", negative_prompt=""),
            "settings": {"auto_regeneration_enabled": enabled, "max_auto_regenerations": limit},
            "validation": {"selection": {"provider_id": "local", "profile_id": "default"}}})

    def finish(self, task, outcome="failed", changes=True):
        image = {"id": str(uuid.uuid4()), "task_id": task["id"], "generation_image_id": str(uuid.uuid4())}
        self.store.finish_generation(task, [image])
        run = self.store.create_validation(image["id"], "auto:" + task["id"] + ":" + image["id"], "fp", {}, "local")
        proposals = [{"field": "steps", "value": task["snapshot"]["generation_inputs"]["steps"] + 1,
                      "reason": "Insufficient detail", "evidence_ids": ["p1"]}] if changes else []
        run.update(state="completed", outcome=outcome, result={"evidence": [{"id": "p1", "status": "mismatch"}], "regeneration": {"changes": proposals}})
        self.store.update_validation(run)
        self.engine.tick()
        return self.store.cycle(task["regeneration"]["cycle_id"])

    def test_budget_counts_started_only_once_and_survives_restart(self):
        first = self.initial(limit=2)
        cycle = self.finish(first)
        child = self.store.task(cycle["active_task_id"])
        self.assertEqual(cycle["used"], 0)
        self.store.charge_automatic_start(child["id"])
        self.store.update_task(child)  # stale snapshot must not erase charged marker
        self.store.close()
        self.store = Store(self.path)
        self.bind()
        self.store.charge_automatic_start(child["id"])
        self.assertEqual(self.store.cycle(cycle["id"])["used"], 1)
        cycle = self.finish(self.store.task(child["id"]))
        last = self.store.task(cycle["active_task_id"])
        self.store.charge_automatic_start(last["id"])
        cycle = self.finish(self.store.task(last["id"]))
        self.assertEqual((cycle["state"], cycle["used"]), ("limit_reached", 2))
        self.engine.tick()
        self.assertEqual(self.store.cycle(cycle["id"])["active_task_id"], last["id"])

    def test_errors_zero_and_disabled_stop(self):
        for outcome, changes, limit, enabled, expected in [
            ("error", True, 5, True, "error"), ("error", False, 5, True, "error"),
            ("failed", True, 0, True, "limit_reached"), ("failed", False, 0, True, "limit_reached"),
            ("failed", True, 5, False, "automatic_disabled"), ("passed", False, 5, True, "passed")]:
            with self.subTest(outcome=outcome, changes=changes, expected=expected):
                task = self.initial(limit, enabled)
                cycle = self.finish(task, outcome, changes)
                self.assertEqual((cycle["state"], cycle["used"], cycle["active_task_id"]), (expected, 0, task["id"]))

    def assert_seed_only(self, parent, cycle, reason):
        child = self.store.task(cycle["active_task_id"])
        self.assertNotEqual(child["id"], parent["id"])
        before, after = parent["snapshot"]["generation_inputs"], child["snapshot"]["generation_inputs"]
        self.assertNotEqual(after["seed"], before["seed"])
        self.assertTrue(0 <= after["seed"] < 2**53)
        self.assertEqual({k: v for k, v in after.items() if k != "seed"}, {k: v for k, v in before.items() if k != "seed"})
        self.assertEqual({k: v for k, v in child["snapshot"].items() if k != "generation_inputs"},
                         {k: v for k, v in parent["snapshot"].items() if k != "generation_inputs"})
        change = child["regeneration"]["change"]
        self.assertEqual(change, {"kind": "seed_only", "reason": reason, "previous_seed": before["seed"], "seed": after["seed"]})
        self.assertEqual(cycle["last_change"], dict(change, parent_task_id=parent["id"]))
        return child

    def test_failed_without_proposal_regenerates_with_new_seed_only(self):
        first = self.initial(limit=2)
        cycle = self.finish(first, changes=False)
        self.assertEqual(cycle["state"], "active")
        child = self.assert_seed_only(first, cycle, "proposal_unavailable")
        self.engine.tick()
        self.assertEqual(self.store.cycle(cycle["id"])["active_task_id"], child["id"])
        self.store.charge_automatic_start(child["id"])
        cycle = self.finish(self.store.task(child["id"]), changes=False)
        grandchild = self.assert_seed_only(self.store.task(child["id"]), cycle, "proposal_unavailable")
        self.store.charge_automatic_start(grandchild["id"])
        cycle = self.finish(self.store.task(grandchild["id"]), changes=False)
        self.assertEqual((cycle["state"], cycle["used"], cycle["active_task_id"]), ("limit_reached", 2, grandchild["id"]))

    def test_dropped_proposal_reason_is_recorded(self):
        task = self.initial()
        image = {"id": str(uuid.uuid4()), "task_id": task["id"], "generation_image_id": str(uuid.uuid4())}
        self.store.finish_generation(task, [image])
        run = self.store.create_validation(image["id"], "auto:" + task["id"] + ":" + image["id"], "fp", {}, "local")
        run.update(state="completed", outcome="failed", result={"evidence": [], "regeneration": {"changes": []},
                                                                "diagnostics": {"regeneration_proposal_dropped": "bad"}})
        self.store.update_validation(run)
        self.engine.tick()
        self.assert_seed_only(self.store.task(task["id"]), self.store.cycle(task["id"]), "proposal_dropped")

    def test_seed_only_choice_is_reused_for_the_same_parent(self):
        task = self.initial()
        cycle = self.store.cycle(task["id"])
        first = self.engine.seed_only(cycle, task, "proposal_unavailable")
        self.store.update_cycle(cycle, last_change=dict(first, parent_task_id=task["id"]))
        self.assertEqual(self.engine.seed_only(self.store.cycle(task["id"]), task, "proposal_invalid"), first)

    def test_attempt_with_two_outputs_waits_for_representative_only(self):
        task = self.initial()
        webp = {"id": str(uuid.uuid4()), "task_id": task["id"], "generation_image_id": str(uuid.uuid4()), "media_type": "image/webp"}
        png = dict(webp, id=str(uuid.uuid4()), generation_image_id=str(uuid.uuid4()), media_type="image/png")
        self.store.finish_generation(task, [webp, png])
        run = self.store.create_validation(png["id"], "auto:" + task["id"] + ":" + png["id"], "fp", {}, "local", [webp["id"]])
        run.update(state="completed", outcome="passed", result={"evidence": []})
        self.store.update_validation(run)
        shared = self.store.image(webp["id"])["validation"]
        self.assertEqual((shared["id"], shared["outcome"], shared["shared_from_image_id"]), (run["id"], "passed", png["id"]))
        validation = self.store.task(task["id"])["validation"]
        self.assertEqual(validation["representative_image_id"], png["id"])
        self.assertEqual(validation["images"], [
            {"image_id": webp["id"], "state": "completed", "outcome": "passed", "shared_from_image_id": png["id"]},
            {"image_id": png["id"], "state": "completed", "outcome": "passed"}])
        self.engine.tick()
        self.assertEqual(self.store.cycle(task["id"])["state"], "passed")

    def test_manual_run_on_shared_image_applies_to_that_image_only(self):
        task = self.initial()
        png = {"id": str(uuid.uuid4()), "task_id": task["id"], "generation_image_id": str(uuid.uuid4()), "media_type": "image/png"}
        webp = dict(png, id=str(uuid.uuid4()), generation_image_id=str(uuid.uuid4()), media_type="image/webp")
        self.store.finish_generation(task, [png, webp])
        auto = self.store.create_validation(png["id"], "auto:" + task["id"] + ":" + png["id"], "fp", {}, "local", [webp["id"]])
        manual = self.store.create_validation(webp["id"], "manual-webp", "fp", {}, "local")
        manual.update(state="completed", outcome="failed", result={"evidence": []})
        self.store.update_validation(manual)
        auto.update(state="completed", outcome="passed", result={"evidence": []})
        self.store.update_validation(auto)
        self.assertEqual(self.store.image(webp["id"])["validation"]["id"], manual["id"])
        self.assertNotIn("shared_from_image_id", self.store.image(webp["id"])["validation"])
        self.assertEqual(self.store.image(png["id"])["validation"]["outcome"], "passed")
        self.engine.tick()
        self.assertEqual(self.store.cycle(task["id"])["state"], "passed")

    def test_legacy_attempt_with_two_runs_keeps_per_output_evaluation(self):
        task = self.initial()
        png = {"id": str(uuid.uuid4()), "task_id": task["id"], "generation_image_id": str(uuid.uuid4()), "media_type": "image/png"}
        webp = dict(png, id=str(uuid.uuid4()), generation_image_id=str(uuid.uuid4()), media_type="image/webp")
        self.store.finish_generation(task, [png, webp])
        runs = [self.store.create_validation(image["id"], "auto:" + task["id"] + ":" + image["id"], "fp", {}, "local") for image in (png, webp)]
        runs[0].update(state="completed", outcome="passed", result={"evidence": []})
        self.store.update_validation(runs[0])
        self.engine.tick()
        self.assertEqual(self.store.cycle(task["id"])["active_task_id"], task["id"])
        runs[1].update(state="completed", outcome="failed", result={"evidence": [], "regeneration": {"changes": []}})
        self.store.update_validation(runs[1])
        self.assertEqual(self.store.image(png["id"])["validation"]["outcome"], "passed")
        self.engine.tick()
        cycle = self.store.cycle(task["id"])
        child = self.assert_seed_only(self.store.task(task["id"]), cycle, "proposal_unavailable")
        self.assertEqual(child["regeneration"]["source_run_ids"], [runs[1]["id"]])

    def test_stop_queued_auto_does_not_charge_and_manual_gets_new_budget(self):
        first = self.initial()
        cycle = self.finish(first)
        child = self.store.task(cycle["active_task_id"])
        self.engine.stop(cycle["id"])
        self.assertEqual(self.store.task(child["id"])["state"], "cancelled")
        self.assertEqual(self.store.cycle(cycle["id"])["used"], 0)
        self.store.update_settings(1, {"max_auto_regenerations": 7})
        manual, created = self.engine.manual(child["id"], "manual", {})
        new = self.store.cycle(manual["regeneration"]["cycle_id"])
        self.assertTrue(created)
        self.assertEqual((new["used"], new["limit"]), (0, 7))
        self.assertEqual(manual["snapshot"]["generation_inputs"]["positive_prompt"], "blue eyes")
        self.assertEqual(self.engine.manual(child["id"], "manual", {})[0]["id"], manual["id"])

    def test_proposals_require_failed_evidence_and_valid_values(self):
        proposal = {"field": "steps", "value": 30, "reason": "detail missing", "evidence_ids": ["p1"]}
        for change, evidence in [(proposal, []), (dict(proposal, value=101), [{"id": "p1", "status": "mismatch"}]),
                                 (dict(proposal, field="positive_prompt"), [{"id": "p1", "status": "mismatch"}])]:
            with self.assertRaises(ApiError): validate_changes([change], evidence, GEN)

    def test_started_failure_and_cancel_remain_charged(self):
        for state in ("failed", "cancelled"):
            first = self.initial()
            cycle = self.finish(first)
            child = self.store.task(cycle["active_task_id"])
            self.store.charge_automatic_start(child["id"])
            child["state"] = state
            self.store.update_task(child)
            self.engine.tick()
            result = self.store.cycle(cycle["id"])
            self.assertEqual(result["used"], 1)
            self.assertEqual(result["state"], "error" if state == "failed" else "cancelled")

    def test_invalid_proposal_falls_back_to_seed_only(self):
        first = self.initial()
        first["snapshot"]["generation_inputs"]["steps"] = 100
        self.store.update_task(first)
        cycle = self.finish(first)
        self.assertEqual(cycle["state"], "active")
        self.assert_seed_only(self.store.task(first["id"]), cycle, "proposal_invalid")

    def test_valid_proposal_records_proposal_change(self):
        first = self.initial()
        cycle = self.finish(first)
        child = self.store.task(cycle["active_task_id"])
        self.assertEqual(child["regeneration"]["change"], {"kind": "proposal", "fields": ["steps"]})
        self.assertEqual(child["snapshot"]["generation_inputs"]["seed"], first["snapshot"]["generation_inputs"]["seed"])
        self.assertEqual(child["snapshot"]["generation_inputs"]["steps"], 25)

    def test_legacy_manual_key_fingerprint_remains_idempotent_without_frozen_snapshot(self):
        source = self.initial()
        self.finish(source, outcome="passed", changes=False)
        key, body = "legacy-manual-key", {}
        legacy_fingerprint = hashlib.sha256(canonical({"regeneration_of": source["id"], "body": body}).encode()).hexdigest()
        legacy = self.store.create_task(key, legacy_fingerprint, self.group["id"], source["snapshot"])
        found, created = self.engine.manual(source["id"], key, body)
        self.assertFalse(created)
        self.assertEqual(found["id"], legacy["id"])
