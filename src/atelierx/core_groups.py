"""Frozen group comparison requests; reference edits never launch generation."""
import hashlib
import json
import re
import time
import uuid
from aiohttp import web
from .common import ApiError, canonical
from .group_validation import normalize, summary

TERMINAL = {"completed", "failed", "cancelled"}


class CoreGroups:
    def __init__(self, core):
        self.core, self.store = core, core.store
        self.store.db.execute("CREATE TABLE IF NOT EXISTS group_runs (id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, document TEXT NOT NULL)")
        self.store.db.execute("CREATE TABLE IF NOT EXISTS group_replacements (id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, document TEXT NOT NULL)")
        self.store.db.commit()

    def images(self, group_id):
        self.store.group(group_id)
        items = [json.loads(row[0]) for row in self.store.db.execute("SELECT document FROM images")]
        return [item for item in items if item.get("group_id") == group_id]

    def eligible(self, group_id, image_id):
        image = self.store.image(image_id)
        if image.get("group_id") != group_id or (image.get("validation") or {}).get("outcome") != "passed":
            raise ApiError("CORE_GROUP_IMAGE_INELIGIBLE", "Select a single-validation passed image in this group", 409)
        task = self.store.task(image["task_id"])
        if task["snapshot"]["generation_endpoint"] != self.core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Image belongs to another Generation endpoint", 409)
        return image, task

    @staticmethod
    def _terms(value):
        """Stable, deliberately simple identity-term matching for evidence coverage."""
        return {term for term in re.findall(r"[\w가-힣]{2,}", value.casefold()) if term not in {"with", "and", "the"}}

    def reference_candidate(self, group_id):
        """Return a deterministic proposal; it never writes or replaces a reference."""
        group = self.store.group(group_id)
        existing = group.get("reference")
        candidates = []
        for image in self.images(group_id):
            validation = image.get("validation") or {}
            if validation.get("outcome") != "passed":
                continue
            evidence = (validation.get("result") or {}).get("evidence")
            if not isinstance(evidence, list):
                continue
            visible = []
            # Group comparison sends only visible, nonempty identity fields.
            # Empty optional components must not make a reference insufficient.
            for feature, expected in group["components"].items():
                if not expected.strip():
                    continue
                expected_terms = self._terms(expected)
                matching = [item for item in evidence if isinstance(item, dict) and item.get("status") == "matched"
                            and isinstance(item.get("observed"), str) and item["observed"].strip()
                            and isinstance(item.get("location"), str) and item["location"].strip()
                            and expected_terms & self._terms(" ".join(str(item.get(k, "")) for k in ("requirement", "source_clause", "observed")))]
                if matching:
                    visible.append(feature)
            # created_at/id are fixed tie-breakers.  More visible identity areas first.
            candidates.append({"image_id": image["id"], "visible_components": visible,
                               "matched_evidence": sum(1 for item in evidence if isinstance(item, dict) and item.get("status") == "matched"),
                               "tie_break": [image.get("created_at", 0), image["id"]]})
        candidates.sort(key=lambda item: (-len(item["visible_components"]), -item["matched_evidence"], item["tie_break"][0], item["tie_break"][1]))
        if existing:
            conflicting = any(run["request"]["reference_revision"] == existing["revision"] and run.get("result")
                              and any(item.get("status") == "reference_conflict" for item in run["result"].get("items", []))
                              for run in self.runs(group_id))
            return {"state": "reference_conflict" if conflicting else "existing_reference_retained", "reference": existing, "candidates": candidates,
                    "reason": "An existing reference is never automatically replaced"}
        if not candidates:
            return {"state": "awaiting_single_pass", "candidates": [], "reason": "No passed image has usable single-validation evidence"}
        representative = candidates[0]
        covered, auxiliaries = set(representative["visible_components"]), []
        for candidate in candidates[1:]:
            adds = set(candidate["visible_components"]) - covered
            if adds and len(auxiliaries) < 2:
                auxiliaries.append(candidate["image_id"])
                covered.update(adds)
        missing = [feature for feature, expected in group["components"].items() if expected.strip() and feature not in covered]
        return {"state": "ready_for_confirmation" if not missing else "insufficient_reference_evidence",
                "revision": 0, "representative_id": representative["image_id"], "auxiliary_ids": auxiliaries,
                "covered_components": sorted(covered), "missing_components": missing, "candidates": candidates,
                "reason": "Candidates are ordered by visible identity components, matched evidence, creation time, then image ID"}

    def reference(self, group_id, body):
        if not isinstance(body, dict) or set(body) != {"revision", "representative_id", "auxiliary_ids"}:
            raise ApiError("CORE_INVALID_INPUT", "revision, representative_id and auxiliary_ids are required")
        group = self.store.group(group_id)
        previous = group.get("reference", {"revision": 0})
        if type(body["revision"]) is not int or previous["revision"] != body["revision"]:
            raise ApiError("CORE_GROUP_STALE", "Reference changed; fetch current group before requesting", 409)
        if not isinstance(body["auxiliary_ids"], list) or len(body["auxiliary_ids"]) > 2:
            raise ApiError("CORE_INVALID_INPUT", "At most two auxiliary images supported")
        ids = [body["representative_id"], *body["auxiliary_ids"]]
        if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ApiError("CORE_INVALID_INPUT", "Reference IDs must be distinct strings")
        for image_id in ids: self.eligible(group_id, image_id)
        group["reference"] = {"revision": previous["revision"] + 1, "representative_id": ids[0], "auxiliary_ids": ids[1:]}
        with self.store.db:
            self.store.db.execute("UPDATE groups SET document=? WHERE id=?", (canonical(group), group_id))
        return group

    def image_payload(self, group_id, image_id):
        image, task = self.eligible(group_id, image_id)
        gen = task["snapshot"]["generation_inputs"]
        return {"ref": image_id, "positive_prompt": gen["positive_prompt"], "negative_prompt": gen["negative_prompt"],
                "negative_sources": task["snapshot"].get("negative_sources", {"global": gen["negative_prompt"], "character": ""}),
                "source": {"type": "generation", "server_id": self.core.validation.config.get("generation_server_id", "generation-local"),
                           "image_id": image["generation_image_id"], "sha256": image["sha256"]}}

    def get(self, run_id):
        row = self.store.db.execute("SELECT document FROM group_runs WHERE id=?", (run_id,)).fetchone()
        if not row: raise ApiError("CORE_NOT_FOUND", "Group run not found", 404)
        return json.loads(row[0])

    def save(self, run):
        current = self.get(run["id"])
        if current["state"] in TERMINAL: return
        if current.get("cancel_requested"):
            run["cancel_requested"] = True
            if run["state"] in TERMINAL:
                run.update(state="cancelled", outcome=None, result=None)
        with self.store.db:
            self.store.db.execute("UPDATE group_runs SET document=? WHERE id=?", (canonical(run), run["id"]))

    def public(self, run):
        current = self.store.group(run["group_id"]).get("reference", {})
        return dict(run, current_reference=current.get("revision") == run["request"]["reference_revision"])

    def submit(self, group_id, key, body, frozen_validation=None):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key required")
        if not isinstance(body, dict) or set(body) != {"reference_revision", "target_ids", "validation"}:
            raise ApiError("CORE_INVALID_INPUT", "reference_revision, target_ids and validation required")
        fp = hashlib.sha256(canonical({"group_id": group_id, "body": body}).encode()).hexdigest()
        existing = self.store.db.execute("SELECT fingerprint,document FROM group_runs WHERE request_key=?", (key,)).fetchone()
        if existing:
            if existing[0] != fp: raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Group key has different content", 409)
            return self.public(json.loads(existing[1])), False
        group = self.store.group(group_id)
        reference = group.get("reference")
        if not reference or type(body["reference_revision"]) is not int or body["reference_revision"] != reference["revision"]:
            raise ApiError("CORE_GROUP_STALE", "Select or refresh group reference", 409)
        targets = body["target_ids"]
        if not isinstance(targets, list) or not 1 <= len(targets) <= 32 or any(not isinstance(i, str) for i in targets) or len(set(targets)) != len(targets):
            raise ApiError("CORE_INVALID_INPUT", "Select 1..32 distinct targets")
        refs = [reference["representative_id"], *reference["auxiliary_ids"]]
        if set(targets) & set(refs): raise ApiError("CORE_INVALID_INPUT", "Comparison targets and references are separate")
        for old in self.runs(group_id):
            if old["state"] not in TERMINAL and set(targets) & {i["ref"] for i in old["request"]["targets"]}:
                raise ApiError("CORE_GROUP_ACTIVE", "Selected targets already have an active group run", 409)
        frozen = frozen_validation if frozen_validation is not None else dict(self.core.validation.settings.freeze_group(body["validation"], self.core.validation.config.get("providers", {}).get(body["validation"]["provider_id"])), endpoint=self.core.validation.url)
        if not isinstance(frozen, dict) or set(frozen) != {"selection", "profile", "provider", "endpoint"}:
            raise ApiError("CORE_INVALID_INPUT", "Saved group validation selection is invalid")
        if set(frozen["profile"]) != {"profile_id", "revision", "consistency"} or frozen["profile"]["consistency"] is not True:
            raise ApiError("CORE_INVALID_INPUT", "Select a dedicated group profile")
        payload = {"group_id": group_id, "reference_revision": reference["revision"], "representative": self.image_payload(group_id, refs[0]),
                   "auxiliaries": [self.image_payload(group_id, i) for i in refs[1:]], "targets": [self.image_payload(group_id, i) for i in targets],
                   "identity": {k: v for k, v in group["components"].items() if v.strip()}, "profile": frozen["profile"], "provider": frozen["provider"]}
        run = {"id": str(uuid.uuid4()), "group_id": group_id, "created_at": time.time(), "state": "queued", "request": payload,
               "endpoint": frozen["endpoint"], "job_id": None, "outcome": None, "result": None, "error": None}
        with self.store.db:
            self.store.db.execute("INSERT INTO group_runs VALUES(?,?,?,?)", (run["id"], key, fp, canonical(run)))
        return self.public(run), True

    def runs(self, group_id=None):
        items = [json.loads(row[0]) for row in self.store.db.execute("SELECT document FROM group_runs")]
        return sorted([i for i in items if group_id is None or i["group_id"] == group_id], key=lambda r: (r["created_at"], r["id"]))

    def replacements(self, group_id=None):
        items = [json.loads(row[0]) for row in self.store.db.execute("SELECT document FROM group_replacements")]
        return sorted([item for item in items if group_id is None or item["group_id"] == group_id], key=lambda r: (r["created_at"], r["id"]))

    def replacement_get(self, replacement_id):
        row = self.store.db.execute("SELECT document FROM group_replacements WHERE id=?", (replacement_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Group replacement not found", 404)
        return json.loads(row[0])

    def runs_with_key_prefix(self, prefix):
        """Recovery lookup for a durable parent record missing its child link."""
        return [dict(json.loads(row[1]), request_key=row[0]) for row in self.store.db.execute(
            "SELECT request_key,document FROM group_runs WHERE request_key LIKE ? ORDER BY request_key", (prefix + "%",))]

    def replacement_save(self, replacement):
        with self.store.db:
            self.store.db.execute("UPDATE group_replacements SET document=? WHERE id=?", (canonical(replacement), replacement["id"]))

    def current_target_ids(self, group_id):
        """Exclude only replacement descendants that were not the selected output.

        Original PNG/WebP siblings remain independent targets.  A record whose
        task was never created leaves its source current after a local rejection.
        """
        images = self.images(group_id)
        by_task = {}
        for image in images:
            by_task.setdefault(image["task_id"], []).append(image)
        tasks = [self.store.task(row[0]) for row in self.store.db.execute("SELECT id FROM tasks")]
        children = {}
        for task in tasks:
            parent = (task.get("regeneration") or {}).get("parent_task_id")
            if parent: children.setdefault(parent, set()).add(task["id"])
        excluded, superseded = set(), set()
        for replacement in self.replacements(group_id):
            task_ids = [*replacement.get("attempt_task_ids", []), *([replacement["replacement_task_id"]] if replacement.get("replacement_task_id") else [])]
            if task_ids:
                superseded.add(replacement["source_image_id"])
                descendants, pending = set(), task_ids
                while pending:
                    current = pending.pop()
                    if current in descendants: continue
                    descendants.add(current)
                    pending.extend(children.get(current, ()))
                for descendant in descendants:
                    excluded.update(image["id"] for image in by_task.get(descendant, ()))
                if replacement.get("replacement_image_id"):
                    excluded.discard(replacement["replacement_image_id"])
            elif replacement["state"] == "creating":
                superseded.add(replacement["source_image_id"])
        return [image["id"] for image in images
                if (image.get("validation") or {}).get("outcome") == "passed" and image["id"] not in superseded | excluded]

    def request_replacement(self, group_id, key, body):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key required")
        if not isinstance(body, dict) or set(body) != {"reference_revision", "target_image_id", "regeneration", "group_validation"}:
            raise ApiError("CORE_INVALID_INPUT", "reference_revision, target_image_id, regeneration and group_validation required")
        fp = hashlib.sha256(canonical({"group_id": group_id, "body": body}).encode()).hexdigest()
        old = self.store.db.execute("SELECT fingerprint,document FROM group_replacements WHERE request_key=?", (key,)).fetchone()
        if old:
            if old[0] != fp:
                raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Group replacement key has different content", 409)
            return json.loads(old[1]), False
        group = self.store.group(group_id)
        reference = group.get("reference")
        if not reference or type(body["reference_revision"]) is not int or body["reference_revision"] != reference["revision"]:
            raise ApiError("CORE_GROUP_STALE", "Reference changed; confirm the current reference before regenerating", 409)
        source, source_task = self.eligible(group_id, body["target_image_id"])
        if source["id"] not in self.current_target_ids(group_id):
            raise ApiError("CORE_GROUP_STALE", "Target was replaced or is no longer current", 409)
        if source["id"] in {reference["representative_id"], *reference["auxiliary_ids"]}:
            raise ApiError("CORE_INVALID_INPUT", "Reference images cannot be selected as comparison targets")
        if not isinstance(body["regeneration"], dict):
            raise ApiError("CORE_REGENERATION_INVALID", "regeneration must be an object")
        frozen_group_validation = dict(self.core.validation.settings.freeze_group(body["group_validation"], self.core.validation.config.get("providers", {}).get(body["group_validation"]["provider_id"])), endpoint=self.core.validation.url)
        if frozen_group_validation["profile"].get("consistency") is not True:
            raise ApiError("CORE_INVALID_INPUT", "Select a dedicated group profile")
        # A group replacement always needs a new single-image decision.  The
        # regular manual endpoint may deliberately omit validation, this one may not.
        proposed = self.core.regeneration.snapshot(source_task, body["regeneration"], manual=True)
        if not proposed.get("validation"):
            raise ApiError("CORE_REGENERATION_INVALID", "Group replacement requires single-image validation")
        index = next((i for i, image in enumerate(source_task["images"]) if image["id"] == source["id"]), None)
        if index is None:
            raise ApiError("CORE_GROUP_STALE", "Selected image is absent from its saved generation", 409)
        replacement = {"id": str(uuid.uuid4()), "group_id": group_id, "request_key": key, "created_at": time.time(),
                       "state": "creating", "reference": dict(reference), "source_image_id": source["id"],
                       "source_task_id": source_task["id"], "source_generation_image_id": source["generation_image_id"],
                       "source_sha256": source["sha256"], "source_output_index": index, "source_media_type": source["media_type"],
                       "regeneration": body["regeneration"], "replacement_snapshot": proposed,
                       "group_validation": body["group_validation"], "group_validation_frozen": frozen_group_validation,
                       "replacement_task_id": None, "attempt_task_ids": [], "replacement_image_id": None,
                       "single_validation_run_id": None, "group_run_id": None, "error": None}
        with self.store.db:
            self.store.db.execute("INSERT INTO group_replacements VALUES(?,?,?,?)", (replacement["id"], key, fp, canonical(replacement)))
        # Persisted before creating the task.  A restart calls this same internal
        # idempotency key rather than emitting a second generation request.
        self.advance_replacement(replacement)
        return self.replacement_get(replacement["id"]), True

    def _replacement_error(self, replacement, code, message, state="error"):
        replacement.update(state=state, error={"code": code, "message": message})
        self.replacement_save(replacement)

    def advance_replacement(self, replacement):
        if replacement["state"] == "creating":
            try:
                required = {"source_generation_image_id", "source_sha256", "source_media_type", "replacement_snapshot"}
                if not required.issubset(replacement):
                    self._replacement_error(replacement, "CORE_REPLACEMENT_SNAPSHOT_MISSING", "Replacement record lacks the frozen creation snapshot"); return
                current = self.store.group(replacement["group_id"]).get("reference")
                if current != replacement["reference"]:
                    self._replacement_error(replacement, "CORE_GROUP_STALE", "Reference changed before replacement generation started", "stale_reference"); return
                source, source_task = self.eligible(replacement["group_id"], replacement["source_image_id"])
                if (source.get("generation_image_id"), source.get("sha256"), source.get("media_type")) != (
                    replacement["source_generation_image_id"], replacement["source_sha256"], replacement["source_media_type"]):
                    self._replacement_error(replacement, "CORE_GROUP_STALE", "Selected target changed before replacement generation started", "stale_reference"); return
                if source_task.get("cancel_requested") or source_task["state"] == "cancelled":
                    self._replacement_error(replacement, "CORE_REPLACEMENT_CANCELLED", "Selected source was cancelled", "cancelled"); return
                task, _ = self.core.regeneration.manual(replacement["source_task_id"], "group-replacement-task:" + replacement["id"], replacement["regeneration"], replacement["replacement_snapshot"])
                replacement.update(state="generation_pending", replacement_task_id=task["id"], attempt_task_ids=[task["id"]])
                self.replacement_save(replacement)
            except ApiError as exc:
                self._replacement_error(replacement, exc.code, exc.message)
            return
        if replacement["state"] == "generation_pending":
            task = self.store.task(replacement["replacement_task_id"])
            if task.get("cancel_requested") or task["state"] == "cancelled":
                self._replacement_error(replacement, "CORE_REPLACEMENT_CANCELLED", "Replacement generation was cancelled", "cancelled"); return
            if task["state"] == "failed":
                self._replacement_error(replacement, "CORE_REPLACEMENT_GENERATION_FAILED", "Replacement generation failed"); return
            if task["state"] != "generated": return
            index = replacement["source_output_index"]
            if index >= len(task["images"]):
                self._replacement_error(replacement, "CORE_REPLACEMENT_OUTPUT_MISSING", "Replacement did not produce the selected output derivative"); return
            image = task["images"][index]
            if image.get("media_type") != replacement["source_media_type"]:
                self._replacement_error(replacement, "CORE_REPLACEMENT_OUTPUT_MISMATCH", "Replacement output derivative media type changed"); return
            replacement.update(state="single_validation_pending", replacement_image_id=image["id"])
            self.replacement_save(replacement)
            return
        if replacement["state"] == "single_validation_pending":
            task = self.store.task(replacement["replacement_task_id"])
            cycle = self.store.cycle(task["regeneration"]["cycle_id"])
            if cycle["active_task_id"] != task["id"]:
                # A normal single-validation automatic retry selected a new
                # descendant.  Preserve all earlier attempts but only its same
                # derivative may become the current group target.
                replacement["replacement_task_id"] = cycle["active_task_id"]
                replacement["attempt_task_ids"] = [*replacement.get("attempt_task_ids", []), cycle["active_task_id"]]
                replacement.update(state="generation_pending", replacement_image_id=None, single_validation_run_id=None)
                self.replacement_save(replacement); return
            # A selected output can pass while a PNG/WebP sibling is still being
            # checked.  Do not freeze a group comparison until the whole cycle
            # settles, because that sibling may legitimately spawn a child.
            if cycle["state"] == "active":
                self.replacement_save(replacement); return
            if cycle["state"] in {"error", "cancelled", "stopped", "limit_reached", "proposal_unavailable", "automatic_disabled"}:
                self._replacement_error(replacement, "CORE_REPLACEMENT_SINGLE_FAILED", "Replacement single-image cycle ended without a passed selected output", "cancelled" if cycle["state"] == "cancelled" else "error"); return
            if cycle["state"] != "passed":
                self._replacement_error(replacement, "CORE_REPLACEMENT_SINGLE_FAILED", "Replacement single-image cycle did not finish successfully"); return
            image = self.store.image(replacement["replacement_image_id"])
            validation = image.get("validation") or {}
            if validation.get("id"): replacement["single_validation_run_id"] = validation["id"]
            if validation.get("state") in {"queued", "dispatching", "pending", "running", "not_requested", None}:
                self.replacement_save(replacement); return
            if validation.get("outcome") != "passed":
                self._replacement_error(replacement, "CORE_REPLACEMENT_SINGLE_FAILED", "Replacement did not pass single-image validation"); return
            current = self.store.group(replacement["group_id"]).get("reference")
            if current != replacement["reference"]:
                self._replacement_error(replacement, "CORE_GROUP_STALE", "Reference changed while replacement was pending", "stale_reference"); return
            try:
                if not isinstance(replacement.get("group_validation_frozen"), dict):
                    self._replacement_error(replacement, "CORE_REPLACEMENT_SNAPSHOT_MISSING", "Replacement record lacks the frozen group validation snapshot"); return
                run, _ = self.submit(replacement["group_id"], "group-replacement-validation:" + replacement["id"], {
                    "reference_revision": replacement["reference"]["revision"], "target_ids": [image["id"]],
                    "validation": replacement["group_validation"],
                }, replacement["group_validation_frozen"])
                replacement.update(state="group_validation_pending", group_run_id=run["id"])
                self.replacement_save(replacement)
            except ApiError as exc:
                self._replacement_error(replacement, exc.code, exc.message)
            return
        if replacement["state"] == "group_validation_pending":
            run = self.get(replacement["group_run_id"])
            if run["state"] not in TERMINAL: return
            replacement.update(state="completed" if run["state"] == "completed" else run["state"], error=run.get("error"))
            self.replacement_save(replacement)

    def cancel(self, run_id):
        run = self.get(run_id)
        run["cancel_requested"] = True
        if run["state"] == "queued": run["state"] = "cancelled"
        self.save(run)
        return self.public(self.get(run_id))

    async def tick(self):
        for replacement in self.replacements():
            if replacement["state"] not in {"completed", "failed", "cancelled", "error", "stale_reference"}:
                self.advance_replacement(self.replacement_get(replacement["id"]))
        api = self.core.validation
        for run in self.runs():
            run = self.get(run["id"])
            if run["state"] in TERMINAL: continue
            try:
                if run["endpoint"] != api.url: raise ApiError("CORE_VALIDATION_ENDPOINT_CHANGED", "Saved group endpoint changed", 409)
                key = "core-group:" + run["id"]
                if run.get("cancel_requested") and run["job_id"]:
                    await api.call("POST", "/v1/validation-jobs/" + run["job_id"] + "/cancel")
                if run["state"] == "queued":
                    registry = api.settings.registry()
                    # A legacy group profile alone is not managed runtime
                    # configuration.  Keep compact legacy fixtures/endpoints live.
                    if registry["providers"]:
                        await api.sync_registry()
                    run["state"] = "dispatching"
                    self.save(run)
                    job = await api.call("POST", "/v1/validations/group", headers={"Idempotency-Key": key}, json=run["request"])
                elif run["state"] == "dispatching":
                    job = await api.call("GET", "/v1/validation-jobs/by-key", headers={"Idempotency-Key": key})
                else:
                    job = await api.call("GET", "/v1/validation-jobs/" + run["job_id"])
                if not job: raise ApiError("CORE_VALIDATION_ACCEPTANCE_UNKNOWN", "Group job unavailable; no automatic resubmission", 502)
                if job.get("request") != run["request"] or not isinstance(job.get("job_id"), str) or (run["job_id"] and job["job_id"] != run["job_id"]):
                    raise ApiError("CORE_VALIDATION_PROTOCOL_ERROR", "Group response does not match frozen request", 502)
                try:
                    if str(uuid.UUID(job["job_id"])) != job["job_id"]: raise ValueError()
                except ValueError as exc:
                    raise ApiError("CORE_VALIDATION_PROTOCOL_ERROR", "Invalid group job ID", 502) from exc
                run["job_id"] = job["job_id"]
                if job["state"] in TERMINAL:
                    if job["state"] == "completed":
                        result = job.get("result")
                        targets = {i["ref"] for i in run["request"]["targets"]}
                        if not isinstance(result, dict) or not isinstance(result.get("items"), list) or len(result["items"]) != len(targets) or any(not isinstance(i, dict) for i in result["items"]) or {i.get("image_ref") for i in result["items"]} != targets:
                            raise ApiError("CORE_VALIDATION_PROTOCOL_ERROR", "Group target results missing or duplicated", 502)
                        refs = {i["ref"] for i in [run["request"]["representative"], *run["request"]["auxiliaries"]]}
                        for item in result["items"]:
                            if item.get("status") == "error":
                                if not isinstance(item.get("error"), dict): raise ApiError("CORE_VALIDATION_PROTOCOL_ERROR", "Missing target error", 502)
                            elif normalize({"assessments": item.get("evidence")}, run["request"]["identity"], refs)["status"] != item.get("status"):
                                raise ApiError("CORE_VALIDATION_PROTOCOL_ERROR", "Group status differs from evidence", 502)
                        result = dict(result, summary=summary(result["items"]))
                        outcome = {"matched": "passed", "mismatch": "failed", "incomplete": "incomplete"}[result["summary"]["state"]]
                        run.update(state="completed", result=result, outcome=outcome, error=None)
                    else:
                        run.update(state=job["state"], outcome=job.get("outcome"), result=None, error=job.get("error"), partial_results=job.get("partial_results", []))
                elif job["state"] in {"queued", "submitting", "running"}: run["state"] = "pending"
                else: raise ApiError("CORE_VALIDATION_PROTOCOL_ERROR", "Unknown group state", 502)
                self.save(run)
            except ApiError as exc:
                if exc.code == "CORE_VALIDATION_UNAVAILABLE": continue
                run.update(state="failed", outcome="error", result=None, error={"code": exc.code, "message": exc.message})
                self.save(run)
            except (KeyError, TypeError, ValueError, AttributeError):
                run.update(state="failed", outcome="error", result=None, error={"code": "CORE_VALIDATION_PROTOCOL_ERROR", "message": "Malformed group response"})
                self.save(run)

    def status(self, group_id):
        group = self.store.group(group_id)
        reference = group.get("reference")
        images = self.images(group_id)
        eligible = [image for image in images if (image.get("validation") or {}).get("outcome") == "passed"]
        refs = {reference["representative_id"], *reference["auxiliary_ids"]} if reference else set()
        current = set(self.current_target_ids(group_id))
        targets = [i["id"] for i in eligible if i["id"] in current and i["id"] not in refs]
        latest = {}
        if reference:
            for run in self.runs(group_id):
                if run["request"]["reference_revision"] != reference["revision"]: continue
                if run["state"] != "completed":
                    for target in run["request"]["targets"]:
                        latest[target["ref"]] = {"image_ref": target["ref"], "status": "unvalidated", "run_id": run["id"]}
                    continue
                for item in run["result"]["items"]:
                    latest[item["image_ref"]] = dict(item, run_id=run["id"])
        results = [latest.get(i, {"image_ref": i, "status": "unvalidated"}) for i in targets]
        counts = {key: sum(i["status"] == key for i in results) for key in ("matched", "mismatch", "insufficient", "reference_conflict", "error", "unvalidated")}
        state = "awaiting_reference" if not reference else "insufficient_images" if not targets else "mismatch" if counts["mismatch"] else "matched" if counts["matched"] == len(targets) else "incomplete"
        return {"group_id": group_id, "reference": reference, "state": state, "counts": counts,
                "target_ids": targets, "results": results, "eligible_image_ids": [i["id"] for i in eligible],
                "excluded_image_ids": [i["id"] for i in images if i not in eligible or i["id"] not in current],
                "replacements": self.replacements(group_id)}

    def attach(self, app):
        async def status(request): return web.json_response(self.status(request.match_info["id"]))
        async def reference(request): return web.json_response(self.reference(request.match_info["id"], await request.json()))
        async def candidate(request): return web.json_response(self.reference_candidate(request.match_info["id"]))
        async def replacements(request):
            group_id = request.match_info["id"]
            if request.method == "GET":
                self.store.group(group_id)
                return web.json_response({"items": self.replacements(group_id)})
            replacement, created = self.request_replacement(group_id, request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(replacement, status=202 if created else 200)
        async def collection(request):
            group_id = request.match_info["id"]
            if request.method == "GET":
                self.store.group(group_id)
                return web.json_response({"items": [self.public(r) for r in self.runs(group_id)]})
            run, created = self.submit(group_id, request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(run, status=202 if created else 200)
        async def detail(request): return web.json_response(self.public(self.get(request.match_info["id"])))
        async def cancel(request): return web.json_response(self.cancel(request.match_info["id"]))
        app.add_routes([web.get("/v1/groups/{id}/consistency", status), web.get("/v1/groups/{id}/reference-candidate", candidate), web.put("/v1/groups/{id}/reference", reference),
                        web.get("/v1/groups/{id}/replacements", replacements), web.post("/v1/groups/{id}/replacements", replacements), web.get("/v1/groups/{id}/validations", collection),
                        web.post("/v1/groups/{id}/validations", collection), web.get("/v1/group-validation-runs/{id}", detail),
                        web.post("/v1/group-validation-runs/{id}/cancel", cancel)])
