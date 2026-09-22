from __future__ import annotations

import copy
import asyncio
import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from atelierx.common import ApiError, canonical
from atelierx.core_production_plans import ProductionPlans, WINDOW
from atelierx.core_store import Store


class FakeValidation:
    def freeze(self, selection):
        return {"selection": dict(selection), "profile": {"profile_id": selection["profile_id"], "consistency": selection["profile_id"] == "group"}, "provider": {"provider_id": selection["provider_id"]}}

    freeze_group = freeze

    def cancel(self, run_id):
        return None


class FakeGroups:
    def __init__(self):
        self.calls, self.runs, self.cancelled = [], {}, []

    def submit(self, group_id, key, body, frozen):
        run = {"id": str(uuid.uuid4()), "state": "queued", "outcome": None, "error": None}
        self.calls.append((group_id, key, copy.deepcopy(body), copy.deepcopy(frozen), run["id"]))
        self.runs[run["id"]] = run
        return run, True

    def get(self, run_id):
        return self.runs[run_id]

    def runs_with_key_prefix(self, prefix):
        return [dict(run, request_key=key) for _, key, _, _, run_id in self.calls if key.startswith(prefix)
                for run in [self.runs[run_id]]]

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        self.runs[run_id]["state"] = "cancelled"


class FakeBatches:
    def _observe_item(self, item):
        # These tests intentionally leave dispatched work pending.
        return None


class FakeRegeneration:
    def __init__(self, store):
        self.store = store

    def stop(self, cycle_id):
        cycle = self.store.cycle(cycle_id)
        task = self.store.task(cycle["active_task_id"])
        task["state"] = "cancelled"
        self.store.update_task(task)
        self.store.update_cycle(cycle, state="cancelled", reason="test cancellation")


class ProductionPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "core.sqlite3")
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        outfit = self.store.create_entity("outfits", "outfit", character["id"], {"appearance": "hair", "upper": "shirt", "lower": "boots"})
        self.group = self.store.create_group(outfit["id"])
        self.validation, self.groups = FakeValidation(), FakeGroups()
        self.core = SimpleNamespace(store=self.store, validation=self.validation, groups=self.groups,
                                    batches=FakeBatches(), regeneration=FakeRegeneration(self.store))
        self.core.preview = self.preview
        self.plans = ProductionPlans(self.core)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def reference(self, revision=1):
        group = self.store.group(self.group["id"])
        group["reference"] = {"revision": revision, "representative_id": "reference-image", "auxiliary_ids": []}
        with self.store.db:
            self.store.db.execute("UPDATE groups SET document=? WHERE id=?", (canonical(group), group["id"]))
        return group["reference"]

    def preview(self, payload):
        selection = payload["fragment"]
        if selection["id"] == "invalid":
            raise ApiError("CORE_REVISION_CONFLICT", "fragment changed", 409)
        snapshot = {
            "generation_endpoint": "http://generation.fixture",
            "generation_inputs": {"positive_prompt": "portrait " + selection["id"], "negative_prompt": "",
                                  "seed": payload.get("generation_inputs", {}).get("seed", 7)},
            "fragment": {"id": selection["id"], "revision": selection["revision"], "body": "frozen " + selection["id"], "include": {"upper": True, "lower": False}},
        }
        if "validation" in payload:
            snapshot["validation"] = self.validation.freeze(payload["validation"])
        if "common_fragments" in payload:
            snapshot["common_fragments"] = copy.deepcopy(payload["common_fragments"])
        return {"snapshot": snapshot, "preview_hash": hashlib.sha256(canonical(snapshot).encode()).hexdigest()}

    def body(self, count=2):
        return {
            "group_id": self.group["id"],
            "fragments": [{"id": "fragment-" + str(index), "revision": 1} for index in range(count)],
            "generation_inputs": {"seed": 7},
            "validation": {"profile_id": "single", "provider_id": "vision"},
            "group_validation": {"profile_id": "group", "provider_id": "vision"},
        }

    def mark_passed(self, plan):
        for item in self.plans.items(plan["id"], {"limit": 200, "offset": 0})["items"]:
            item.update(state="passed", passed_image_ids=["image-" + str(item["index"])])
            self.plans.item_save(plan["id"], item)

    def test_create_3000_plan_is_pageable_and_rolls_back_when_one_snapshot_fails(self):
        body = self.body(3000)
        plan, created = self.plans.create("large-plan", body)
        self.assertTrue(created)
        self.assertEqual((plan["total"], self.plans.items(plan["id"], {"limit": 200, "offset": 2800})["total"]), (3000, 3000))
        tail = self.plans.items(plan["id"], {"limit": 200, "offset": 2800})["items"]
        self.assertEqual((len(tail), tail[0]["index"], tail[-1]["index"]), (200, 2800, 2999))
        broken = self.body(3)
        broken["fragments"][1]["id"] = "invalid"
        with self.assertRaises(ApiError):
            self.plans.create("rollback", broken)
        self.assertEqual(self.plans.list({"limit": 200, "offset": 0})["total"], 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM production_plan_items").fetchone()[0], 3000)

    def test_eight_item_dispatch_is_restart_safe_and_cancel_stops_active_and_queued(self):
        plan, _ = self.plans.create("window", self.body(10))
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        self.plans.advance(self.plans.get(plan["id"]))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], WINDOW)
        self.plans = ProductionPlans(self.core)  # equivalent durable reload before the next tick
        self.plans.advance(self.plans.get(plan["id"]))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], WINDOW)
        self.plans.cancel(plan["id"])
        self.plans.advance(self.plans.get(plan["id"]))
        saved = self.plans.get(plan["id"])
        self.assertEqual(saved["state"], "cancelled")
        self.assertEqual(saved["counts"].get("cancelled"), 10)

    def test_targets_over_32_share_reference_and_chunk_in_sequence(self):
        reference = self.reference()
        plan, _ = self.plans.create("chunks", self.body(65))
        self.mark_passed(plan)
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        for expected_size in (32, 32, 1):
            self.plans.advance(self.plans.get(plan["id"]))
            call = self.groups.calls[-1]
            self.assertEqual((len(call[2]["target_ids"]), call[2]["reference_revision"]), (expected_size, reference["revision"]))
            self.groups.runs[call[4]].update(state="completed", outcome="passed")
        self.plans.advance(self.plans.get(plan["id"]))
        saved = self.plans.get(plan["id"])
        self.assertEqual((saved["state"], saved["outcome"], len(self.groups.calls)), ("completed", "passed", 3))

    def test_group_failed_and_error_outcomes_are_never_reported_as_passed(self):
        for outcome in ("failed", "error"):
            self.reference()
            plan, _ = self.plans.create("result-" + outcome, self.body(2))
            self.mark_passed(plan)
            self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
            self.plans.advance(self.plans.get(plan["id"]))
            self.groups.runs[self.groups.calls[-1][4]].update(state="completed", outcome=outcome)
            self.plans.advance(self.plans.get(plan["id"]))
            self.assertEqual(self.plans.get(plan["id"])["outcome"], outcome)

    def test_dispatch_error_drains_accepted_work_after_reload(self):
        plan, _ = self.plans.create("dispatch-error", self.body(10))
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        original = self.store.create_task
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ApiError("CORE_TEST_DISPATCH_FAILURE", "Dispatch failed")
            return original(*args, **kwargs)
        self.store.create_task = fail_second
        asyncio.run(self.plans.tick())
        saved = self.plans.get(plan["id"])
        self.assertEqual((saved["state"], saved["outcome"]), ("cancellation_pending", "error"))
        self.assertEqual(saved["counts"]["generation_pending"], 1)
        self.store.create_task = original
        self.plans = ProductionPlans(self.core)
        asyncio.run(self.plans.tick())
        saved = self.plans.get(plan["id"])
        self.assertEqual((saved["state"], saved["outcome"]), ("failed", "error"))
        self.assertEqual(saved["error"]["code"], "CORE_TEST_DISPATCH_FAILURE")
        self.assertEqual(saved["counts"], {"cancelled": 10})
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1)

    def test_cancel_intent_survives_interruption_before_queued_rows_update(self):
        plan, _ = self.plans.create("cancel-interruption", self.body(10))
        plan.update(cancel_requested=True, state="cancellation_pending")
        self.plans.save(plan)
        self.plans = ProductionPlans(self.core)
        asyncio.run(self.plans.tick())
        self.assertEqual(self.plans.get(plan["id"])["counts"], {"cancelled": 10})
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)

    def test_cancel_recovers_task_committed_before_item_link(self):
        plan, _ = self.plans.create("unlinked-task", self.body())
        item = self.plans.items(plan["id"], {})["items"][0]
        task = self.store.create_task(f"production-plan:{plan['id']}:0", item["preview_hash"], plan["group_id"], item["snapshot"])
        self.plans = ProductionPlans(self.core)
        self.plans.cancel(plan["id"])
        asyncio.run(self.plans.tick())
        self.assertEqual(self.store.task(task["id"])["state"], "cancelled")
        self.assertEqual(self.plans.get(plan["id"])["counts"], {"cancelled": 2})

    def test_cancel_recovers_group_run_committed_before_comparison_link(self):
        self.reference()
        plan, _ = self.plans.create("comparison-link-gap", self.body())
        self.mark_passed(plan)
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        original = self.plans.compare_save
        self.plans.compare_save = lambda *_: (_ for _ in ()).throw(RuntimeError("interrupted after group submit"))
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.plans.advance(self.plans.get(plan["id"]))
        run_id = self.groups.calls[0][4]
        self.plans.compare_save = original
        self.plans.cancel(plan["id"])
        self.plans.advance(self.plans.get(plan["id"]))
        self.assertIn(run_id, self.groups.cancelled)
        # Cancellation is cooperative: one pass requests it, the next observes
        # the terminal group Run before closing the parent plan.
        self.plans.advance(self.plans.get(plan["id"]))
        self.assertEqual(self.plans.get(plan["id"])["state"], "cancelled")

    def test_validation_modes_allow_generation_only_and_single_without_group_comparison(self):
        generation_only = self.body()
        generation_only.pop("validation")
        generation_only.pop("group_validation")
        plan, _ = self.plans.create("generation-only", generation_only)
        self.assertEqual(plan["validation_mode"], "none")
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        self.plans.advance(self.plans.get(plan["id"]))
        for item in self.plans.items(plan["id"], {"limit": 200, "offset": 0})["items"]:
            task = self.store.task(item["task_id"])
            task["state"] = "generated"
            self.store.update_task(task)
        self.plans.advance(self.plans.get(plan["id"]))
        saved = self.plans.get(plan["id"])
        self.assertEqual((saved["state"], saved["outcome"], saved["counts"]), ("completed", "unvalidated", {"generation_only": 2}))
        self.assertEqual(self.groups.calls, [])

        single = self.body()
        single.pop("group_validation")
        plan, _ = self.plans.create("single-only", single)
        self.assertEqual(plan["validation_mode"], "single")
        self.mark_passed(plan)
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        self.plans.advance(self.plans.get(plan["id"]))
        self.assertEqual((self.plans.get(plan["id"])["state"], self.plans.get(plan["id"])["outcome"], self.groups.calls),
                         ("completed", "passed", []))

        invalid = self.body()
        invalid.pop("validation")
        with self.assertRaisesRegex(ApiError, "group_validation requires") as raised:
            self.plans.create("invalid-group-only", invalid)
        self.assertEqual(raised.exception.code, "CORE_INVALID_INPUT")
        with self.assertRaisesRegex(ApiError, "validation selections") as raised:
            self.plans.create("null-validation", dict(generation_only, validation=None))
        self.assertEqual(raised.exception.code, "CORE_INVALID_INPUT")

    def test_generation_only_failure_and_cancel_are_explicit_terminal_outcomes(self):
        body = self.body(1)
        body.pop("validation")
        body.pop("group_validation")
        failed, _ = self.plans.create("generation-only-failure", body)
        self.plans.start(failed["id"], {"plan_hash": failed["plan_hash"]})
        self.plans.advance(self.plans.get(failed["id"]))
        item = self.plans.items(failed["id"], {})["items"][0]
        task = self.store.task(item["task_id"])
        task.update(state="failed", error={"code": "CORE_GENERATION_FAILED", "message": "fixture failure"})
        self.store.update_task(task)
        self.plans.advance(self.plans.get(failed["id"]))
        self.assertEqual((self.plans.get(failed["id"])["state"], self.plans.get(failed["id"])["outcome"]), ("failed", "error"))
        self.assertEqual(self.plans.items(failed["id"], {})["items"][0]["error"]["code"], "CORE_GENERATION_FAILED")

        cancelled, _ = self.plans.create("generation-only-cancel", body)
        self.plans.start(cancelled["id"], {"plan_hash": cancelled["plan_hash"]})
        self.plans.advance(self.plans.get(cancelled["id"]))
        self.plans.cancel(cancelled["id"])
        self.plans.advance(self.plans.get(cancelled["id"]))
        self.assertEqual((self.plans.get(cancelled["id"])["state"], self.plans.get(cancelled["id"])["counts"]),
                         ("cancelled", {"cancelled": 1}))

    def test_random_seed_is_distinct_per_plan_item_and_idempotently_frozen(self):
        body = self.body(2)
        body["generation_inputs"] = {"seed": -1}
        plan, created = self.plans.create("random-plan", body)
        self.assertTrue(created)
        seeds = [item["snapshot"]["generation_inputs"]["seed"]
                 for item in self.plans.items(plan["id"], {"limit": 200, "offset": 0})["items"]]
        self.assertTrue(all(type(seed) is int and seed >= 0 for seed in seeds))
        self.assertNotEqual(*seeds)
        self.plans = ProductionPlans(self.core)  # reload uses stored execution snapshots
        same, created = self.plans.create("random-plan", body)
        self.assertFalse(created)
        self.assertEqual([item["snapshot"]["generation_inputs"]["seed"]
                          for item in self.plans.items(same["id"], {"limit": 200, "offset": 0})["items"]], seeds)

    def test_common_fragment_refs_are_frozen_for_each_variant_item(self):
        body = self.body(2)
        body["common_fragments"] = [{"id": "common", "revision": 3}]
        plan, _ = self.plans.create("common-fragment-plan", body)
        items = self.plans.items(plan["id"], {"limit": 200, "offset": 0})["items"]
        self.assertEqual([item["snapshot"]["common_fragments"] for item in items], [body["common_fragments"], body["common_fragments"]])


if __name__ == "__main__":
    unittest.main()
