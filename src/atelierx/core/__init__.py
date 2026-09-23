"""Core REST service: category editing, prompt snapshots and Generation orchestration."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid

import aiohttp
from aiohttp import web
from ..runtime_info import RUNTIME_INFO

from ..common import ApiError, canonical
from ..output_names import build_output_name
from .batches import CoreBatches
from .production_plans import ProductionPlans
from .catalog import list_groups, list_images
from .task_queries import list_tasks, list_batches
from .groups import CoreGroups
from .presets import CorePresets, validate_postprocess_settings
from .fragments import CoreFragments
from .regeneration import Regeneration
from .reference_sets import ReferenceSets
from .store import KINDS, Store
from .validation import CoreValidation
from ..validation_evidence import clauses, expanded_clause
from ..gpu import GpuCoordinator
from .standalone import StandaloneJobs
from .postprocess import CorePostprocess
from ..queue_api import attach_queue_api
from .frontend import attach as attach_frontend
from .resources import attach as attach_generation_resources
from .frontend_connection import FrontendConnection
from .operations_status import OperationsStatus

CORE = web.AppKey("core", object)
FRONTEND_CONNECTION = web.AppKey("frontend_connection", FrontendConnection)
PARTS = ("upper", "lower", "accessories", "hands")
COMPONENTS = set(PARTS)
REQUIRED_COMPONENTS = {"upper", "lower", "accessories"}
LEGACY_COMPONENTS = {"appearance", "upper", "lower"}
COMPOSITION_VERSION = 4
GEN_FIELDS = {"diffusion_model", "text_encoder", "vae", "width", "height", "seed", "steps", "cfg", "sampler", "scheduler"}
TASK_FIELDS = {"group_id", "framing", "framing_prompt", "expression", "action", "situation", "include", "fragment", "common_fragments", "generation_inputs", "postprocess", "presets", "preview_hash", "validation", "consistency", "accept_reference_settings_mismatch"}

# ADR-0027 P3: consistency method registry. Generation's ``/v1/resources`` is the
# eventual canonical source (``consistency_methods``); this static mirror of the
# accepted defaults/ranges lets synchronous prompt composition validate params
# without a network round trip, and is used until that resource is cached here.
DEFAULT_CONSISTENCY_METHOD = "anima-incontext-character"
CONSISTENCY_METHODS = {
    "anima-incontext-character": {
        "families": ["anima"],
        "params": {
            "strength": {"type": "number", "default": 1.0, "min": 0.5, "max": 1.5},
            "end_percent": {"type": "number", "default": 0.5, "min": 0.3, "max": 1.0, "warn_below": 0.5},
            "suppress_reference_background": {"type": "boolean", "default": True},
        },
    },
}
REFERENCE_SETTINGS_FIELDS = ("diffusion_model", "text_encoder", "common_fragments", "positive_quality", "loras")


def consistency_params(method_id, requested):
    definition = CONSISTENCY_METHODS.get(method_id)
    if definition is None:
        invalid(f"Unknown consistency method: {method_id}")
    if requested is None:
        requested = {}
    if not isinstance(requested, dict) or set(requested) - set(definition["params"]):
        invalid("Unknown consistency params")
    result, warnings = {}, []
    for name, spec in definition["params"].items():
        value = requested.get(name, spec["default"])
        if spec["type"] == "number":
            if type(value) not in (int, float) or not math.isfinite(value) or not spec["min"] <= value <= spec["max"]:
                invalid(f"consistency params.{name} must be a number in {spec['min']}..{spec['max']}")
            if "warn_below" in spec and value < spec["warn_below"]:
                warnings.append(name)
        elif spec["type"] == "boolean":
            if type(value) is not bool:
                invalid(f"consistency params.{name} must be boolean")
        result[name] = value
    return result, warnings


def invalid(message):
    raise ApiError("CORE_INVALID_INPUT", message)


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        invalid("Missing or unknown fields")


def text(value, label, nonempty=False):
    if not isinstance(value, str) or len(value) > 20000 or (nonempty and not value.strip()):
        invalid(f"{label} must be text" + (" and not empty" if nonempty else ""))
    return value


def components(value):
    # Existing snapshots remain readable; only new entity writes use the
    # character-owned appearance schema.
    if isinstance(value, dict) and set(value) == LEGACY_COMPONENTS:
        return {name: text(value[name], name) for name in sorted(LEGACY_COMPONENTS)}
    fields(value, COMPONENTS, REQUIRED_COMPONENTS)
    return {name: text(value.get(name, ""), name) for name in sorted(COMPONENTS)}


def check_features(value):
    if not isinstance(value, list) or len(value) > 50:
        invalid("check_features must be an array of at most 50 items")
    result = []
    for item in value:
        if not isinstance(item, str):
            invalid("check_features items must be text")
        item = item.strip()
        if len(item) > 200:
            invalid("check_features items must be at most 200 characters")
        if item:
            result.append(item)
    return result


def output_path(item):
    value = item.get("output_path")
    return value if isinstance(value, str) and 0 < len(value) <= 1024 else None


def revision(value):
    if type(value) is not int or value < 1:
        invalid("revision must be a positive integer")
    return value


def character_negative(value):
    text(value, "negative_prompt")
    abstract = {"low quality", "worst quality", "bad quality", "masterpiece", "고품질", "저품질"}
    if any(entry["requirement"].strip().casefold() in abstract for part in clauses(value) for entry in expanded_clause(part)):
        raise ApiError("CORE_CHARACTER_NEGATIVE_INVALID", "Put abstract quality terms in global negative; character negative requires visible forbidden elements")
    return value


def paging(request):
    try:
        limit, offset = int(request.query.get("limit", 50)), int(request.query.get("offset", 0))
    except ValueError:
        invalid("limit and offset must be integers")
    if not 1 <= limit <= 200 or offset < 0:
        invalid("limit must be 1..200 and offset nonnegative")
    return limit, offset


def generation_settings(value):
    fields(value, GEN_FIELDS | {"loras"}, GEN_FIELDS - {"width", "height"})
    value = {"width": 1024, "height": 1024, **value}
    for name in ("diffusion_model", "text_encoder", "vae", "sampler", "scheduler"):
        text(value[name], name, True)
    ranges = {"width": (256, 1920), "height": (256, 1920), "seed": (-1, 2**64-1), "steps": (1, 100)}
    for name, (low, high) in ranges.items():
        if type(value[name]) is not int or not low <= value[name] <= high:
            invalid(f"{name} must be an integer in {low}..{high}")
    if value["width"] % 16 or value["height"] % 16:
        invalid("Dimensions must be multiples of 16")
    cfg = value["cfg"]
    if type(cfg) not in (int, float) or not math.isfinite(cfg) or not 0 <= cfg <= 20:
        invalid("cfg must be finite and within 0..20")
    loras = value.get("loras", [])
    if not isinstance(loras, list):
        invalid("loras must be an array")
    for item in loras:
        fields(item, {"name", "strength"}, {"name", "strength"})
        text(item["name"], "LoRA name", True)
        strength = item["strength"]
        if type(strength) not in (int, float) or not math.isfinite(strength) or not -100 <= strength <= 100:
            invalid("LoRA strength must be finite and within -100..100")
    return dict(value, loras=loras)


def reference_templates(value):
    fields(value, {"full", "face"}, {"full", "face"})
    result = {}
    for role in ("full", "face"):
        entry = value[role]
        fields(entry, {"framing_prompt", "include"}, {"framing_prompt", "include"})
        text(entry["framing_prompt"], "framing_prompt", True)
        fields(entry["include"], COMPONENTS, COMPONENTS)
        if any(type(v) is not bool for v in entry["include"].values()):
            invalid("reference_templates include values must be boolean")
        result[role] = {"framing_prompt": entry["framing_prompt"], "include": dict(entry["include"])}
    return result


class Core:
    def __init__(self, db_path, generation_url, token, generation_token, poll):
        self.store = Store(db_path)
        self.presets = CorePresets(self.store.db, generation_settings)
        self.fragments = CoreFragments(self.store.db)
        self.generation_url = generation_url.rstrip("/")
        self.token, self.generation_token, self.poll = token, generation_token, poll

    def preview(self, payload):
        fields(payload, TASK_FIELDS, {"group_id"})
        selected_presets = self.preset_settings(payload)
        group_id = text(payload["group_id"], "group_id", True)
        group = self.store.group(group_id)
        self.store.active_chain(group["outfit_id"], "outfits")
        fragment = self.fragments.snapshot(payload["fragment"]) if "fragment" in payload else None
        common_selections = payload.get("common_fragments", [])
        if not isinstance(common_selections, list): invalid("common_fragments must be an array")
        common_fragments = [self.fragments.snapshot(selection) for selection in common_selections]
        references = [item["id"] for item in common_fragments]
        if len(references) != len(set(references)):
            invalid("common_fragments cannot contain duplicates")
        if any(not item.get("common", False) for item in common_fragments):
            invalid("common_fragments must reference common prompt fragments")
        if fragment and fragment.get("common", False):
            invalid("fragment must reference an image-variant prompt fragment")
        if fragment and any(field in payload for field in ("framing", "framing_prompt", "expression", "action", "situation", "include")):
            invalid("fragment cannot be combined with framing, prompt inputs, or include")
        framing = None if fragment else payload.get("framing")
        if fragment:
            framing_prompt, include = "", {"upper": True, "lower": True, "accessories": True, "hands": True, **fragment["include"]}
        else:
            if not isinstance(framing, str) or framing not in {"upper_body", "full_body", "custom"}:
                invalid("framing supports upper_body, full_body or custom")
            framing_prompt = "upper body" if framing == "upper_body" else "full body"
            if framing == "custom": framing_prompt = text(payload.get("framing_prompt"), "framing_prompt", True)
            elif "framing_prompt" in payload: invalid("framing_prompt requires custom framing")
            include = payload.get("include", {})
            if isinstance(include, dict) and set(include) == LEGACY_COMPONENTS:
                include = {"upper": include["upper"], "lower": include["lower"], "accessories": True}
            fields(include, COMPONENTS)
            if any(type(value) is not bool for value in include.values()): invalid("include values must be boolean")
            if framing == "custom" and not REQUIRED_COMPONENTS <= set(include): invalid("Custom framing requires explicit upper, lower and accessories inclusion")
        framing_context = ", ".join([fragment["body"] if fragment else framing_prompt, *(item["body"] for item in common_fragments)])
        framing_terms = {entry["requirement"].strip().casefold()
                         for part in clauses(framing_context) for entry in expanded_clause(part)}
        if {"upper body", "full body"}.issubset(framing_terms):
            raise ApiError("CORE_PROMPT_CONFLICT", "Choose one body crop; upper body and full body conflict")
        upper_body = framing == "upper_body" or ((framing == "custom" or fragment is not None) and "upper body" in framing_terms)
        if upper_body and include.get("lower") is True:
            raise ApiError("CORE_PROMPT_CONFLICT", "upper_body cannot require lower/footwear")
        settings = self.store.settings()
        source = group["components"]
        appearance = group.get("character_appearance_prompt", source.get("appearance", ""))
        character = self.store.entity(group["character_id"], "characters")
        features = character.get("check_features") or []
        chunks = [settings["positive_quality"]]
        decisions = {"appearance": {"included": True, "reason": "character"}}
        chunks.append(appearance)
        checks = ([{"text": feature, "source": "character_features"} for feature in features] if features else
                  [{"text": appearance, "source": "character_appearance"}] if appearance.strip() else [])
        for name in PARTS:
            active = include.get(name, True) and not (name == "lower" and framing == "upper_body")
            decisions[name] = {"included": active, "reason": "fragment" if fragment and active else "included" if active else
                               ("framing" if name == "lower" and framing == "upper_body" else "user_excluded")}
            if active:
                chunks.append(source.get(name, ""))
                if source.get(name, "").strip():
                    checks.append({"text": source[name], "source": "outfit_" + name})
        for common in common_fragments:
            chunks.append(common["body"])
        chunks.append(framing_prompt)
        prompt_texts = [framing_prompt] + [text(payload.get(name, ""), name) for name in ("expression", "action", "situation")]
        chunks.extend(prompt_texts[1:])
        if fragment: chunks.append(fragment["body"])
        checks.extend({"text": value, "source": "fragment"} for value in ([fragment["body"]] if fragment else prompt_texts) if value.strip())
        positive = ", ".join(chunk for chunk in chunks if chunk.strip())
        gen = selected_presets.get("generation", {}).get("settings")
        if gen is None:
            if "generation_inputs" not in payload:
                invalid("generation_inputs is required when no generation preset is selected")
            gen = generation_settings(payload["generation_inputs"])
        postprocess = selected_presets.get("postprocess", {}).get("settings")
        if postprocess is None:
            postprocess = payload.get("postprocess", {"upscale": {"upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5}, "encode": {"webp_enabled": True, "webp_quality": 90}})
        if not isinstance(postprocess, dict) or set(postprocess) - {"upscale", "detailer", "censor", "alpha", "encode"}:
            invalid("postprocess must contain supported stage settings")
        if any(not isinstance(value, dict) for value in postprocess.values()):
            invalid("Each postprocess stage must be an object")
        if "upscale" in postprocess:
            validate_postprocess_settings({"upscale": postprocess["upscale"]})
        consistency = self.resolve_consistency(payload, group)
        negative_sources = {"global": settings["negative"], "character": character.get("negative_prompt", "")}
        # Fragment Negatives are generation-only: selected common fragments in
        # order, then the image-variant fragment. The key is omitted when empty so
        # snapshots and preview hashes without fragment Negatives stay unchanged.
        fragment_negative = ", ".join(part for part in (*(item.get("negative", "") for item in common_fragments), (fragment or {}).get("negative", "")) if part.strip())
        if fragment_negative:
            negative_sources["fragment"] = fragment_negative
        if consistency and consistency[0]["params"].get("suppress_reference_background"):
            # ADR-0027 P4: appended last, generation-only, excluded from VLM checks (like global).
            negative_sources["consistency"] = "white background, simple background"
        negative = ", ".join(part for part in negative_sources.values() if part.strip())
        positive_terms = {entry["requirement"].strip().casefold() for part in clauses(positive) for entry in expanded_clause(part)}
        forbidden_terms = {entry["requirement"].strip().casefold() for part in clauses(negative_sources["character"]) for entry in expanded_clause(part)}
        if positive_terms & forbidden_terms:
            raise ApiError("CORE_PROMPT_CONFLICT", "A character forbidden element also occurs in the positive prompt")
        if consistency:
            gen["consistency"] = consistency[1]
        gen.update(positive_prompt=positive, negative_prompt=negative)
        prefix = self.output_prefix(group)
        if fragment and fragment.get("number"):
            gen["output_name"] = build_output_name(*prefix, fragment["number"])
        snapshot = dict(composition_version=COMPOSITION_VERSION, negative_sources=negative_sources, character_revision=character["revision"], group=group, settings=settings,
                        generation_inputs=gen, inclusion=decisions, generation_endpoint=self.generation_url, positive_check=checks, output_name_prefix=prefix)
        if framing == "custom":
            snapshot["prompt_inputs"] = {name: payload.get(name, "") for name in ("framing_prompt", "expression", "action", "situation")}
        if selected_presets:
            snapshot["preset_sources"] = {kind: selected_presets[kind]["preset"] for kind in sorted(selected_presets)}
        if fragment: snapshot["fragment"] = fragment
        if common_fragments: snapshot["common_fragments"] = common_fragments
        if postprocess:
            snapshot["postprocess"] = postprocess
        if consistency:
            snapshot["consistency"] = consistency[0]
        if payload.get("validation") is not None:
            selection = payload["validation"]
            fields(selection, {"provider_id", "profile_id"}, {"provider_id", "profile_id"})
            snapshot["validation"] = self.validation.freeze(selection)
        digest = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
        return {"snapshot": snapshot, "preview_hash": digest}

    def output_prefix(self, group):
        return ["AtelierX", *(self.store.entity(group[key], kind)["name"] for key, kind in (("work_id", "works"), ("character_id", "characters"), ("outfit_id", "outfits")))]

    def resolve_consistency(self, payload, group):
        """Build the (snapshot, generation_inputs) consistency pair, or None (ADR-0027 P3)."""
        if "consistency" in payload and payload["consistency"] is None:
            return None
        reference_sets = getattr(self, "reference_sets", None)
        if reference_sets is None:
            return None
        status = reference_sets.status(group["outfit_id"])
        if status["status"] != "valid":
            return None
        reference_set = status["set"]
        requested = payload.get("consistency")
        if requested is not None:
            fields(requested, {"method", "params"}, {"method"})
        method_id = (requested or {}).get("method", DEFAULT_CONSISTENCY_METHOD)
        params, _warnings = consistency_params(method_id, (requested or {}).get("params"))
        references = [{"role": "full", **reference_set["full"]}, {"role": "face", **reference_set["face"]}]
        snapshot_block = {"method": method_id, "params": params,
                          "reference_set": {"id": reference_set["id"], "revision": reference_set["revision"]},
                          "references": references}
        generation_block = {"method": method_id, "params": params,
                            "references": [{"role": item["role"], "image_id": item["generation_image_id"], "sha256": item["sha256"]} for item in references]}
        return snapshot_block, generation_block

    def require_reference_set(self, group):
        """ADR-0027 P5: block production plan/Task creation without a valid reference set."""
        status = self.reference_sets.status(group["outfit_id"])
        if status["status"] != "valid":
            raise ApiError("CORE_REFERENCE_SET_REQUIRED",
                            "Confirm a valid reference set for this outfit before creating a production plan or task",
                            409, details={"outfits": [{"outfit_id": group["outfit_id"], "status": status["status"]}]})
        return status["set"]

    def check_reference_settings(self, snapshot, reference_set, accepted):
        """ADR-0027 P1/#7: warn (or block) when a plan's settings differ from the confirmed reference set."""
        gen = snapshot["generation_inputs"]
        expected = reference_set["settings_summary"]
        actual = {"diffusion_model": gen.get("diffusion_model"), "text_encoder": gen.get("text_encoder"),
                  "common_fragments": [{"id": item["id"], "revision": item["revision"]} for item in snapshot.get("common_fragments", [])],
                  "positive_quality": snapshot.get("settings", {}).get("positive_quality", ""), "loras": gen.get("loras", [])}
        diff = {key: {"reference": expected.get(key), "plan": actual.get(key)} for key in REFERENCE_SETTINGS_FIELDS if expected.get(key) != actual.get(key)}
        if diff and not accepted:
            raise ApiError("CORE_REFERENCE_SETTINGS_MISMATCH", "Generation settings differ from the confirmed reference set", 409, details={"diff": diff})
        return diff

    def preset_settings(self, payload):
        """Resolve explicitly versioned presets before composing an immutable Task snapshot."""
        selected = payload.get("presets")
        if selected is None:
            return {}
        if not isinstance(selected, dict) or set(selected) - {"generation", "postprocess"}:
            invalid("presets may select generation and/or postprocess")
        result = {}
        for kind, direct_field in (("generation", "generation_inputs"), ("postprocess", "postprocess")):
            choice = selected.get(kind)
            if choice is None:
                continue
            if direct_field in payload:
                invalid(f"{kind} preset cannot be combined with direct {direct_field}")
            fields(choice, {"id", "revision"}, {"id", "revision"})
            result[kind] = self.presets.snapshot(kind, text(choice["id"], f"{kind} preset id", True), revision(choice["revision"]))
        return result

    def submit(self, key, payload):
        if not key or len(key) > 200:
            invalid("Idempotency-Key of 1..200 characters is required")
        fields(payload, TASK_FIELDS, {"group_id"})
        fingerprint = hashlib.sha256(canonical(payload).encode()).hexdigest()
        old = self.store.by_key(key)
        if old:
            if old[0] != fingerprint:
                raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Request key already has different content", 409)
            return old[1], False
        reference_set = None
        if getattr(self, "reference_sets", None) is not None:
            # ADR-0027 P5: new individual Tasks require a valid reference set for their outfit.
            reference_set = self.require_reference_set(self.store.group(payload["group_id"]))
            # A valid reference set always uses a consistency method here; only
            # reference-sample generation and pre-ADR-0027 regeneration run without one.
            if "consistency" in payload and payload["consistency"] is None:
                invalid("consistency cannot be disabled once a valid reference set is required")
        preview = self.preview(payload)
        if "preview_hash" in payload and payload["preview_hash"] != preview["preview_hash"]:
            raise ApiError("CORE_PREVIEW_STALE", "Prompt or settings changed; review the updated preview", 409)
        if reference_set is not None:
            diff = self.check_reference_settings(preview["snapshot"], reference_set, bool(payload.get("accept_reference_settings_mismatch")))
            if diff:
                preview["snapshot"]["reference_settings_mismatch_accepted"] = {"accepted": True, "diff": diff}
        try:
            return self.store.create_task(key, fingerprint, payload["group_id"], preview["snapshot"]), True
        except sqlite3.IntegrityError:
            old = self.store.by_key(key)
            if old and old[0] == fingerprint:
                return old[1], False
            raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Concurrent request key conflict", 409)

    async def generation(self, method, path, **kwargs):
        headers = {"Authorization": "Bearer " + self.generation_token}
        headers.update(kwargs.pop("headers", {}))
        try:
            async with self.session.request(method, self.generation_url + path, headers=headers,
                                            allow_redirects=False, **kwargs) as response:
                if response.status in (502, 503, 504):
                    raise ApiError("CORE_GENERATION_UNAVAILABLE", "Generation temporarily unavailable", 503)
                if response.status == 404:
                    return None
                if response.status not in (200, 202):
                    raise ApiError("CORE_GENERATION_REJECTED", f"Generation returned HTTP {response.status}", 502)
                value = await response.json()
                if not isinstance(value, dict):
                    raise ValueError("Expected object")
                return value
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise ApiError("CORE_GENERATION_UNAVAILABLE", "Generation response unavailable", 503) from exc

    def verify_job(self, task, job):
        try:
            job_id = str(uuid.UUID(job["job_id"]))
            if job_id != job["job_id"] or job.get("inputs") != task["snapshot"]["generation_inputs"]:
                raise ValueError("Job/input mismatch")
            if task["generation_job_id"] and task["generation_job_id"] != job_id:
                raise ValueError("Job ID changed")
            if job.get("requested_postprocess", {}) != task["snapshot"].get("postprocess", {}):
                raise ValueError("Postprocess settings changed")
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Generation Job does not match the saved request", 502)
        task["generation_job_id"] = job_id

    async def advance(self, task):
        task = self.store.task(task["id"])
        if task["state"] in {"generated", "failed", "cancelled"}: return
        if task["snapshot"]["generation_endpoint"] != self.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Saved task targets a different Generation endpoint", 409)
        request_key = "core:" + task["id"]
        if task.get("cancel_requested") and task.get("generation_job_id"):
            await self.generation("POST", "/v1/jobs/" + task["generation_job_id"] + "/cancel")
        if task["state"] == "queued":
            # Persist before POST, so a crash cannot blindly send the work twice.
            task["state"] = "dispatching"
            self.store.update_task(task)
            job = await self.generation("POST", "/v1/nodes/anima/jobs",
                                        headers={"Idempotency-Key": request_key},
                                        json={"inputs": task["snapshot"]["generation_inputs"],
                                              **({"postprocess": task["snapshot"]["postprocess"]} if task["snapshot"].get("postprocess") else {})})
        elif task["state"] == "dispatching":
            job = await self.generation("GET", "/v1/jobs/by-key", headers={"Idempotency-Key": request_key})
            if job is None:
                raise ApiError("CORE_GENERATION_ACCEPTANCE_UNKNOWN", "No job found for persisted key; no automatic resubmission", 502)
        else:
            job = await self.generation("GET", "/v1/jobs/" + task["generation_job_id"])
        if job is None:
            raise ApiError("CORE_GENERATION_JOB_MISSING", "Previously accepted Generation Job is missing", 502)
        self.verify_job(task, job)
        state = job.get("state")
        if job.get("execution_started") or state in {"running", "completed"}:
            self.store.update_task(task)
            self.store.charge_automatic_start(task["id"])
            task = self.store.task(task["id"])
        if state == "completed":
            images = []
            if not isinstance(job.get("images"), list) or not job["images"]:
                raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Completed Job has no images", 502)
            seen = set()
            for item in job["images"]:
                if (not isinstance(item, dict) or not isinstance(item.get("image_id"), str)
                        or not re.fullmatch(re.escape(job["job_id"]) + r"-\d+", item["image_id"])
                        or item["image_id"] in seen or not isinstance(item.get("sha256"), str)
                        or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                        or type(item.get("bytes")) is not int or item["bytes"] <= 0
                        or item.get("media_type") not in {"image/png", "image/webp"}):
                    raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Invalid image descriptor", 502)
                seen.add(item["image_id"])
                images.append(dict(id=str(uuid.uuid4()), task_id=task["id"], group_id=task["group_id"],
                                   generation_image_id=item["image_id"], generation_job_id=job["job_id"],
                                   sha256=item["sha256"], bytes=item["bytes"], media_type=item["media_type"],
                                   output_path=output_path(item), validation_state="not_requested"))
            self.store.finish_generation(task, images)
        elif state == "cancelled":
            task.update(state="cancelled", error=None)
            self.store.update_task(task)
        elif state == "failed":
            task.update(state="failed", error={"code": "CORE_GENERATION_FAILED", "message": "Generation did not complete", "generation_error": job.get("error")})
            self.store.update_task(task)
        elif state in {"queued", "submitting", "submitted", "running"}:
            task["state"] = "generating" if state == "running" else "generation_pending"
            self.store.update_task(task)
        else:
            raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Unknown Generation state", 502)

    async def worker(self):
        while True:
            for task in self.store.pending():
                try:
                    await self.advance(task)
                except ApiError as exc:
                    if exc.code == "CORE_GENERATION_UNAVAILABLE":
                        continue
                    task.update(state="failed", error={"code": exc.code, "message": exc.message})
                    self.store.update_task(task)
                except Exception:
                    logging.exception("Core task %s failed", task["id"])
                    task.update(state="failed", error={"code": "CORE_INTERNAL_ERROR", "message": "Internal task processing failure"})
                    self.store.update_task(task)
            await self.validation.tick()
            self.regeneration.tick()
            await self.groups.tick()
            await self.batches.tick()
            await self.plans.tick()
            await asyncio.sleep(self.poll)


