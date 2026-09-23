"""Core-owned attempt lineage and bounded automatic regeneration cycles."""
import copy
import hashlib
import secrets

from ..common import ApiError, canonical
from ..regeneration_contract import validate_changes
from .store import representative_image


class Regeneration:
    def __init__(self, core, validate_generation):
        self.core, self.store, self.validate_generation = core, core.store, validate_generation

    def snapshot(self, source, body, manual):
        if not isinstance(body, dict) or set(body) - {"generation_inputs", "postprocess", "validation"}:
            raise ApiError("CORE_REGENERATION_INVALID", "Only generation_inputs, postprocess and validation overrides are supported")
        snapshot = copy.deepcopy(source["snapshot"])
        inputs = snapshot["generation_inputs"]
        patch = body.get("generation_inputs", {})
        if not isinstance(patch, dict) or set(patch) & {"positive_prompt", "negative_prompt", "output_name"}:
            raise ApiError("CORE_REGENERATION_INVALID", "Regeneration preserves the saved prompt intent")
        if manual and "seed" not in patch:
            inputs["seed"] = (inputs["seed"] + 1 + secrets.randbelow(2**32)) % (2**64)
        settings = {key: value for key, value in inputs.items() if key not in {"positive_prompt", "negative_prompt", "output_name"}}
        settings.update(patch)
        inputs.update(self.validate_generation(settings))
        if "postprocess" in body:
            value = body["postprocess"]
            if not isinstance(value, dict) or set(value) - {"upscale", "detailer", "censor", "alpha", "encode"} or any(not isinstance(v, dict) for v in value.values()):
                raise ApiError("CORE_REGENERATION_INVALID", "Invalid postprocess override")
            snapshot["postprocess"] = copy.deepcopy(value)
        if manual:
            current = self.store.settings()
            snapshot.setdefault("settings", {}).update({key: current[key] for key in ("auto_regeneration_enabled", "max_auto_regenerations")})
            selection = body.get("validation", (snapshot.get("validation") or {}).get("selection"))
            if selection is None:
                snapshot.pop("validation", None)
            else:
                snapshot["validation"] = self.core.validation.freeze(selection)
        return snapshot

    def manual(self, task_id, key, body, frozen_snapshot=None):
        if not key or len(key) > 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key of 1..200 characters is required")
        # Preserve the pre-frozen contract's fingerprint so an old persisted
        # manual key remains idempotent after this optional feature was added.
        material = {"regeneration_of": task_id, "body": body}
        if frozen_snapshot is not None:
            material["frozen_snapshot"] = frozen_snapshot
        fingerprint = hashlib.sha256(canonical(material).encode()).hexdigest()
        old = self.store.by_key(key)
        if old:
            if old[0] != fingerprint: raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Key already has different content", 409)
            return old[1], False
        source = self.store.task(task_id)
        if source["state"] not in {"generated", "failed", "cancelled"}:
            raise ApiError("CORE_REGENERATION_ACTIVE", "Wait for or cancel the current generation before regenerating", 409)
        for image in source["images"]:
            if any(run["state"] not in {"completed", "failed", "cancelled"} for run in self.store.image_validations(image["id"])):
                raise ApiError("CORE_REGENERATION_ACTIVE", "Wait for or cancel active validation first", 409)
        link = source.get("regeneration", {})
        old_cycle = self.store.cycle(link["cycle_id"]) if link else None
        if old_cycle and old_cycle["state"] == "active" and old_cycle["active_task_id"] != source["id"]:
            raise ApiError("CORE_REGENERATION_ACTIVE", "An automatic descendant is active; stop its cycle first", 409)
        # Group replacement orchestration persists this snapshot before creating
        # the task.  Retrying after a config change must not silently refreeze a
        # different validation profile or provider.
        snapshot = copy.deepcopy(frozen_snapshot) if frozen_snapshot is not None else self.snapshot(source, body, manual=True)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("generation_inputs"), dict):
            raise ApiError("CORE_REGENERATION_INVALID", "Frozen regeneration snapshot is invalid")
        new_link = {"kind": "manual", "parent_task_id": task_id, "lineage_id": link.get("lineage_id", task_id),
                    "supersedes_cycle": old_cycle["id"] if old_cycle and old_cycle["state"] == "active" else None}
        return self.store.create_task(key, fingerprint, source["group_id"], snapshot, new_link), True

    def stop(self, cycle_id):
        cycle = self.store.cycle(cycle_id)
        if cycle["state"] != "active": return cycle
        # Persist stopping before any cancellable service communication.
        self.store.update_cycle(cycle, state="stopped", reason="Stopped by user")
        task = self.store.task_metadata(cycle["active_task_id"], cancel_requested=True)
        if task["state"] == "queued":
            task["state"] = "cancelled"
            self.store.update_task(task)
        for image in task["images"]:
            for run in self.store.image_validations(image["id"]): self.core.validation.cancel(run["id"])
        return cycle

    def seed_only(self, cycle, task, reason):
        """ADR-0025 F: keep every saved setting and draw only a new seed."""
        saved = cycle.get("last_change") or {}
        if saved.get("kind") == "seed_only" and saved.get("parent_task_id") == task["id"]:
            return {key: saved[key] for key in ("kind", "reason", "previous_seed", "seed")}
        previous = task["snapshot"]["generation_inputs"]["seed"]
        seed = previous
        while seed == previous:
            seed = secrets.randbelow(2**53)
        return {"kind": "seed_only", "reason": reason, "previous_seed": previous, "seed": seed}

    def tick(self):
        for cycle in self.store.active_cycles():
            task = self.store.task(cycle["active_task_id"])
            if task.get("cancel_requested") or task["state"] == "cancelled":
                self.store.update_cycle(cycle, state="cancelled", reason="Attempt cancelled"); continue
            if task["state"] == "failed" or task.get("automatic_validation_error"):
                self.store.update_cycle(cycle, state="error", reason="Generation or validation submission failed"); continue
            if task["state"] != "generated": continue
            if not task["snapshot"].get("validation"):
                self.store.update_cycle(cycle, state="generation_only", reason="Validation was not requested"); continue
            runs, representative = [], representative_image(task["images"])
            for image in task["images"]:
                saved = self.store.validation_by_key("auto:" + task["id"] + ":" + image["id"])
                if saved: runs.append(saved[1])
            if representative is None or representative["id"] not in {r["image_id"] for r in runs}: continue
            if any(r["state"] not in {"completed", "failed", "cancelled"} for r in runs): continue
            if any(r["state"] == "cancelled" for r in runs):
                self.store.update_cycle(cycle, state="cancelled", reason="Validation cancelled"); continue
            if any(r["outcome"] == "error" for r in runs):
                self.store.update_cycle(cycle, state="error", reason="Validation execution error; no regeneration"); continue
            failed = [r for r in runs if r["outcome"] == "failed"]
            if not failed:
                self.store.update_cycle(cycle, state="passed", reason="All requested single-image validations passed"); continue
            if not cycle["enabled"]:
                self.store.update_cycle(cycle, state="automatic_disabled", reason="Automatic regeneration disabled"); continue
            if cycle["used"] >= cycle["limit"]:
                self.store.update_cycle(cycle, state="limit_reached", reason="Automatic attempt limit reached"); continue
            try:
                patch, missing = {}, None
                for run in failed:
                    result = run.get("result") or {}
                    proposed = (result.get("regeneration") or {}).get("changes") if isinstance(result.get("regeneration"), dict) else None
                    if not proposed:
                        missing = missing or ("proposal_dropped" if (result.get("diagnostics") or {}).get("regeneration_proposal_dropped") else "proposal_unavailable")
                        continue
                    try:
                        changes = validate_changes(proposed, result.get("evidence", []), task["snapshot"]["generation_inputs"])
                    except ApiError:
                        missing = missing or "proposal_invalid"
                        continue
                    for change in changes:
                        field, value = change["field"], change["value"]
                        if field in patch and patch[field] != value:
                            raise ApiError("CORE_REGENERATION_CONFLICT", "Output validations propose conflicting changes", 422)
                        patch[field] = value
                if missing:
                    change = self.seed_only(cycle, task, missing)
                    patch = {"seed": change["seed"]}
                else:
                    change = {"kind": "proposal", "fields": sorted(patch)}
                snapshot = self.snapshot(task, {"generation_inputs": patch}, manual=False)
                self.store.update_cycle(cycle, last_change=dict(change, parent_task_id=task["id"]))
                link = {"kind": "automatic", "parent_task_id": task["id"], "lineage_id": cycle["lineage_id"],
                        "cycle_id": cycle["id"], "source_run_ids": [run["id"] for run in failed], "change": change}
                key = "regenerate:auto:" + task["id"]
                fingerprint = hashlib.sha256(canonical({"snapshot": snapshot, "link": link}).encode()).hexdigest()
                previous = self.store.by_key(key)
                if previous:
                    if previous[0] != fingerprint:
                        raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Automatic attempt key has conflicting content", 409)
                    self.store.update_cycle(cycle, active_task_id=previous[1]["id"])
                else:
                    self.store.create_task(key, fingerprint, task["group_id"], snapshot, link)
            except ApiError as exc:
                self.store.update_cycle(cycle, state="error", reason=exc.message, error_code=exc.code)
