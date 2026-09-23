"""Durable, fixed-scope group generation batches.

The Core worker already owns generation, single validation, and regeneration.
This module only persists a batch boundary and observes those existing tasks.
"""
import hashlib
import json
import time
import uuid

from aiohttp import web

from ..common import ApiError, canonical


TERMINAL = {"completed", "failed", "cancelled", "insufficient_images"}
ITEM_TERMINAL = {"passed", "single_failed", "generation_failed", "cancelled", "generation_only"}


class CoreBatches:
    def __init__(self, core):
        self.core, self.store = core, core.store
        self.store.db.execute("CREATE TABLE IF NOT EXISTS group_batches (id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, document TEXT NOT NULL)")
        self.store.db.commit()

    def get(self, batch_id):
        row = self.store.db.execute("SELECT document FROM group_batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Group batch not found", 404)
        return json.loads(row[0])

    def save(self, batch):
        with self.store.db:
            self.store.db.execute("UPDATE group_batches SET document=? WHERE id=?", (canonical(batch), batch["id"]))

    def list(self, group_id=None):
        rows = [json.loads(row[0]) for row in self.store.db.execute("SELECT document FROM group_batches")]
        return sorted([row for row in rows if group_id is None or row["group_id"] == group_id], key=lambda row: (row["created_at"], row["id"]))

    @staticmethod
    def _item_payload(group_id, item):
        if not isinstance(item, dict):
            raise ApiError("CORE_INVALID_INPUT", "Each batch item must be an object")
        if "group_id" in item:
            raise ApiError("CORE_INVALID_INPUT", "Batch items inherit group_id")
        return dict(item, group_id=group_id)

    def submit(self, group_id, key, body):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key required")
        if not isinstance(body, dict) or set(body) != {"items", "group_validation"}:
            raise ApiError("CORE_INVALID_INPUT", "items and group_validation are required")
        if not isinstance(body["items"], list) or not 1 <= len(body["items"]) <= 32:
            raise ApiError("CORE_INVALID_INPUT", "Select 1..32 batch items")
        fingerprint = hashlib.sha256(canonical({"group_id": group_id, "body": body}).encode()).hexdigest()
        old = self.store.db.execute("SELECT fingerprint,document FROM group_batches WHERE request_key=?", (key,)).fetchone()
        if old:
            if old[0] != fingerprint:
                raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Batch key has different content", 409)
            return json.loads(old[1]), False
        self.store.group(group_id)
        accepted_reference = self.store.group(group_id).get("reference")
        frozen_group = self.core.validation.freeze_group(body["group_validation"])
        if frozen_group["profile"].get("consistency") is not True:
            raise ApiError("CORE_INVALID_INPUT", "Select a dedicated group profile")
        specs = []
        for index, raw in enumerate(body["items"]):
            payload = self._item_payload(group_id, raw)
            if payload.get("validation") is None:
                raise ApiError("CORE_INVALID_INPUT", "Batch items require single-image validation")
            preview = self.core.preview(payload)
            if "preview_hash" in payload and payload["preview_hash"] != preview["preview_hash"]:
                raise ApiError("CORE_PREVIEW_STALE", "Prompt or settings changed; review the updated preview", 409)
            snapshot = preview["snapshot"]
            specs.append({"index": index, "request": payload, "snapshot": snapshot,
                          "fingerprint": hashlib.sha256(canonical(payload).encode()).hexdigest(),
                          "task_key": "core-batch-task:" + key + ":" + str(index), "task_id": None,
                          "active_task_id": None, "state": "queued", "passed_image_ids": [], "error": None})
        batch = {"id": str(uuid.uuid4()), "group_id": group_id, "created_at": time.time(), "state": "creating",
                 "request": body, "group_validation_frozen": frozen_group, "items": specs, "reference": None,
                 "accepted_reference": dict(accepted_reference) if accepted_reference else None,
                 "group_run_id": None, "summary": None, "cancel_requested": False, "error": None,
                 "confirmations": {}, "confirmation_sequence": 0}
        with self.store.db:
            self.store.db.execute("INSERT INTO group_batches VALUES(?,?,?,?)", (batch["id"], key, fingerprint, canonical(batch)))
        self.advance(self.get(batch["id"]))
        return self.get(batch["id"]), True

    def _create_items(self, batch):
        for item in batch["items"]:
            if batch.get("cancel_requested"):
                if item["state"] == "queued": item["state"] = "cancelled"
                continue
            if item["task_id"]:
                continue
            old = self.store.by_key(item["task_key"])
            if old:
                if old[0] != item["fingerprint"]:
                    raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Saved batch task key conflicts", 409)
                task = old[1]
            else:
                task = self.store.create_task(item["task_key"], item["fingerprint"], batch["group_id"], item["snapshot"])
            item.update(task_id=task["id"], active_task_id=task["id"], state="generation_pending")

    def _observe_item(self, item):
        task = self.store.task(item["active_task_id"])
        cycle = self.store.cycle(task["regeneration"]["cycle_id"])
        if cycle["active_task_id"] != task["id"]:
            item["active_task_id"] = cycle["active_task_id"]
            item["state"] = "generation_pending"
            return
        if task.get("cancel_requested") or task["state"] == "cancelled":
            item["state"] = "cancelled"; return
        if task["state"] == "failed":
            item.update(state="generation_failed", error=task.get("error")); return
        if task["state"] != "generated":
            item["state"] = "generation_pending"; return
        if cycle["state"] == "active":
            item["state"] = "single_validation_pending"; return
        if cycle["state"] != "passed":
            item.update(state="single_failed", error={"code": "CORE_BATCH_SINGLE_CYCLE", "message": "Single-image cycle did not pass"}); return
        passed = [image["id"] for image in task["images"] if (image.get("validation") or {}).get("outcome") == "passed"]
        if not passed:
            item.update(state="single_failed", error={"code": "CORE_BATCH_SINGLE_FAILED", "message": "No output passed single validation"}); return
        item.update(state="passed", passed_image_ids=passed)

    def _summary(self, batch):
        counts = {state: sum(item["state"] == state for item in batch["items"]) for state in ("queued", "generation_pending", "single_validation_pending", *sorted(ITEM_TERMINAL))}
        return {"counts": counts, "passed_image_ids": [image for item in batch["items"] for image in item["passed_image_ids"]]}

    def _start_group_validation(self, batch):
        summary = self._summary(batch)
        if any(item["state"] not in ITEM_TERMINAL for item in batch["items"]):
            batch.update(state="running", summary=summary); return
        reference = self.store.group(batch["group_id"]).get("reference")
        if batch.get("accepted_reference") and reference != batch["accepted_reference"]:
            batch.update(state="awaiting_reference_confirmation", summary=summary,
                         error={"code": "CORE_GROUP_STALE", "message": "Reference changed after batch acceptance"})
            return
        if not reference:
            proposal = self.core.groups.reference_candidate(batch["group_id"])
            batch.update(state="insufficient_images" if len(summary["passed_image_ids"]) < 2 else "awaiting_reference_confirmation",
                         summary=summary, reference_proposal=proposal)
            return
        targets = [image for image in summary["passed_image_ids"] if image not in {reference["representative_id"], *reference["auxiliary_ids"]}]
        if not targets:
            batch.update(state="insufficient_images", summary=summary, reference=dict(reference)); return
        if batch["reference"] and batch["reference"] != reference:
            batch.update(state="awaiting_reference_confirmation", summary=summary,
                         error={"code": "CORE_GROUP_STALE", "message": "Reference changed before batch comparison"}); return
        batch["reference"] = dict(reference)
        run, _ = self.core.groups.submit(batch["group_id"], "core-batch-group:" + batch["id"] + ":" + str(batch.get("confirmation_sequence", 0)), {
            "reference_revision": reference["revision"], "target_ids": targets,
            "validation": batch["request"]["group_validation"],
        }, batch["group_validation_frozen"])
        batch.update(state="group_validation_pending", group_run_id=run["id"], summary=summary)

    def advance(self, batch):
        if batch["state"] in TERMINAL:
            return
        # Reference selection/replacement is an explicit user confirmation
        # boundary.  A later PUT reference alone must never wake this batch.
        if batch["state"] == "awaiting_reference_confirmation" and not batch.get("cancel_requested"):
            return
        self._create_items(batch)
        for item in batch["items"]:
            if item["task_id"] and item["state"] not in ITEM_TERMINAL:
                self._observe_item(item)
        if batch.get("cancel_requested"):
            if batch.get("group_run_id") and self.core.groups.get(batch["group_run_id"])["state"] not in {"completed", "failed", "cancelled"}:
                batch.update(state="cancellation_pending", summary=self._summary(batch))
                self.save(batch); return
            if all(item["state"] in ITEM_TERMINAL for item in batch["items"]):
                batch.update(state="cancelled", summary=self._summary(batch))
            self.save(batch); return
        if batch["state"] != "group_validation_pending":
            self._start_group_validation(batch)
        else:
            run = self.core.groups.get(batch["group_run_id"])
            if run["state"] in {"completed", "failed", "cancelled"}:
                current = self.store.group(batch["group_id"]).get("reference")
                if current != batch["reference"]:
                    batch.update(state="awaiting_reference_confirmation", summary=self._summary(batch),
                                 error={"code": "CORE_GROUP_STALE", "message": "Reference changed while batch comparison ran"})
                else:
                    batch.update(state="completed" if run["state"] == "completed" else run["state"], summary=self._summary(batch), error=run.get("error"))
        self.save(batch)

    def cancel(self, batch_id):
        batch = self.get(batch_id)
        if batch["state"] in TERMINAL:
            return batch
        batch["cancel_requested"] = True
        if batch.get("group_run_id"):
            self.core.groups.cancel(batch["group_run_id"])
        for item in batch["items"]:
            if not item["task_id"]: continue
            task = self.store.task(item["active_task_id"])
            cycle = self.store.cycle(task["regeneration"]["cycle_id"])
            # Stop uses the cycle's current active task, avoiding a race where
            # single validation spawned an automatic child after batch creation.
            self.core.regeneration.stop(cycle["id"])
            task = self.store.task(cycle["active_task_id"])
            for image in task["images"]:
                for run in self.store.image_validations(image["id"]): self.core.validation.cancel(run["id"])
        self.save(batch)
        return self.get(batch_id)

    async def tick(self):
        for batch in self.list():
            try:
                self.advance(self.get(batch["id"]))
            except ApiError as exc:
                failed = self.get(batch["id"])
                failed.update(state="failed", error={"code": exc.code, "message": exc.message}, summary=self._summary(failed))
                self.save(failed)

    def confirm_reference(self, batch_id, key, body):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key required")
        if not isinstance(body, dict) or set(body) != {"reference_revision"} or type(body["reference_revision"]) is not int:
            raise ApiError("CORE_INVALID_INPUT", "reference_revision is required")
        batch = self.get(batch_id)
        fingerprint = hashlib.sha256(canonical(body).encode()).hexdigest()
        old = batch.get("confirmations", {}).get(key)
        if old:
            if old["fingerprint"] != fingerprint:
                raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Confirmation key has different content", 409)
            return batch, False
        if batch["state"] != "awaiting_reference_confirmation" or batch.get("cancel_requested"):
            raise ApiError("CORE_BATCH_STATE", "Batch is not awaiting reference confirmation", 409)
        reference = self.store.group(batch["group_id"]).get("reference")
        if not reference or reference["revision"] != body["reference_revision"]:
            raise ApiError("CORE_GROUP_STALE", "Reference changed; refresh before confirming", 409)
        sequence = batch.get("confirmation_sequence", 0) + 1
        batch.setdefault("confirmations", {})[key] = {"fingerprint": fingerprint, "reference_revision": reference["revision"], "sequence": sequence}
        batch.update(accepted_reference=dict(reference), reference=None, group_run_id=None, confirmation_sequence=sequence,
                     state="running", error=None)
        self.save(batch)
        self.advance(self.get(batch_id))
        return self.get(batch_id), True

    def attach(self, app):
        async def collection(request):
            group_id = request.match_info["id"]
            if request.method == "GET": return web.json_response({"items": self.list(group_id)})
            result, created = self.submit(group_id, request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(result, status=202 if created else 200)
        async def detail(request): return web.json_response(self.get(request.match_info["id"]))
        async def cancel(request): return web.json_response(self.cancel(request.match_info["id"]))
        async def confirm(request):
            result, created = self.confirm_reference(request.match_info["id"], request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(result, status=202 if created else 200)
        app.add_routes([web.get("/v1/groups/{id}/batches", collection), web.post("/v1/groups/{id}/batches", collection),
                        web.get("/v1/group-batches/{id}", detail), web.post("/v1/group-batches/{id}/cancel", cancel),
                        web.post("/v1/group-batches/{id}/confirm-reference", confirm)])