@web.middleware
async def errors(request, handler):
    if request.method in {"GET", "HEAD"} and (request.path in {"/", "/ui"} or request.path.startswith("/ui/")):
        return await handler(request)
    core = request.app[CORE]
    try:
        authorization = request.headers.get("Authorization")
        if authorization is not None:
            if not hmac.compare_digest(authorization.encode(), ("Bearer " + core.token).encode()):
                raise ApiError("CORE_UNAUTHORIZED", "Bearer token required", 401)
        else:
            connection = request.app[FRONTEND_CONNECTION]
            if connection.config is None:
                raise ApiError("CORE_UNAUTHORIZED", "Bearer token required", 401)
            await connection.verify_access(request, core.session)
            if request.path != "/v1/frontend-connection" and not connection.matches_core_token():
                raise ApiError("CORE_FRONTEND_TOKEN_INVALID", "Stored frontend token does not match the current Core token", 401)
        return await handler(request)
    except ApiError as exc:
        error = {"code": exc.code, "message": exc.message}
        if exc.details:
            error.update(exc.details)
        return web.json_response({"error": error}, status=exc.status)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return web.json_response({"error": {"code": "CORE_INVALID_INPUT", "message": "Invalid JSON or value"}}, status=400)
    except sqlite3.OperationalError:
        logging.exception("Core database operation failed")
        return web.json_response({"error": {"code": "CORE_STORAGE_UNAVAILABLE", "message": "Core storage unavailable"}}, status=503)


