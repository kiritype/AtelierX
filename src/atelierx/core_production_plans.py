"""Durable fragment production plans; total queue size is not a dispatch limit."""
import hashlib
import json
import time
import uuid

from aiohttp import web

from .common import ApiError, canonical

TERMINAL = {"completed", "failed", "cancelled", "insufficient_images"}
ITEM_DONE = {"passed", "single_failed", "generation_failed", "cancelled"}
WINDOW = 8
TARGET_CHUNK = 32


def bad(message, code="CORE_INVALID_INPUT", status=400):
    raise ApiError(code, message, status)


def paging(query):
    try:
        limit, offset = int(query.get("limit", 50)), int(query.get("offset", 0))
    except (TypeError, ValueError):
        bad("Invalid pagination")
    if not 1 <= limit <= 200 or not 0 <= offset <= 2**63 - 1:
        bad("Invalid pagination")
    return limit, offset


class ProductionPlans:
    def __init__(self, core):
        self.core, self.db = core, core.store.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS production_plans
            (id TEXT PRIMARY KEY, request_key TEXT UNIQUE, fingerprint TEXT, state TEXT, document TEXT);
          CREATE TABLE IF NOT EXISTS production_plan_items
            (plan_id TEXT, item_index INTEGER, state TEXT, document TEXT, PRIMARY KEY(plan_id,item_index));
          CREATE INDEX IF NOT EXISTS production_plan_item_state ON production_plan_items(plan_id,state,item_index);
          CREATE TABLE IF NOT EXISTS production_plan_comparisons
            (plan_id TEXT, sequence INTEGER, chunk_index INTEGER, state TEXT, document TEXT,
             PRIMARY KEY(plan_id,sequence,chunk_index));
        """)

    def get(self, plan_id):
        row = self.db.execute("SELECT document FROM production_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            bad("Production plan not found", "CORE_NOT_FOUND", 404)
        plan = json.loads(row[0])
        plan["counts"] = {row[0]: row[1] for row in self.db.execute(
            "SELECT state,count(*) FROM production_plan_items WHERE plan_id=? GROUP BY state", (plan_id,))}
        return plan

    def save(self, plan):
        value = dict(plan)
        value.pop("counts", None)
        with self.db:
            self.db.execute("UPDATE production_plans SET state=?,document=? WHERE id=?",
                            (value["state"], canonical(value), value["id"]))

    def list(self, query):
        limit, offset = paging(query)
        ids = [r[0] for r in self.db.execute("SELECT id FROM production_plans ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset))]
        return {"items": [self.get(i) for i in ids], "limit": limit, "offset": offset,
                "total": self.db.execute("SELECT count(*) FROM production_plans").fetchone()[0]}

    def items(self, plan_id, query):
        self.get(plan_id)
        limit, offset = paging(query)
        rows = self.db.execute("SELECT document FROM production_plan_items WHERE plan_id=? ORDER BY item_index LIMIT ? OFFSET ?", (plan_id, limit, offset))
        return {"items": [json.loads(row[0]) for row in rows], "limit": limit, "offset": offset,
                "total": self.db.execute("SELECT count(*) FROM production_plan_items WHERE plan_id=?", (plan_id,)).fetchone()[0]}

    def item_save(self, plan_id, item):
        with self.db:
            self.db.execute("UPDATE production_plan_items SET state=?,document=? WHERE plan_id=? AND item_index=?",
                            (item["state"], canonical(item), plan_id, item["index"]))

    def create(self, key, body):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            bad("Idempotency-Key required")
        allowed = {"group_id", "fragments", "generation_inputs", "presets", "postprocess", "validation", "group_validation"}
        if not isinstance(body, dict) or set(body) - allowed or not {"group_id", "fragments", "validation", "group_validation"} <= set(body):
            bad("group_id, fragments, single and group validation are required")
        fingerprint = hashlib.sha256(canonical(body).encode()).hexdigest()
        old = self.db.execute("SELECT id,fingerprint FROM production_plans WHERE request_key=?", (key,)).fetchone()
        if old:
            if old[1] != fingerprint:
                bad("Plan key has different content", "CORE_IDEMPOTENCY_CONFLICT", 409)
            return self.get(old[0]), False
        selections = body["fragments"]
        if not isinstance(selections, list) or not selections:
            bad("Select at least one fragment")
        if any(not isinstance(s, dict) or set(s) != {"id", "revision"} or not isinstance(s["id"], str) for s in selections):
            bad("Each fragment requires id and revision")
        if len({s["id"] for s in selections}) != len(selections):
            bad("Select each fragment once")
        frozen_validation = self.core.validation.freeze_group(body["group_validation"])
        if frozen_validation["profile"].get("consistency") is not True:
            bad("Select a group consistency profile")
        group = self.core.store.group(body["group_id"])
        plan = {"id": str(uuid.uuid4()), "state": "draft", "total": len(selections), "created_at": time.time(),
                "group_id": group["id"], "accepted_reference": group.get("reference"), "reference": None,
                "sequence": 0, "group_validation": body["group_validation"], "group_validation_frozen": frozen_validation,
                "cancel_requested": False, "error": None, "outcome": None, "confirmations": {}}
        base = {k: v for k, v in body.items() if k not in {"fragments", "group_validation"}}
        digest = hashlib.sha256(canonical({"request": body, "group_validation": frozen_validation}).encode())
        # All selected items are accepted durably, without creating GPU tasks.
        # Rows keep large snapshots out of the list/status response.
        with self.db:
            for index, selection in enumerate(selections):
                preview = self.core.preview(dict(base, fragment=selection))
                digest.update(preview["preview_hash"].encode())
                item = {"index": index, "state": "queued", "snapshot": preview["snapshot"],
                        "preview_hash": preview["preview_hash"], "fragment": selection,
                        "task_id": None, "active_task_id": None, "passed_image_ids": [], "error": None}
                self.db.execute("INSERT INTO production_plan_items VALUES(?,?,?,?)",
                                (plan["id"], index, "queued", canonical(item)))
            plan["plan_hash"] = digest.hexdigest()
            self.db.execute("INSERT INTO production_plans VALUES(?,?,?,?,?)",
                            (plan["id"], key, fingerprint, "draft", canonical(plan)))
        return self.get(plan["id"]), True

    def start(self, plan_id, body):
        plan = self.get(plan_id)
        if not isinstance(body, dict) or set(body) != {"plan_hash"} or body["plan_hash"] != plan["plan_hash"]:
            bad("Confirm the frozen plan hash", "CORE_PREVIEW_STALE", 409)
        if plan["state"] == "draft":
            plan["state"] = "running"
            self.save(plan)
        return self.get(plan_id)

    def comparisons(self, plan_id):
        plan = self.get(plan_id)
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT document FROM production_plan_comparisons WHERE plan_id=? AND sequence=? ORDER BY chunk_index", (plan_id, plan["sequence"]))]

    def compare_save(self, plan, item):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO production_plan_comparisons VALUES(?,?,?,?,?)",
                (plan["id"], plan["sequence"], item["index"], item["state"], canonical(item)))

    def recover_comparison_links(self, plan):
        """Link a persisted group Run after interruption before ``compare_save``.

        The child is idempotently named from the plan/sequence/chunk.  Without
        this recovery, cancelling immediately after that narrow interruption
        could mark the plan terminal while leaving the active remote comparison.
        """
        finder = getattr(self.core.groups, "runs_with_key_prefix", None)
        if not finder:
            return
        prefix = f"production-plan-group:{plan['id']}:{plan['sequence']}:"
        known = {item["index"] for item in self.comparisons(plan["id"])}
        for run in finder(prefix):
            try:
                index = int(run.get("request_key", "").rsplit(":", 1)[1])
            except (AttributeError, IndexError, ValueError):
                continue
            if index not in known:
                self.compare_save(plan, {"index": index, "run_id": run["id"], "state": run["state"],
                                         "outcome": run.get("outcome"), "error": run.get("error")})

    def cancel(self, plan_id):
        plan = self.get(plan_id)
        if plan["state"] in TERMINAL:
            return plan
        plan.update(cancel_requested=True, state="cancellation_pending")
        self.save(plan)
        self.cancel_queued(plan_id)
        return self.get(plan_id)

    def cancel_queued(self, plan_id):
        # Recover a Task committed just before interruption of its item linkage.
        rows = self.db.execute("""SELECT i.document, t.id FROM production_plan_items i
            JOIN tasks t ON t.request_key = 'production-plan:' || i.plan_id || ':' || i.item_index
            WHERE i.plan_id=? AND i.state='queued'""", (plan_id,)).fetchall()
        for row in rows:
            item = json.loads(row[0])
            item.update(task_id=row[1], active_task_id=row[1], state="generation_pending")
            self.item_save(plan_id, item)
        with self.db:
            self.db.execute("UPDATE production_plan_items SET state='cancelled',document=json_set(document,'$.state','cancelled') WHERE plan_id=? AND state='queued'", (plan_id,))

    def confirm(self, plan_id, key, body):
        plan = self.get(plan_id)
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or not isinstance(body, dict) or set(body) != {"reference_revision"} or type(body["reference_revision"]) is not int:
            bad("Confirmation key and reference_revision required")
        old = plan["confirmations"].get(key)
        if old is not None:
            if old != body["reference_revision"]:
                bad("Confirmation key conflict", "CORE_IDEMPOTENCY_CONFLICT", 409)
            return plan
        reference = self.core.store.group(plan["group_id"]).get("reference")
        if plan["state"] != "awaiting_reference_confirmation" or plan["cancel_requested"]:
            bad("Plan is not awaiting reference confirmation", "CORE_BATCH_STATE", 409)
        if not reference or reference["revision"] != body["reference_revision"]:
            bad("Reference changed", "CORE_GROUP_STALE", 409)
        plan["confirmations"][key] = body["reference_revision"]
        plan.update(accepted_reference=reference, reference=None, state="running", sequence=plan["sequence"] + 1, error=None)
        self.save(plan)
        return self.get(plan_id)

    def advance(self, plan):
        pid = plan["id"]
        self.recover_comparison_links(plan)
        if plan["cancel_requested"]:
            # Repeat after reload if interruption occurred between intent and row updates.
            self.cancel_queued(pid)
        active = [json.loads(r[0]) for r in self.db.execute(
            "SELECT document FROM production_plan_items WHERE plan_id=? AND state IN ('generation_pending','single_validation_pending')", (pid,))]
        for item in active:
            if plan["cancel_requested"]:
                task = self.core.store.task(item["active_task_id"])
                cycle = self.core.store.cycle(task["regeneration"]["cycle_id"])
                self.core.regeneration.stop(cycle["id"])
                task = self.core.store.task(cycle["active_task_id"])
                for image in task["images"]:
                    for run in self.core.store.image_validations(image["id"]):
                        self.core.validation.cancel(run["id"])
                if task["state"] not in {"generated", "failed", "cancelled"}:
                    continue
                if any(run["state"] not in {"completed", "failed", "cancelled"} for image in task["images"] for run in self.core.store.image_validations(image["id"])):
                    continue
                item["state"] = "cancelled"
            else:
                self.core.batches._observe_item(item)
            self.item_save(pid, item)
        counts = self.get(pid)["counts"]
        pending = counts.get("generation_pending", 0) + counts.get("single_validation_pending", 0)
        if plan["cancel_requested"]:
            waiting = False
            for chunk in self.comparisons(pid):
                run = self.core.groups.get(chunk["run_id"])
                if run["state"] not in {"completed", "failed", "cancelled"}:
                    self.core.groups.cancel(run["id"])
                    waiting = True
            if not pending and not waiting:
                plan["state"] = "failed" if plan.get("error") else "cancelled"
                if plan.get("error"):
                    plan["outcome"] = "error"
                self.save(plan)
            return
        if plan["state"] == "awaiting_reference_confirmation":
            return
        capacity = max(0, WINDOW - pending)
        queued = [json.loads(r[0]) for r in self.db.execute(
            "SELECT document FROM production_plan_items WHERE plan_id=? AND state='queued' ORDER BY item_index LIMIT ?", (pid, capacity))]
        for item in queued:
            key = f"production-plan:{pid}:{item['index']}"
            fingerprint = item["preview_hash"]
            old = self.core.store.by_key(key)
            if old and old[0] != fingerprint:
                bad("Plan task key conflicts", "CORE_IDEMPOTENCY_CONFLICT", 409)
            task = old[1] if old else self.core.store.create_task(key, fingerprint, plan["group_id"], item["snapshot"])
            item.update(task_id=task["id"], active_task_id=task["id"], state="generation_pending")
            self.item_save(pid, item)
        if queued or pending or counts.get("queued", 0):
            return
        self.advance_comparisons(plan)

    def advance_comparisons(self, plan):
        reference = self.core.store.group(plan["group_id"]).get("reference")
        chunks = self.comparisons(plan["id"])
        if reference != plan["accepted_reference"] or not reference:
            for chunk in chunks:
                if self.core.groups.get(chunk["run_id"])["state"] not in {"completed", "failed", "cancelled"}:
                    self.core.groups.cancel(chunk["run_id"])
            # A reference cannot change the meaning of already completed chunks.
            passed_count = sum(len(json.loads(r[0])["passed_image_ids"]) for r in self.db.execute(
                "SELECT document FROM production_plan_items WHERE plan_id=? AND state='passed'", (plan["id"],)))
            plan["state"] = "insufficient_images" if not reference and passed_count < 2 else "awaiting_reference_confirmation"
            self.save(plan)
            return
        refs = {reference["representative_id"], *reference["auxiliary_ids"]}
        targets = []
        for row in self.db.execute("SELECT document FROM production_plan_items WHERE plan_id=? AND state='passed' ORDER BY item_index", (plan["id"],)):
            targets.extend(i for i in json.loads(row[0])["passed_image_ids"] if i not in refs)
        if not targets:
            plan["state"] = "insufficient_images"
            self.save(plan)
            return
        # Only one chunk is in flight per plan; every chunk shares the same reference.
        for chunk in chunks:
            run = self.core.groups.get(chunk["run_id"])
            if run["state"] not in {"completed", "failed", "cancelled"}:
                return
            chunk.update(state=run["state"], outcome=run.get("outcome"), error=run.get("error"))
            self.compare_save(plan, chunk)
        index = len(chunks)
        if index * TARGET_CHUNK < len(targets):
            run, _ = self.core.groups.submit(plan["group_id"], f"production-plan-group:{plan['id']}:{plan['sequence']}:{index}",
                {"reference_revision": reference["revision"], "target_ids": targets[index * TARGET_CHUNK:(index + 1) * TARGET_CHUNK],
                 "validation": plan["group_validation"]}, plan["group_validation_frozen"])
            self.compare_save(plan, {"index": index, "run_id": run["id"], "state": run["state"], "outcome": run.get("outcome")})
            plan.update(state="group_validation_pending", reference=reference)
            self.save(plan)
            return
        counts = self.get(plan["id"])["counts"]
        failed_items = sum(counts.get(s, 0) for s in ("single_failed", "generation_failed", "cancelled"))
        outcomes = [c.get("outcome") for c in self.comparisons(plan["id"])]
        outcome = "error" if "error" in outcomes else "failed" if "failed" in outcomes else "passed" if not failed_items and all(o == "passed" for o in outcomes) else "incomplete"
        plan.update(state="completed", outcome=outcome)
        self.save(plan)

    async def tick(self):
        ids = [r[0] for r in self.db.execute("SELECT id FROM production_plans WHERE state NOT IN ('draft','completed','failed','cancelled','insufficient_images')")]
        for pid in ids:
            try:
                self.advance(self.get(pid))
            except ApiError as exc:
                plan = self.get(pid)
                # Stop dispatch, but keep observing until previously accepted work is stopped.
                # A terminal failure here would orphan in-flight tasks across restarts.
                plan.update(state="cancellation_pending", cancel_requested=True, outcome="error")
                if not plan.get("error"):
                    plan["error"] = {"code": exc.code, "message": exc.message}
                self.save(plan)

    def attach(self, app):
        async def collection(request):
            if request.method == "GET":
                return web.json_response(self.list(request.query))
            result, created = self.create(request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(result, status=201 if created else 200)
        async def detail(request):
            return web.json_response(self.get(request.match_info["id"]))
        async def by_key(request):
            row = self.db.execute("SELECT id FROM production_plans WHERE request_key=?", (request.headers.get("Idempotency-Key"),)).fetchone()
            if not row:
                bad("Production plan not found", "CORE_NOT_FOUND", 404)
            return web.json_response(self.get(row[0]))
        async def items(request):
            return web.json_response(self.items(request.match_info["id"], request.query))
        async def comparisons(request):
            return web.json_response({"items": self.comparisons(request.match_info["id"])})
        async def start(request):
            return web.json_response(self.start(request.match_info["id"], await request.json()), status=202)
        async def cancel(request):
            return web.json_response(self.cancel(request.match_info["id"]), status=202)
        async def confirm(request):
            return web.json_response(self.confirm(request.match_info["id"], request.headers.get("Idempotency-Key"), await request.json()), status=202)
        base = "/v1/production-plans"
        app.add_routes([web.get(base, collection), web.post(base, collection), web.get(base + "/by-key", by_key), web.get(base + "/{id}", detail),
                        web.get(base + "/{id}/items", items), web.get(base + "/{id}/comparisons", comparisons),
                        web.post(base + "/{id}/start", start), web.post(base + "/{id}/cancel", cancel),
                        web.post(base + "/{id}/confirm-reference", confirm)])
