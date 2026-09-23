import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from atelierx.common import ApiError, canonical
from atelierx.core.batches import CoreBatches
from atelierx.core.store import Store


class FakeValidation:
    def freeze(self, selection):
        consistent = selection["profile_id"] == "group"
        return {"selection": dict(selection), "profile": {"profile_id": selection["profile_id"], "revision": 1, "consistency": consistent},
                "provider": {"provider_id": selection["provider_id"], "revision": 1}, "endpoint": "http://validation.fixture"}

    def cancel(self, run_id):
        return None

    freeze_group = freeze


class FakeGroups:
    def __init__(self, reference=None):
        self.reference = reference
        self.calls, self.runs, self.cancelled = [], {}, []

    def reference_candidate(self, group_id):
        return {"state": "ready_for_confirmation", "representative_id": "candidate", "auxiliary_ids": [], "group_id": group_id}

    def submit(self, group_id, key, body, frozen):
        self.calls.append((group_id, key, body, frozen))
        run = {"id": str(uuid.uuid4()), "state": "queued", "error": None}
        self.runs[run["id"]] = run
        return run, True

    def get(self, run_id):
        return self.runs[run_id]

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        self.runs[run_id]["state"] = "cancelled"


class FakeRegeneration:
    def __init__(self, store): self.store = store

    def stop(self, cycle_id):
        cycle = self.store.cycle(cycle_id)
        task = self.store.task(cycle["active_task_id"])
        task["state"] = "cancelled"
        self.store.update_task(task)
        return self.store.update_cycle(cycle, state="cancelled", reason="fixture stopped")


class CoreBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "core.sqlite")
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        outfit = self.store.create_entity("outfits", "outfit", character["id"], {"appearance": "hair", "upper": "shirt", "lower": "boots"})
        self.group = self.store.create_group(outfit["id"])
        self.groups = FakeGroups({"revision": 1, "representative_id": "reference", "auxiliary_ids": []})
        self.set_reference(self.groups.reference)
        self.core = SimpleNamespace(store=self.store, validation=FakeValidation(), groups=self.groups, regeneration=FakeRegeneration(self.store))
        self.preview_revision = 1
        self.core.preview = self.preview
        self.batches = CoreBatches(self.core)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def preview(self, payload):
        frozen = self.core.validation.freeze(payload["validation"])
        snapshot = {"generation_endpoint": "http://generation.fixture", "settings": {"revision": self.preview_revision},
                    "generation_inputs": {"positive_prompt": payload.get("expression", "portrait"), "negative_prompt": "", "seed": payload["generation_inputs"]["seed"]},
                    "validation": frozen}
        return {"snapshot": snapshot, "preview_hash": hashlib.sha256(canonical(snapshot).encode()).hexdigest()}

    def set_reference(self, reference):
        group = self.store.group(self.group["id"])
        if reference is None: group.pop("reference", None)
        else: group["reference"] = dict(reference)
        with self.store.db:
            self.store.db.execute("UPDATE groups SET document=? WHERE id=?", (canonical(group), group["id"]))

    def body(self, count=2):
        return {"items": [{"framing": "upper_body", "expression": "pose " + str(index), "generation_inputs": {"seed": index},
                           "validation": {"profile_id": "single", "provider_id": "vision"}} for index in range(count)],
                "group_validation": {"profile_id": "group", "provider_id": "vision"}}

    def finish(self, item, outcome="passed"):
        task = self.store.task(item["active_task_id"])
        if outcome == "generation_failed":
            task.update(state="failed", error={"code": "fixture"}); self.store.update_task(task); return
        if outcome == "cancelled":
            task.update(state="cancelled", error=None); self.store.update_task(task); return
        data = (task["id"] + outcome).encode()
        image = {"id": str(uuid.uuid4()), "task_id": task["id"], "group_id": task["group_id"],
                 "generation_image_id": str(uuid.uuid4()) + "-0", "generation_job_id": str(uuid.uuid4()),
                 "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "media_type": "image/png",
                 "validation_state": "completed", "validation": {"outcome": outcome}}
        self.store.finish_generation(task, [image])
        cycle = self.store.cycle(task["regeneration"]["cycle_id"])
        self.store.update_cycle(cycle, state="passed" if outcome == "passed" else "error", reason="fixture")
        return image

    def test_stale_item_preview_rejects_entire_batch_before_creation(self):
        body = self.body()
        body["items"][1]["preview_hash"] = "stale"
        with self.assertRaises(ApiError) as caught:
            self.batches.submit(self.group["id"], "stale-preview", body)
        self.assertEqual(caught.exception.code, "CORE_PREVIEW_STALE")
        self.assertEqual(self.batches.list(), [])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_reference_confirmation_wait_can_be_cancelled(self):
        self.set_reference(None)
        batch, _ = self.batches.submit(self.group["id"], "cancel-reference-wait", self.body())
        for item in batch["items"]:
            self.finish(item)
        self.batches.advance(self.batches.get(batch["id"]))
        self.assertEqual(self.batches.get(batch["id"])["state"], "awaiting_reference_confirmation")
        self.batches.advance(self.batches.cancel(batch["id"]))
        self.assertEqual(self.batches.get(batch["id"])["state"], "cancelled")
        self.assertEqual(self.groups.calls, [])

    def test_frozen_specs_idempotency_and_restart_do_not_duplicate_tasks(self):
        created, new = self.batches.submit(self.group["id"], "batch-key", self.body())
        self.assertTrue(new)
        self.assertEqual([item["snapshot"]["settings"]["revision"] for item in created["items"]], [1, 1])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
        self.preview_revision = 99
        repeated, new = self.batches.submit(self.group["id"], "batch-key", self.body())
        self.assertFalse(new)
        self.assertEqual(repeated["id"], created["id"])
        self.batches = CoreBatches(self.core)
        self.batches.advance(self.batches.get(created["id"]))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
        self.assertEqual([item["snapshot"]["settings"]["revision"] for item in self.batches.get(created["id"])["items"]], [1, 1])

    def test_partial_terminal_items_start_one_group_run_for_passed_images_only(self):
        batch, _ = self.batches.submit(self.group["id"], "partial", self.body(3))
        passed = self.finish(batch["items"][0])
        self.finish(batch["items"][1], "generation_failed")
        self.finish(batch["items"][2], "cancelled")
        self.batches.advance(self.batches.get(batch["id"]))
        pending = self.batches.get(batch["id"])
        self.assertEqual(pending["state"], "group_validation_pending")
        self.assertEqual(self.groups.calls[0][2]["target_ids"], [passed["id"]])
        self.groups.runs[pending["group_run_id"]].update(state="completed")
        self.batches.advance(self.batches.get(batch["id"]))
        done = self.batches.get(batch["id"])
        self.assertEqual((done["state"], done["summary"]["counts"]["generation_failed"], done["summary"]["counts"]["cancelled"]), ("completed", 1, 1))

    def test_no_reference_or_only_one_passed_image_never_starts_comparison(self):
        self.groups.reference = None
        self.set_reference(None)
        batch, _ = self.batches.submit(self.group["id"], "one-pass", self.body(2))
        self.finish(batch["items"][0])
        self.finish(batch["items"][1], "generation_failed")
        self.batches.advance(self.batches.get(batch["id"]))
        saved = self.batches.get(batch["id"])
        self.assertEqual(saved["state"], "insufficient_images")
        self.assertEqual(saved["reference_proposal"]["state"], "ready_for_confirmation")
        self.assertEqual(self.groups.calls, [])

    def test_cancel_prevents_future_batch_progress_and_preserves_task_history(self):
        batch, _ = self.batches.submit(self.group["id"], "cancel", self.body(2))
        cancelled = self.batches.cancel(batch["id"])
        self.batches.advance(cancelled)
        saved = self.batches.get(batch["id"])
        self.assertTrue(saved["cancel_requested"])
        self.assertEqual(saved["state"], "cancelled")
        self.assertEqual(self.groups.calls, [])

    def test_cancel_stops_the_cycle_latest_automatic_child(self):
        batch, _ = self.batches.submit(self.group["id"], "cancel-child", self.body(1))
        root = self.store.task(batch["items"][0]["task_id"])
        child = self.store.create_task("fixture-child", "fixture-child", self.group["id"], root["snapshot"], {
            "kind": "automatic", "parent_task_id": root["id"], "lineage_id": root["regeneration"]["lineage_id"],
            "cycle_id": root["regeneration"]["cycle_id"], "source_run_ids": [],
        })
        self.batches.cancel(batch["id"])
        self.assertEqual(self.store.task(child["id"])["state"], "cancelled")
        self.assertEqual(self.store.cycle(root["regeneration"]["cycle_id"])["state"], "cancelled")

    def test_reference_change_after_acceptance_never_auto_submits_a_new_group_run(self):
        batch, _ = self.batches.submit(self.group["id"], "reference-race", self.body())
        self.set_reference({"revision": 2, "representative_id": "new-reference", "auxiliary_ids": []})
        self.finish(batch["items"][0]); self.finish(batch["items"][1])
        self.batches.advance(self.batches.get(batch["id"]))
        saved = self.batches.get(batch["id"])
        self.assertEqual((saved["state"], saved["error"]["code"], self.groups.calls), ("awaiting_reference_confirmation", "CORE_GROUP_STALE", []))

    def test_reference_confirmation_resumes_once_with_a_new_durable_group_key(self):
        self.set_reference(None)
        batch, _ = self.batches.submit(self.group["id"], "confirm", self.body(2))
        self.finish(batch["items"][0]); self.finish(batch["items"][1])
        self.batches.advance(self.batches.get(batch["id"]))
        waiting = self.batches.get(batch["id"])
        self.assertEqual(waiting["state"], "awaiting_reference_confirmation")
        reference = {"revision": 2, "representative_id": "chosen", "auxiliary_ids": []}
        self.set_reference(reference)
        resumed, created = self.batches.confirm_reference(batch["id"], "confirm-key", {"reference_revision": 2})
        self.assertTrue(created)
        self.assertEqual((resumed["state"], self.groups.calls[0][1].rsplit(":", 1)[-1]), ("group_validation_pending", "1"))
        repeated, created = self.batches.confirm_reference(batch["id"], "confirm-key", {"reference_revision": 2})
        self.assertFalse(created)
        self.assertEqual(repeated["id"], batch["id"])
        self.assertEqual(len(self.groups.calls), 1)

    def test_reference_put_does_not_resume_awaiting_batch_without_confirmation(self):
        self.set_reference(None)
        batch, _ = self.batches.submit(self.group["id"], "awaiting", self.body(2))
        self.finish(batch["items"][0]); self.finish(batch["items"][1])
        self.batches.advance(self.batches.get(batch["id"]))
        self.assertEqual(self.batches.get(batch["id"])["state"], "awaiting_reference_confirmation")
        self.set_reference({"revision": 2, "representative_id": "chosen", "auxiliary_ids": []})
        self.batches.advance(self.batches.get(batch["id"]))
        self.assertEqual((self.batches.get(batch["id"])["state"], self.groups.calls), ("awaiting_reference_confirmation", []))

    def test_cancel_is_noop_after_completed_or_insufficient_batch(self):
        batch, _ = self.batches.submit(self.group["id"], "completed-noop", self.body(1))
        self.finish(batch["items"][0]); self.batches.advance(self.batches.get(batch["id"]))
        pending = self.batches.get(batch["id"])
        self.groups.runs[pending["group_run_id"]]["state"] = "completed"
        self.batches.advance(pending)
        completed = self.batches.cancel(batch["id"])
        self.assertEqual((completed["state"], completed["cancel_requested"], self.groups.cancelled), ("completed", False, []))
        self.set_reference(None)
        empty, _ = self.batches.submit(self.group["id"], "insufficient-noop", self.body(1))
        self.finish(empty["items"][0]); self.batches.advance(self.batches.get(empty["id"]))
        self.assertEqual(self.batches.cancel(empty["id"])["state"], "insufficient_images")

    def test_tick_records_one_batch_api_error_without_blocking_others(self):
        first, _ = self.batches.submit(self.group["id"], "bad-tick", self.body(1))
        second, _ = self.batches.submit(self.group["id"], "good-tick", self.body(1))
        broken = self.batches.get(first["id"])
        broken["items"][0]["active_task_id"] = "missing"
        self.batches.save(broken)
        self.finish(second["items"][0])
        import asyncio
        asyncio.run(self.batches.tick())
        self.assertEqual(self.batches.get(first["id"])["state"], "failed")
        self.assertEqual(self.batches.get(second["id"])["state"], "group_validation_pending")


if __name__ == "__main__":
    unittest.main()
