"""Durable queue checks using real SQLite and simulated execution providers."""
import asyncio
import time
import unittest
import uuid
from pathlib import Path

from atelierx.common import canonical
from atelierx.core.groups import CoreGroups
from atelierx.core.production_plans import ProductionPlans, WINDOW
from atelierx.core.store import Store
import test_production_plans as fixtures


class PlanRecoveryTests(unittest.TestCase):
    setUp = fixtures.ProductionPlanTests.setUp
    tearDown = fixtures.ProductionPlanTests.tearDown
    preview = fixtures.ProductionPlanTests.preview
    body = fixtures.ProductionPlanTests.body
    reference = fixtures.ProductionPlanTests.reference
    mark_passed = fixtures.ProductionPlanTests.mark_passed

    def reopen(self):
        self.store.close()
        self.store = Store(Path(self.tmp.name) / "core.sqlite3")
        self.core.store = self.store
        self.core.regeneration = fixtures.FakeRegeneration(self.store)
        self.plans = ProductionPlans(self.core)

    def test_1024_items_progress_across_database_reopens_without_duplicates(self):
        self.reference()
        plan, _ = self.plans.create("long-queue", self.body(1024))
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        def finish(item):
            task = self.store.task(item["active_task_id"])
            task["state"] = "generated"
            self.store.update_task(task)
            item.update(state="passed", passed_image_ids=["image-" + str(item["index"])])
        self.core.batches._observe_item = finish
        for turn in range(200):
            if turn in (1, 32, 64, 128):
                self.reopen()
            asyncio.run(self.plans.tick())
            current = self.plans.get(plan["id"])
            self.assertLessEqual(current["counts"].get("generation_pending", 0), WINDOW)
            for run in self.groups.runs.values():
                run.update(state="completed", outcome="passed")
            if current["state"] == "completed":
                break
        self.assertEqual((current["state"], current["outcome"]), ("completed", "passed"))
        self.assertEqual(current["counts"], {"passed": 1024})
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1024)
        self.assertEqual(len(self.groups.calls), 32)
        self.assertEqual({call[2]["reference_revision"] for call in self.groups.calls}, {1})

    def test_cancel_running_comparison_waits_for_terminal_after_reopen(self):
        self.reference()
        plan, _ = self.plans.create("cancel-group", self.body())
        self.mark_passed(plan)
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        asyncio.run(self.plans.tick())
        run_id = self.groups.calls[0][4]
        self.groups.runs[run_id]["state"] = "running"
        self.groups.cancel = lambda rid: self.groups.runs[rid].update(state="cancellation_pending")
        self.plans.cancel(plan["id"])
        self.reopen()
        asyncio.run(self.plans.tick())
        self.assertEqual(self.plans.get(plan["id"])["state"], "cancellation_pending")
        self.groups.runs[run_id]["state"] = "cancelled"
        asyncio.run(self.plans.tick())
        self.assertEqual(self.plans.get(plan["id"])["state"], "cancelled")
        self.assertEqual(len(self.groups.calls), 1)

    def test_committed_unlinked_task_cancelled_after_database_reopen(self):
        plan, _ = self.plans.create("commit-gap", self.body())
        item = self.plans.items(plan["id"], {})["items"][0]
        task = self.store.create_task(f"production-plan:{plan['id']}:0", item["preview_hash"], plan["group_id"], item["snapshot"])
        plan.update(cancel_requested=True, state="cancellation_pending")
        self.plans.save(plan)
        self.reopen()
        asyncio.run(self.plans.tick())
        self.assertEqual(self.store.task(task["id"])["state"], "cancelled")
        self.assertEqual(self.plans.get(plan["id"])["counts"], {"cancelled": 2})

    def test_real_group_run_lookup_recovers_then_cancels_after_database_reopen(self):
        """Use the production SQLite lookup when a comparison link was not saved."""
        self.reference()
        plan, _ = self.plans.create("comparison-link-gap", self.body())
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        CoreGroups(self.core)
        run_id = str(uuid.uuid4())
        request_key = f"production-plan-group:{plan['id']}:0:0"
        run = {"id": run_id, "group_id": self.group["id"], "created_at": time.time(), "state": "queued",
               "request": {"reference_revision": 1}, "outcome": None, "result": None, "error": None}
        with self.store.db:
            self.store.db.execute("INSERT INTO group_runs VALUES(?,?,?,?)",
                                  (run_id, request_key, "fault-test", canonical(run)))
        self.reopen()
        self.core.groups = CoreGroups(self.core)
        self.plans.recover_comparison_links(self.plans.get(plan["id"]))
        linked = self.plans.comparisons(plan["id"])
        self.assertEqual([(item["index"], item["run_id"], item["state"]) for item in linked],
                         [(0, run_id, "queued")])
        self.plans.cancel(plan["id"])
        self.plans.advance(self.plans.get(plan["id"]))
        self.assertEqual(self.core.groups.get(run_id)["state"], "cancelled")
        self.plans.advance(self.plans.get(plan["id"]))
        self.assertEqual(self.plans.get(plan["id"])["state"], "cancelled")

    def test_single_validation_cancel_waits_and_never_dispatches_more(self):
        plan, _ = self.plans.create("single-cancel", self.body(10))
        self.plans.start(plan["id"], {"plan_hash": plan["plan_hash"]})
        asyncio.run(self.plans.tick())
        item = self.plans.items(plan["id"], {})["items"][0]
        task = self.store.task(item["active_task_id"])
        task.update(state="generated", images=[{"id": "single-image"}])
        self.store.update_task(task)
        item["state"] = "single_validation_pending"
        self.plans.item_save(plan["id"], item)
        self.reopen()
        run = {"id": "single-run", "state": "running"}
        self.store.image_validations = lambda image_id: [run]
        self.core.validation.cancel = lambda run_id: run.update(state="cancellation_pending")
        self.plans.cancel(plan["id"])
        asyncio.run(self.plans.tick())
        self.assertEqual(self.plans.get(plan["id"])["state"], "cancellation_pending")
        self.assertEqual(self.plans.get(plan["id"])["counts"].get("single_validation_pending"), 1)
        run["state"] = "cancelled"
        self.core.validation.cancel = lambda run_id: None
        asyncio.run(self.plans.tick())
        self.assertEqual(self.plans.get(plan["id"])["state"], "cancelled")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], WINDOW)
        self.assertFalse(self.groups.calls)
