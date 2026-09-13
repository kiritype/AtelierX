import tempfile
import unittest
import uuid
import hashlib
from pathlib import Path
from types import SimpleNamespace
from atelierx.core_store import Store
from atelierx.core_regeneration import Regeneration
from atelierx.core import generation_settings
from atelierx.common import ApiError, canonical
from atelierx.regeneration_contract import validate_changes

GEN = dict(diffusion_model="anima", text_encoder="encoder", vae="vae", width=512, height=512,
           seed=1, steps=24, cfg=4.5, sampler="euler", scheduler="normal")

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

    def test_errors_missing_proposal_zero_and_disabled_stop(self):
        for outcome, changes, limit, enabled, expected in [
            ("error", True, 5, True, "error"), ("failed", False, 5, True, "proposal_unavailable"),
            ("failed", True, 0, True, "limit_reached"), ("failed", True, 5, False, "automatic_disabled"),
            ("passed", False, 5, True, "passed")]:
            with self.subTest(expected=expected):
                cycle = self.finish(self.initial(limit, enabled), outcome, changes)
                self.assertEqual((cycle["state"], cycle["used"]), (expected, 0))

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

    def test_invalid_proposal_stops_without_partial_child(self):
        first = self.initial()
        first["snapshot"]["generation_inputs"]["steps"] = 100
        self.store.update_task(first)
        cycle = self.finish(first)
        self.assertEqual(cycle["state"], "error")
        self.assertEqual(cycle["error_code"], "VAL_REGENERATION_PROPOSAL_INVALID")
        self.assertEqual(cycle["active_task_id"], first["id"])

    def test_legacy_manual_key_fingerprint_remains_idempotent_without_frozen_snapshot(self):
        source = self.initial()
        self.finish(source, outcome="passed", changes=False)
        key, body = "legacy-manual-key", {}
        legacy_fingerprint = hashlib.sha256(canonical({"regeneration_of": source["id"], "body": body}).encode()).hexdigest()
        legacy = self.store.create_task(key, legacy_fingerprint, self.group["id"], source["snapshot"])
        found, created = self.engine.manual(source["id"], key, body)
        self.assertFalse(created)
        self.assertEqual(found["id"], legacy["id"])