def create_app(db_path, generation_url, token, generation_token=None, poll=1, validation_config=None, validation_token=None, gpu_config=None, standalone_config=None, frontend_connection_path=None, operations_status=None):
    if not token:
        raise ValueError("ATELIERX_SERVICE_TOKEN must be set")
    app = web.Application(middlewares=[errors], client_max_size=2 * 1024 * 1024)
    attach_frontend(app)
    core = Core(db_path, generation_url, token, generation_token or token, poll)
    attach_generation_resources(app, core)
    app[FRONTEND_CONNECTION] = FrontendConnection(frontend_connection_path, token)
    operations = OperationsStatus(operations_status)
    core.presets.attach(app)
    core.fragments.attach(app)
    core.validation = CoreValidation(core, validation_config, validation_token)
    core.validation.attach(app)
    core.groups = CoreGroups(core)
    core.groups.attach(app)
    core.regeneration = Regeneration(core, generation_settings)
    core.batches = CoreBatches(core)
    core.batches.attach(app)
    core.plans = ProductionPlans(core)
    core.plans.attach(app)
    core.reference_sets = ReferenceSets(core)
    core.reference_sets.attach(app)
    core.gpu = GpuCoordinator(core.store, gpu_config)
    core.standalone = StandaloneJobs(core, standalone_config, generation_settings, validate_postprocess_settings)
    core.postprocess = CorePostprocess(core)
    attach_queue_api(app, lambda: [dict(json.loads(row[0]), kind=kind) for table, kind in (("tasks", "generation"), ("validation_runs", "validation"), ("standalone_jobs", "standalone"), ("postprocess_jobs", "postprocess")) for row in core.store.db.execute("SELECT document FROM " + table)] + [dict(run, kind="group_validation") for run in core.groups.runs()])
    app[CORE] = core

    async def lifecycle(app):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                core.session = session
                worker = asyncio.create_task(core.worker())
                async def standalone_worker():
                    while True:
                        await core.standalone.tick()
                        await asyncio.sleep(core.poll)
                async def postprocess_worker():
                    while True:
                        await core.postprocess.tick()
                        await asyncio.sleep(core.poll)
                standalone_worker_task = asyncio.create_task(standalone_worker())
                postprocess_worker_task = asyncio.create_task(postprocess_worker())
                yield
                worker.cancel(); standalone_worker_task.cancel(); postprocess_worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
                with contextlib.suppress(asyncio.CancelledError):
                    await standalone_worker_task
                with contextlib.suppress(asyncio.CancelledError):
                    await postprocess_worker_task
        finally:
            core.store.close()
    app.cleanup_ctx.append(lifecycle)

    async def health(request):
        return web.json_response({**RUNTIME_INFO, "service": "core", "status": "ok", "database_version": 2,
                                  "validation_configured": bool(core.validation.url)})

    async def frontend_connection(request):
        connection = request.app[FRONTEND_CONNECTION]
        if request.method == "PUT":
            body = await request.json()
            fields(body, {"token"}, {"token"})
            connection.save_token(body["token"])
        return web.json_response(connection.status("cloudflare_access" if request.headers.get("Authorization") is None else "bearer"), headers={"Cache-Control": "no-store"})

    async def operations_status_view(request):
        return web.json_response(await operations.fetch(core.session), headers={"Cache-Control": "no-store"})

    async def gpu(request):
        if request.method == "GET":
            return web.json_response(core.gpu.state())
        body = await request.json()
        fields(body, {"phase", "job_id"}, {"phase", "job_id"})
        if body["phase"] not in {"generation", "validation", "planner"}:
            invalid("Unknown GPU phase")
        text(body["job_id"], "job_id", True)
        result = await core.gpu.acquire(core.session, **body) if request.path.endswith("acquire") else await core.gpu.release(**body)
        return web.json_response(result)

    async def cancel_task(request):
        task = core.store.task(request.match_info["id"])
        if task["state"] not in {"failed", "cancelled"}:
            task = core.store.task_metadata(task["id"], cancel_requested=True)
            if task["state"] == "queued":
                task["state"] = "cancelled"
                core.store.update_task(task)
            for image in task["images"]:
                for run in core.store.image_validations(image["id"]):
                    core.validation.cancel(run["id"])
        pending = any(run["state"] not in {"completed", "failed", "cancelled"} for image in task["images"] for run in core.store.image_validations(image["id"]))
        finished = task["state"] in {"failed", "cancelled"} or (task["state"] == "generated" and not pending)
        return web.json_response(core.store.task(task["id"]), status=200 if finished else 202)

    async def cancel_validation(request):
        run = core.validation.cancel(request.match_info["id"])
        return web.json_response(run, status=200 if run["state"] in {"completed", "failed", "cancelled"} else 202)

    async def entity_collection(request):
        kind = request.match_info["kind"]
        if request.method == "GET":
            limit, offset = paging(request)
            return web.json_response({"items": core.store.list_entities(kind, request.query.get("parent_id"), limit, offset),
                                      "limit": limit, "offset": offset})
        body = await request.json()
        required = {"name"} | ({"parent_id"} if KINDS[kind] else set()) | ({"components"} if kind == "outfits" else set())
        fields(body, required | ({"negative_prompt", "appearance_prompt", "check_features"} if kind == "characters" else set()), required)
        result = core.store.create_entity(kind, text(body["name"], "name", True),
                                          text(body["parent_id"], "parent_id", True) if KINDS[kind] else None,
                                          components(body["components"]) if kind == "outfits" else None,
                                          character_negative(body.get("negative_prompt", "")) if kind == "characters" else "",
                                          text(body.get("appearance_prompt", ""), "appearance_prompt") if kind == "characters" else "",
                                          check_features(body.get("check_features", [])) if kind == "characters" else None)
        return web.json_response(result, status=201)

    async def entity_detail(request):
        kind, entity_id = request.match_info["kind"], request.match_info["id"]
        if request.method == "GET":
            return web.json_response(core.store.entity_response(entity_id, kind))
        body = await request.json()
        allowed = {"revision", "name", "archived"} | ({"components"} if kind == "outfits" else set()) | ({"negative_prompt", "appearance_prompt", "check_features"} if kind == "characters" else set())
        fields(body, allowed, {"revision"})
        changes = {key: value for key, value in body.items() if key != "revision"}
        if not changes:
            invalid("At least one change is required")
        if "name" in changes:
            text(changes["name"], "name", True)
        if "archived" in changes and type(changes["archived"]) is not bool:
            invalid("archived must be boolean")
        if "components" in changes:
            changes["components"] = components(changes["components"])
        if "check_features" in changes:
            changes["check_features"] = check_features(changes["check_features"])
        if "negative_prompt" in changes:
            character_negative(changes["negative_prompt"])
        if "appearance_prompt" in changes:
            text(changes["appearance_prompt"], "appearance_prompt")
        result = core.store.update_entity(entity_id, kind, revision(body["revision"]), changes)
        return web.json_response(core.store.entity_response(result["id"], kind))

    async def history(request):
        limit, offset = paging(request)
        return web.json_response({"items": core.store.history(request.match_info["id"], request.match_info["kind"], limit, offset),
                                  "limit": limit, "offset": offset})

    async def settings(request):
        if request.method == "GET":
            return web.json_response(core.store.settings())
        body = await request.json()
        fields(body, {"revision", "positive_quality", "negative", "auto_regeneration_enabled", "max_auto_regenerations", "reference_templates"}, {"revision"})
        changes = {key: value for key, value in body.items() if key != "revision"}
        for name in ("positive_quality", "negative"):
            if name in changes:
                text(changes[name], name)
        if "auto_regeneration_enabled" in changes and type(changes["auto_regeneration_enabled"]) is not bool:
            invalid("auto_regeneration_enabled must be boolean")
        if "max_auto_regenerations" in changes and (type(changes["max_auto_regenerations"]) is not int or changes["max_auto_regenerations"] < 0):
            invalid("max_auto_regenerations must be a nonnegative integer")
        if "reference_templates" in changes:
            changes["reference_templates"] = reference_templates(changes["reference_templates"])
        return web.json_response(core.store.update_settings(revision(body["revision"]), changes))

    async def groups(request):
        if request.method == "GET":
            return web.json_response(list_groups(core, request.query))
        body = await request.json()
        fields(body, {"outfit_id"}, {"outfit_id"})
        return web.json_response(core.store.create_group(text(body["outfit_id"], "outfit_id", True)), status=201)

    async def group(request):
        return web.json_response(core.store.group(request.match_info["id"]))

    async def preview(request):
        return web.json_response(core.preview(await request.json()))

    async def tasks(request):
        if request.method == "GET":
            return web.json_response(list_tasks(core, request.query))
        result, created = core.submit(request.headers.get("Idempotency-Key"), await request.json())
        return web.json_response(result, status=202 if created else 200,
                                 headers={"Location": f'/v1/tasks/{result["id"]}'})

    async def task(request):
        return web.json_response(core.store.task(request.match_info["id"]))

    async def gallery(request):
        return web.json_response(list_images(core, request.query))

    async def batch_list(request):
        return web.json_response(list_batches(core, request.query))

    async def regenerate(request):
        result, created = core.regeneration.manual(request.match_info["id"], request.headers.get("Idempotency-Key"), await request.json())
        return web.json_response(result, status=202 if created else 200)

    async def attempts(request):
        source = core.store.task(request.match_info["id"])
        lineage = source.get("regeneration", {}).get("lineage_id", source["id"])
        limit, offset = paging(request)
        items = [core.store.task(row[0]) for row in core.store.db.execute("SELECT id FROM tasks ORDER BY created_at,id")]
        items = [item for item in items if item.get("regeneration", {}).get("lineage_id", item["id"]) == lineage]
        return web.json_response({"items": items[offset:offset + limit], "limit": limit, "offset": offset, "total": len(items)})

    async def cycle(request):
        result = core.regeneration.stop(request.match_info["id"]) if request.method == "POST" else core.store.cycle(request.match_info["id"])
        return web.json_response(result)

    async def by_key(request):
        found = core.store.by_key(request.headers.get("Idempotency-Key"))
        if not found:
            raise ApiError("CORE_NOT_FOUND", "Task key not found", 404)
        return web.json_response(found[1])

    async def image(request):
        return web.json_response({"output_path": None, **core.store.image(request.match_info["id"])})

    async def image_content(request):
        image = core.store.image(request.match_info["id"])
        task = core.store.task(image["task_id"])
        if task["snapshot"]["generation_endpoint"] != core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Image belongs to another Generation endpoint", 409)
        try:
            async with core.session.get(core.generation_url + "/v1/images/" + image["generation_image_id"],
                                        headers={"Authorization": "Bearer " + core.generation_token}, allow_redirects=False) as response:
                if response.status != 200:
                    raise ApiError("CORE_IMAGE_UNAVAILABLE", "Generation image unavailable", 502)
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > min(image["bytes"], 128 * 1024 * 1024):
                        raise ApiError("CORE_IMAGE_INTEGRITY", "Image exceeds recorded size", 502)
                if len(data) != image["bytes"] or hashlib.sha256(data).hexdigest() != image["sha256"]:
                    raise ApiError("CORE_IMAGE_INTEGRITY", "Image content changed", 502)
                return web.Response(body=bytes(data), content_type=image["media_type"])
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ApiError("CORE_IMAGE_UNAVAILABLE", "Generation image unavailable", 503)

    async def validations(request):
        image_id = request.match_info["id"]
        if request.method == "GET":
            return web.json_response({"items": core.store.image_validations(image_id)})
        run, created = core.validation.submit(image_id, request.headers.get("Idempotency-Key"), await request.json())
        return web.json_response(run, status=202 if created else 200)

    async def validation_run(request):
        return web.json_response(core.store.validation_run(request.match_info["id"]))

    async def postprocess_jobs(request):
        if request.method == "POST":
            job, created = core.postprocess.create(request.match_info["id"], request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(core.postprocess.public(job), status=202 if created else 200)
        try:
            limit, offset = int(request.query.get("limit", 50)), int(request.query.get("offset", 0))
        except ValueError:
            raise ApiError("CORE_INVALID_INPUT", "limit and offset must be integers")
        page = core.postprocess.list(request.query.get("state"), request.query.get("source_image_id"), limit, offset)
        return web.json_response({**page, "items": [core.postprocess.public(job) for job in page["items"]]})

    async def postprocess_job(request):
        return web.json_response(core.postprocess.public(core.postprocess.get(request.match_info["id"])))

    async def postprocess_by_key(request):
        found = core.postprocess.by_key(request.headers.get("Idempotency-Key"))
        if not found:
            raise ApiError("CORE_NOT_FOUND", "Postprocess job key not found", 404)
        return web.json_response(core.postprocess.public(found[1]))

    async def cancel_postprocess(request):
        job = core.postprocess.cancel(request.match_info["id"])
        return web.json_response(core.postprocess.public(job), status=200 if job["state"] in {"completed", "failed", "cancelled"} else 202)

    async def postprocess_content(request):
        job, image = await core.postprocess.content(request.match_info["id"], request.match_info["image_id"])
        if job["generation_endpoint"] != core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Postprocess image belongs to another Generation endpoint", 409)
        try:
            async with core.session.get(core.generation_url + "/v1/images/" + image["image_id"], headers={"Authorization": "Bearer " + core.generation_token}, allow_redirects=False) as response:
                if response.status != 200:
                    raise ApiError("CORE_IMAGE_UNAVAILABLE", "Postprocess image unavailable", 502)
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > min(image["bytes"], 128 * 1024 * 1024):
                        raise ApiError("CORE_IMAGE_INTEGRITY", "Postprocess image exceeds recorded size", 502)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ApiError("CORE_IMAGE_UNAVAILABLE", "Postprocess image unavailable", 503)
        if len(data) != image["bytes"] or hashlib.sha256(data).hexdigest() != image["sha256"]:
            raise ApiError("CORE_IMAGE_INTEGRITY", "Postprocess image content changed", 502)
        return web.Response(body=bytes(data), content_type=image["media_type"])

    async def standalone(request):
        if request.method == "POST":
            result, created = core.standalone.create(request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(core.standalone.public(result), status=202 if created else 200)
        return web.json_response(core.standalone.public(core.standalone.get(request.match_info["id"])))

    async def standalone_by_key(request):
        found = core.standalone.by_key(request.headers.get("Idempotency-Key"))
        if not found:
            raise ApiError("CORE_NOT_FOUND", "Standalone job key not found", 404)
        return web.json_response(core.standalone.public(found[1]))

    async def standalone_checkpoints(request):
        return web.json_response(core.standalone.checkpoints())

    async def standalone_content(request):
        image = await core.standalone.content(request.match_info["id"], request.match_info["image_id"])
        try:
            async with core.session.get(core.generation_url + "/v1/images/" + image["generation_image_id"], headers={"Authorization": "Bearer " + core.generation_token}, allow_redirects=False) as response:
                if response.status != 200:
                    raise ApiError("CORE_IMAGE_UNAVAILABLE", "Generation image unavailable", 502)
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > min(image["bytes"], 128 * 1024 * 1024):
                        raise ApiError("CORE_IMAGE_INTEGRITY", "Image exceeds recorded size", 502)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ApiError("CORE_IMAGE_UNAVAILABLE", "Generation image unavailable", 503)
        if len(data) != image["bytes"] or hashlib.sha256(data).hexdigest() != image["sha256"]:
            raise ApiError("CORE_IMAGE_INTEGRITY", "Image content changed", 502)
        return web.Response(body=bytes(data), content_type=image["media_type"])

    category = r"/v1/{kind:works|characters|outfits}"
    app.add_routes([web.post("/v1/tasks/{id}/regenerations", regenerate), web.get("/v1/tasks/{id}/attempts", attempts),
                    web.get("/v1/regeneration-cycles/{id}", cycle), web.post("/v1/regeneration-cycles/{id}/stop", cycle), web.post("/v1/tasks/{id}/cancel", cancel_task), web.post("/v1/validation-runs/{id}/cancel", cancel_validation), web.get("/v1/gpu", gpu), web.post("/v1/gpu/acquire", gpu), web.post("/v1/gpu/release", gpu), web.get("/health", health), web.get(category, entity_collection), web.post(category, entity_collection),
                    web.get(category + "/{id}", entity_detail), web.patch(category + "/{id}", entity_detail),
                    web.get(category + "/{id}/revisions", history), web.get("/v1/settings", settings), web.patch("/v1/settings", settings),
                    web.get("/v1/frontend-connection", frontend_connection), web.put("/v1/frontend-connection", frontend_connection), web.get("/v1/operations/status", operations_status_view),
                    web.get("/v1/groups", groups), web.post("/v1/groups", groups), web.get("/v1/groups/{id}", group), web.post("/v1/prompts/preview", preview),
                    web.get("/v1/images", gallery), web.get("/v1/group-batches", batch_list),
                    web.get("/v1/tasks", tasks), web.post("/v1/tasks", tasks), web.get("/v1/tasks/by-key", by_key),
                    web.get("/v1/tasks/{id}", task), web.get("/v1/images/{id}", image),
                    web.get("/v1/images/{id}/content", image_content),
                    web.post("/v1/images/{id}/postprocess-jobs", postprocess_jobs),
                    web.get("/v1/images/{id}/validations", validations), web.post("/v1/images/{id}/validations", validations),
                    web.get("/v1/validation-runs/{id}", validation_run),
                    web.get("/v1/postprocess-jobs", postprocess_jobs), web.get("/v1/postprocess-jobs/by-key", postprocess_by_key),
                    web.get("/v1/postprocess-jobs/{id}", postprocess_job), web.post("/v1/postprocess-jobs/{id}/cancel", cancel_postprocess),
                    web.get("/v1/postprocess-jobs/{id}/images/{image_id}/content", postprocess_content),
                    web.post("/v1/standalone-jobs", standalone), web.get("/v1/standalone-jobs/by-key", standalone_by_key),
                    web.get("/v1/standalone-checkpoints", standalone_checkpoints),
                    web.get("/v1/standalone-jobs/{id}", standalone), web.get("/v1/standalone-jobs/{id}/images/{image_id}/content", standalone_content)])
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8190)
    parser.add_argument("--db", default=".atelierx/core/core.sqlite3")
    parser.add_argument("--generation-url", default="http://127.0.0.1:8189")
    parser.add_argument("--validation-config", help="Core-owned JSON of Validation endpoint and registered profile/provider snapshots")
    parser.add_argument("--gpu-config", help="Shared GPU runtime configuration JSON")
    parser.add_argument("--standalone-config", help="Core-owned standalone generation and local planner JSON")
    parser.add_argument("--frontend-connection-config", help="Private Cloudflare Access frontend connection JSON")
    parser.add_argument("--operations-status-url", help="Loopback URL of the local operations control panel")
    parser.add_argument("--operations-token-file", help="Read-only control panel status token file")
    args = parser.parse_args()
    token = os.environ.get("ATELIERX_SERVICE_TOKEN")
    validation_config = json.loads(Path(args.validation_config).read_text(encoding="utf-8")) if args.validation_config else None
    if validation_config and "core" in validation_config:
        validation_config = {**validation_config["core"], "profiles": validation_config["profiles"],
            "providers": {key: {"provider_id": key, **{field: value[field] for field in (
                "revision", "model", "timeout_seconds", "url", "response_format", "image_format", "shared_gpu") if field in value}}
                          for key, value in validation_config["providers"].items()}}
    web.run_app(create_app(args.db, args.generation_url, token, os.environ.get("ATELIERX_GENERATION_TOKEN", token),
                           validation_config=validation_config, validation_token=os.environ.get("ATELIERX_VALIDATION_TOKEN", token),
                           gpu_config=json.loads(Path(args.gpu_config).read_text(encoding="utf-8")) if args.gpu_config else None,
                           standalone_config=json.loads(Path(args.standalone_config).read_text(encoding="utf-8")) if args.standalone_config else None,
                           frontend_connection_path=args.frontend_connection_config,
                           operations_status={"url": args.operations_status_url, "token_file": args.operations_token_file} if args.operations_status_url or args.operations_token_file else None),
                host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
