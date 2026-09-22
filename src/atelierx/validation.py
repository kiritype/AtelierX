"""Validation REST service with durable, single-image Vision jobs.

It accepts only trusted Generation image identifiers or files uploaded to this
service.  Provider credentials and URLs are process configuration, never
request fields.  A lost Provider response is recorded as an error: it is never
sent again automatically.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
from .runtime_info import RUNTIME_INFO
import hmac
import io
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
import uuid

import aiohttp
from aiohttp import web

from . import group_validation
from .common import ApiError, ProcessLock, canonical
from .gpu import permission
from .queue_api import attach_queue_api
from .regeneration_contract import validate_changes, proposal_schema
from .provider_response import diagnostics as provider_response_diagnostics, was_truncated
from .validation_evidence import EVALUATION_VERSION, RUBRIC, evidence_schema, normalize_evidence, requirements
from .validation_registry import RevisionRegistry

SERVICE = web.AppKey("validation", object)
TERMINAL = {"completed", "failed", "cancelled"}
MAX_UPLOAD = 16 * 1024 * 1024
PROVIDER_CONFIG_FIELDS = ("url", "revision", "model", "timeout_seconds", "response_format", "image_format", "shared_gpu", "max_tokens")
GROUP_EVALUATION_VERSION = 9


def provider_response_format(config, checks=None, proposals=False):
    mode = config.get("response_format", "json_object")
    if mode in {"json_object", "text"}:
        return {"type": mode}
    if mode != "json_schema":
        raise ApiError("VAL_PROVIDER_CONFIGURATION_INVALID", "Unsupported structured response format", 422)
    schema = evidence_schema(checks or [])
    if proposals:
        schema["properties"]["regeneration_changes"] = proposal_schema()
        schema["required"].append("regeneration_changes")
    return {"type": "json_schema", "json_schema": {"name": "atelierx_element_evidence",
            "strict": True, "schema": schema}}


def provider_config_fingerprint(config):
    """Preserve old fingerprints whose provider revisions predate max_tokens."""
    fields = {field: config.get(field) for field in PROVIDER_CONFIG_FIELDS if field != "max_tokens" or field in config}
    return hashlib.sha256(canonical(fields).encode()).hexdigest()


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def fail(message, code="VAL_INVALID_INPUT", status=400):
    raise ApiError(code, message, status)


def required_object(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        fail("Missing or unknown fields")


def identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", value):
        fail(f"{name} must be a non-empty identifier")
    return value


def request_body(value):
    if not isinstance(value, dict) or set(value) - {"image", "generation_attempt_id", "profile", "provider", "expected_output", "generation_settings"} or {"image", "generation_attempt_id", "profile", "provider", "expected_output"} - set(value):
        fail("Missing or unknown fields")
    value = dict(value)
    value.setdefault("generation_settings", None)
    image = value["image"]
    if not isinstance(image, dict):
        fail("image must be an object")
    required_object({key: item for key, item in image.items() if key != "negative_sources"}, {"ref", "source", "positive_prompt", "negative_prompt"})
    identifier(image["ref"], "image.ref")
    if not isinstance(image["positive_prompt"], str) or not image["positive_prompt"].strip() or not isinstance(image["negative_prompt"], str):
        fail("image prompts are required text")
    negative_sources = image.get("negative_sources", {"global": image["negative_prompt"], "character": ""})
    required_object(negative_sources, {"global", "character"})
    if any(not isinstance(part, str) for part in negative_sources.values()):
        fail("negative_sources values must be text")
    if ", ".join(negative_sources[key] for key in ("global", "character") if negative_sources[key].strip()) != image["negative_prompt"]:
        fail("negative_sources must reproduce the actual generation negative_prompt")
    value["image"] = dict(image, negative_sources=negative_sources)
    source = image["source"]
    if not isinstance(source, dict) or source.get("type") not in {"generation", "upload"}:
        fail("image.source must be generation or upload")
    source_fields = {"type", "server_id", "image_id", "sha256"} if source["type"] == "generation" else {"type", "upload_id", "sha256"}
    required_object(source, source_fields)
    for field in source_fields - {"type", "sha256"}:
        identifier(source[field], field)
    if not isinstance(source["sha256"], str) or len(source["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in source["sha256"]):
        fail("source.sha256 must be lowercase SHA-256")
    if value["generation_attempt_id"] is not None:
        identifier(value["generation_attempt_id"], "generation_attempt_id")
    for name in ("profile", "provider"):
        if not isinstance(value[name], dict): fail(f"{name} must be an object")
        identifier(value[name].get("profile_id" if name == "profile" else "provider_id"), name + " id")
    provider = value["provider"]
    required_object(provider, {"provider_id", "revision", "model", "timeout_seconds"} | ({"max_tokens"} if "max_tokens" in provider else set()))
    if type(provider.get("revision")) is not int or provider["revision"] < 0 or not isinstance(provider.get("model"), str) or not provider["model"] or type(provider.get("timeout_seconds")) is not int or provider["timeout_seconds"] < 1:
        fail("provider model and positive timeout_seconds are required")
    if "max_tokens" in provider and (type(provider["max_tokens"]) is not int or provider["max_tokens"] < 1):
        fail("provider max_tokens must be a positive integer")
    profile = value["profile"]
    required_object(profile, {"profile_id", "revision", "output_conditions", "positive_prompt", "negative_prompt", "body_parts", "metadata", "consistency"})
    if type(profile["revision"]) is not int or profile["revision"] < 0 or not isinstance(profile["body_parts"], list) or any(part not in {"hands", "face", "limbs"} for part in profile["body_parts"]) or any(type(profile[field]) is not bool for field in ("output_conditions", "positive_prompt", "negative_prompt", "metadata", "consistency")):
        fail("invalid profile")
    # Checks that this initial adapter cannot perform must never be silently ignored.
    if profile["metadata"] or profile["consistency"] or profile["body_parts"]:
        fail("Requested profile checks are not supported by the single-image adapter", "VAL_PROFILE_UNSUPPORTED", 422)
    if not any(profile[key] for key in ("positive_prompt", "negative_prompt", "output_conditions")):
        fail("At least one supported check must be enabled", "VAL_PROFILE_UNSUPPORTED", 422)
    if profile["output_conditions"] and value["expected_output"] is None: fail("expected_output is required by profile", "VAL_OUTPUT_CONDITIONS_REQUIRED", 422)
    if value["expected_output"] is not None and not isinstance(value["expected_output"], dict): fail("expected_output must be object or null")
    if value["generation_settings"] is not None and not isinstance(value["generation_settings"], dict): fail("generation_settings must be object or null")
    for key, bounds in {"seed": (0, 2**64 - 1), "steps": (1, 100), "cfg": (0, 20)}.items():
        settings = value["generation_settings"] or {}
        if key in settings:
            number = settings[key]
            if type(number) not in ((int,) if key != "cfg" else (int, float)) or not bounds[0] <= number <= bounds[1]:
                fail("Invalid numeric generation setting: " + key)
    return value


class Validation:
    def __init__(self, directory, token, providers=None, generation_sources=None, profiles=None, poll=.25):
        self.directory, self.token = Path(directory), token
        self.jobs_dir, self.uploads_dir = self.directory / "jobs", self.directory / "uploads"
        self.jobs_dir.mkdir(parents=True, exist_ok=True); self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.owner = ProcessLock(self.directory / "service.lock")
        self.providers, self.generation_sources, self.profiles, self.poll = providers or {}, generation_sources or {}, profiles or {}, poll
        self.registry = RevisionRegistry(self.providers, self.profiles, self.directory / "revision-registry.json")
        self.jobs, self.keys, self.lock = {}, {}, asyncio.Lock()
        for path in self.jobs_dir.glob("*.json"):
            job = json.loads(path.read_text(encoding="utf-8")); self.jobs[job["job_id"]] = job; self.keys[job["idempotency_key"]] = job["job_id"]

    def save(self, job):
        if job.get("cancel_requested") and job["state"] in {"completed", "failed"}:
            job["late_result"] = {"outcome": job.get("outcome"), "error": job.get("error")}
            job.update(state="cancelled", outcome=None, result=None, error=None)
        job["updated_at"] = time.time(); atomic_json(self.jobs_dir / (job["job_id"] + ".json"), job)

    def public(self, job):
        return {key: value for key, value in job.items() if key not in {"idempotency_key", "fingerprint"}}

    async def submit(self, key, raw, kind="single"):
        if not key or len(key) > 200: fail("Idempotency-Key (1..200 characters) is required", "VAL_INVALID_KEY")
        request = group_validation.request_body(raw, request_body) if kind == "group" else request_body(raw)
        fingerprint = hashlib.sha256(canonical(request if kind == "single" else {"kind": kind, "request": request}).encode()).hexdigest()
        async with self.lock:
            if key in self.keys:
                old = self.jobs[self.keys[key]]
                if old["fingerprint"] != fingerprint: fail("Key was used with different input", "VAL_IDEMPOTENCY_CONFLICT", 409)
                return old, False
            if self.registry.enabled:
                configured_profile = self.registry.profile(request["profile"])
                configured_provider = self.registry.provider(request["provider"])
            else:
                configured_profile = self.profiles.get(request["profile"]["profile_id"])
                configured_provider = self.providers.get(request["provider"]["provider_id"])
                if configured_profile != request["profile"]: fail("Profile snapshot does not match configured profile", "VAL_PROFILE_MISMATCH", 422)
                if not configured_provider:
                    fail("Provider snapshot does not match configured provider", "VAL_PROVIDER_MISMATCH", 422)
                provider_fields = ("revision", "model", "timeout_seconds") + (("max_tokens",) if "max_tokens" in configured_provider or "max_tokens" in request["provider"] else ())
                if any(configured_provider.get(k) != request["provider"].get(k) for k in provider_fields):
                    fail("Provider snapshot does not match configured provider", "VAL_PROVIDER_MISMATCH", 422)
            provider_response_format(configured_provider)
            config_fingerprint = provider_config_fingerprint(configured_provider)
            evaluation_version = GROUP_EVALUATION_VERSION if kind == "group" else EVALUATION_VERSION
            job = {"job_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()), "state": "queued", "kind": kind, "created_at": time.time(), "request": request, "idempotency_key": key, "fingerprint": fingerprint, "provider_config_fingerprint": config_fingerprint, "evaluation_version": evaluation_version, "outcome": None, "result": None, "error": None}
            self.save(job); self.jobs[job["job_id"]] = job; self.keys[key] = job["job_id"]
            return job, True

    async def image_bytes(self, request):
        source = request["image"]["source"]
        if source["type"] == "upload":
            try: uuid.UUID(source["upload_id"])
            except ValueError: fail("upload_id is invalid", "VAL_IMAGE_UNAVAILABLE", 422)
            path = self.uploads_dir / (source["upload_id"] + ".bin")
            if not path.is_file(): fail("Uploaded image is unavailable", "VAL_IMAGE_UNAVAILABLE", 422)
            data = path.read_bytes()
        else:
            config = self.generation_sources.get(source["server_id"])
            if not config: fail("Generation server is not configured", "VAL_IMAGE_UNAVAILABLE", 422)
            headers = {"Authorization": "Bearer " + config["token"]}
            try:
                async with self.session.get(config["url"].rstrip("/") + "/v1/images/" + quote(source["image_id"], safe=""), headers=headers, allow_redirects=False) as response:
                    if response.status != 200: fail("Generation image is unavailable", "VAL_IMAGE_UNAVAILABLE", 422)
                    chunks, total = [], 0
                    async for chunk in response.content.iter_chunked(65536):
                        total += len(chunk)
                        if total > MAX_UPLOAD: fail("Generation image exceeds limit", "VAL_IMAGE_TOO_LARGE", 422)
                        chunks.append(chunk)
                    data = b"".join(chunks)
            except aiohttp.ClientError as exc: raise ApiError("VAL_IMAGE_UNAVAILABLE", "Generation image cannot be reached", 503) from exc
        if len(data) > MAX_UPLOAD or hashlib.sha256(data).hexdigest() != source["sha256"]: fail("Image integrity check failed", "VAL_IMAGE_INTEGRITY", 422)
        data, media_type, width, height, has_alpha, transparent = self.decode_image(data)
        expected = request["expected_output"]
        if request["profile"]["output_conditions"]:
            if not isinstance(expected.get("width"), int) or not isinstance(expected.get("height"), int) or expected.get("media_type") not in {"image/png", "image/webp"} or expected.get("alpha") not in {"not_required", "channel_required", "transparency_required"}:
                fail("expected_output is invalid")
            if (width, height, media_type) != (expected["width"], expected["height"], expected["media_type"]):
                fail("Image does not meet deterministic output conditions", "VAL_OUTPUT_CONDITIONS_FAILED", 422)
            if expected["alpha"] == "channel_required" and not has_alpha:
                fail("Image lacks required alpha channel", "VAL_OUTPUT_CONDITIONS_FAILED", 422)
            if expected["alpha"] == "transparency_required" and not transparent:
                fail("Image lacks required transparency", "VAL_OUTPUT_CONDITIONS_FAILED", 422)
        return data, media_type

    def decode_image(self, data):
        """Decode verifies image content and rejects animation; Pillow is an explicit runtime dependency."""
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
                    fail("Only static PNG and WebP images are supported", "VAL_IMAGE_INVALID", 422)
                if image.width * image.height > 40_000_000:
                    fail("Decoded image exceeds pixel limit", "VAL_IMAGE_TOO_LARGE", 422)
                image.load()
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                alpha = image.convert("RGBA").getchannel("A") if has_alpha else None
                return data, "image/png" if image.format == "PNG" else "image/webp", image.width, image.height, has_alpha, bool(alpha and alpha.getextrema()[0] < 255)
        except ImportError as exc:
            raise ApiError("VAL_IMAGE_DECODER_UNAVAILABLE", "Image decoder is not installed", 503) from exc
        except ApiError: raise
        except Exception as exc:
            raise ApiError("VAL_IMAGE_INVALID", "Image cannot be decoded", 422) from exc

    async def provider(self, job, data, media_type):
        configured = self.registry.provider(job["request"]["provider"]) if self.registry.enabled else self.providers.get(job["request"]["provider"]["provider_id"])
        provider = job["request"]["provider"]
        if configured.get("model") != provider["model"]: raise ApiError("VAL_PROVIDER_MISMATCH", "Provider model does not match configured snapshot", 422)
        image_format = configured.get("image_format", "original")
        if image_format not in {"original", "png"}:
            raise ApiError("VAL_PROVIDER_CONFIGURATION_INVALID", "Unsupported provider image format", 422)
        original_hash = hashlib.sha256(data).hexdigest()
        original_media = media_type
        if image_format == "png" and media_type != "image/png":
            from PIL import Image
            with Image.open(io.BytesIO(data)) as decoded:
                converted = decoded.convert("RGBA" if "A" in decoded.getbands() else "RGB")
                output = io.BytesIO()
                converted.save(output, format="PNG")
                data = output.getvalue()
            if len(data) > MAX_UPLOAD:
                raise ApiError("VAL_IMAGE_TOO_LARGE", "Provider image exceeds transfer limit after conversion", 422)
            media_type = "image/png"
        job["provider_image"] = {"source_sha256": original_hash, "source_media_type": original_media,
                                 "sha256": hashlib.sha256(data).hexdigest(), "media_type": media_type, "bytes": len(data)}
        self.save(job)
        checks = requirements(job["request"])
        visual_checks = [{key: check[key] for key in ("id", "kind", "requirement")} for check in checks]
        content = [{"type": "text", "text": "Required element checklist: " + canonical(visual_checks)},
                   {"type": "image_url", "image_url": {"url": "data:" + media_type + ";base64," + base64.b64encode(data).decode()}}]
        context = {key: value for key, value in (job["request"].get("generation_settings") or {}).items() if key in {"seed", "steps", "cfg"} and type(value) in (int, float)}
        rubric = RUBRIC
        if context:
            content.append({"type": "text", "text": "Actual numeric generation settings: " + canonical(context)})
            rubric += " Return regeneration_changes as an array. For failed checks only, propose minimal evidence-linked numeric seed/steps/cfg changes when justified by supplied settings. Do not default every failure to a seed change. Each change needs field, value, reason and failed evidence_ids. Use [] if passed or information is insufficient. Never change the requested visual intent. Steps must be integer 1..100, cfg 0..20, seed a nonnegative integer."
        body = {"model": provider["model"], "messages": [{"role": "system", "content": rubric},
                {"role": "user", "content": content}], "response_format": provider_response_format(configured, checks, bool(context)), "temperature": 0}
        if "max_tokens" in configured:
            body["max_tokens"] = configured["max_tokens"]
        headers = {"Authorization": "Bearer " + configured["api_key"], "Content-Type": "application/json"}
        try:
            timeout = aiohttp.ClientTimeout(total=provider["timeout_seconds"])
            async with self.session.post(configured["url"].rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=timeout, allow_redirects=False) as response:
                if response.status != 200: raise ApiError("VAL_PROVIDER_REJECTED", f"Provider rejected validation (HTTP {response.status})", 502)
                response_bytes = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    response_bytes.extend(chunk)
                    if len(response_bytes) > 2 * 1024 * 1024:
                        raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Provider response exceeds the supported limit", 502)
                try:
                    payload = json.loads(response_bytes)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Provider response could not be parsed", 502) from exc
                job["provider_response"] = provider_response_diagnostics(payload)
                self.save(job)
                if was_truncated(payload):
                    raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Provider response was truncated", 502)
        except asyncio.TimeoutError as exc: raise ApiError("VAL_PROVIDER_TIMEOUT", "Provider did not respond in time", 504) from exc
        except aiohttp.ClientError as exc: raise ApiError("VAL_PROVIDER_UNAVAILABLE", "Provider response unavailable", 503) from exc
        try:
            answer = json.loads(payload["choices"][0]["message"]["content"])
            changes = answer.pop("regeneration_changes", []) if context and isinstance(answer, dict) else []
            result = normalize_evidence(answer, checks)
            if context:
                result["regeneration"]["changes"] = validate_changes(changes, result["evidence"], context)
            if result["outcome"] == "failed" and not changes:
                result["regeneration"]["proposal_unavailable_reason"] = "No justified supported changes were provided"
            return result
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc: raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Provider response could not be parsed", 502) from exc

    async def run(self, job):
        configured = self.registry.provider(job["request"]["provider"]) if self.registry.enabled else self.providers.get(job["request"]["provider"]["provider_id"])
        if job["state"] == "queued" and configured.get("shared_gpu"):
            if not getattr(self, "coordinator_url", None):
                job.update(state="failed", outcome="error", error={"code": "VAL_GPU_UNCONFIGURED", "message": "Shared GPU requires Core coordinator", "stage": "runtime"})
                self.save(job); return
            if not await permission(self, job, "validation"):
                return
            if job["state"] in TERMINAL: return
        if job["state"] in {"submitting", "running"}:
            job.update(state="failed", outcome="error", error={"code":"VAL_PROVIDER_ACCEPTANCE_UNKNOWN", "message":"Provider acceptance is unknown; no automatic resubmission", "stage":"recovery"}); self.save(job); return
        expected_evaluation = GROUP_EVALUATION_VERSION if job.get("kind") == "group" else EVALUATION_VERSION
        if job.get("evaluation_version") != expected_evaluation:
            job.update(state="failed", outcome="error", result=None, error={"code": "VAL_EVALUATION_CHANGED", "message": "Evaluation contract changed after submission", "stage": "recovery"})
            self.save(job)
            return
        configured = self.registry.provider(job["request"]["provider"]) if self.registry.enabled else self.providers.get(job["request"]["provider"]["provider_id"])
        actual_fingerprint = provider_config_fingerprint(configured) if configured else None
        if actual_fingerprint != job.get("provider_config_fingerprint"):
            job.update(state="failed", outcome="error", result=None, error={"code":"VAL_PROVIDER_CONFIG_CHANGED", "message":"Provider configuration changed after submission", "stage":"recovery"}); self.save(job); return
        job["state"] = "submitting"; self.save(job)
        try:
            if job["kind"] == "group":
                await group_validation.run(self, job)
                return
            data, media = await self.image_bytes(job["request"])
            job["state"] = "running"; self.save(job)
            if not requirements(job["request"]):
                result = {"outcome": "passed", "findings": [], "regeneration": {"required": False, "reason": "Enabled local output checks passed", "changes": []}}
            else:
                result = await self.provider(job, data, media)
            job.update(state="completed", outcome=result["outcome"], result={"findings": result["findings"], "regeneration": result["regeneration"], "evidence": result.get("evidence", [])}, error=None)
        except ApiError as exc:
            if exc.code == "VAL_OUTPUT_CONDITIONS_FAILED":
                job.update(state="completed", outcome="failed", result={"findings":[{"code":"output_conditions","feature":"output_conditions","expected":"Configured output conditions","observed":exc.message}],"regeneration":{"required":True,"reason":"Output conditions failed.","changes":[]}}, error=None)
            else:
                job.update(state="failed", outcome="error", result=None, error={"code": exc.code, "message": exc.message, "stage": "provider" if exc.code.startswith("VAL_PROVIDER") else "access"})
        self.save(job)

    async def worker(self):
        while True:
            for done in list(self.jobs.values()):
                uncertain = ((done.get("error") or (done.get("late_result") or {}).get("error")) or {}).get("code")
                if done["state"] in TERMINAL and done.get("gpu_requested") and uncertain not in {"VAL_PROVIDER_ACCEPTANCE_UNKNOWN", "VAL_PROVIDER_TIMEOUT", "VAL_PROVIDER_UNAVAILABLE"}:
                    try: await permission(self, done, "validation", release=True)
                    except (aiohttp.ClientError, asyncio.TimeoutError): pass
            candidates = sorted((x for x in self.jobs.values() if x["state"] not in TERMINAL), key=lambda x: x["created_at"])
            if candidates:
                try: await self.run(candidates[0])
                except Exception:
                    job = candidates[0]; job.update(state="failed", outcome="error", result=None, error={"code":"VAL_INTERNAL_ERROR", "message":"Validation internal failure", "stage":"internal"}); self.save(job)
            await asyncio.sleep(self.poll)


@web.middleware
async def errors(request, handler):
    service = request.app[SERVICE]
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied.encode(), ("Bearer " + service.token).encode()):
        return web.json_response({"error":{"code":"VAL_UNAUTHORIZED","message":"Bearer token required"}}, status=401)
    try: return await handler(request)
    except ApiError as exc: return web.json_response({"error":{"code":exc.code,"message":exc.message}}, status=exc.status)
    except (json.JSONDecodeError, UnicodeDecodeError): return web.json_response({"error":{"code":"VAL_INVALID_JSON","message":"Invalid JSON"}}, status=400)


def create_app(directory, token, providers=None, generation_sources=None, profiles=None, poll=.25, coordinator_url=None):
    if not token: raise ValueError("ATELIERX_SERVICE_TOKEN must be set")
    app = web.Application(middlewares=[errors], client_max_size=MAX_UPLOAD + 1024); service = Validation(directory, token, providers, generation_sources, profiles, poll); app[SERVICE] = service
    service.coordinator_url = coordinator_url
    attach_queue_api(app, lambda: [service.public(job) for job in service.jobs.values()])
    async def lifecycle(app):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            service.session = session; worker = asyncio.create_task(service.worker()); yield; worker.cancel()
            with contextlib.suppress(asyncio.CancelledError): await worker
        service.owner.close()
    app.cleanup_ctx.append(lifecycle)
    async def health(request):
        return web.json_response({**RUNTIME_INFO, "service":"validation","status":"ok"})
    async def registry(request):
        service.registry.apply(await request.json())
        return web.json_response({"status":"ok"})
    async def upload(request):
        data = await request.read()
        if not data or len(data) > MAX_UPLOAD: fail("Upload exceeds limit", "VAL_UPLOAD_TOO_LARGE", 413)
        _, media, _, _, _, _ = service.decode_image(data)
        upload_id = str(uuid.uuid4()); (service.uploads_dir / (upload_id + ".bin")).write_bytes(data)
        return web.json_response({"upload_id":upload_id,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data),"media_type":media}, status=201)
    async def submit(request):
        job, created = await service.submit(request.headers.get("Idempotency-Key"), await request.json(), "group" if request.path.endswith("/group") else "single")
        return web.json_response(service.public(job), status=202 if created else 200, headers={"Location":"/v1/validation-jobs/" + job["job_id"]})
    async def get_job(request):
        job = service.jobs.get(request.match_info["job_id"])
        if not job: fail("Job not found", "VAL_JOB_NOT_FOUND", 404)
        return web.json_response(service.public(job))
    async def by_key(request):
        key = request.headers.get("Idempotency-Key"); job_id = service.keys.get(key)
        if not job_id: fail("Job not found", "VAL_JOB_NOT_FOUND", 404)
        return web.json_response(service.public(service.jobs[job_id]))
    async def cancel(request):
        job = service.jobs.get(request.match_info["job_id"])
        if not job: fail("Job not found", "VAL_JOB_NOT_FOUND", 404)
        if job["state"] not in TERMINAL:
            job["cancel_requested"] = True
            if job["state"] == "queued": job.update(state="cancelled", outcome=None, result=None, error=None)
            service.save(job)
        return web.json_response(service.public(job), status=200 if job["state"] in TERMINAL else 202)
    app.add_routes([web.post("/v1/registry/snapshot",registry), web.post("/v1/validation-jobs/{job_id}/cancel",cancel), web.get("/health",health), web.post("/v1/uploads",upload), web.post("/v1/validations/single",submit), web.post("/v1/validations/group",submit), web.get("/v1/validation-jobs/by-key",by_key), web.get("/v1/validation-jobs/{job_id}",get_job)])
    return app


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--port",type=int,default=8191); parser.add_argument("--data-dir",default=".atelierx/validation"); parser.add_argument("--config", required=True, help="server-owned JSON provider/source/profile registry"); args=parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) - {"providers", "generation_sources", "profiles", "core", "coordinator_url"}:
        raise ValueError("config contains only providers, generation_sources, profiles, and core")
    for source in config.get("generation_sources", {}).values():
        if "token_env" in source:
            source["token"] = os.environ.get(source["token_env"], "")
            if not source["token"]:
                raise ValueError("Generation source token environment variable is not set")
    for provider in config.get("providers", {}).values():
        if "api_key_env" in provider:
            provider["api_key"] = os.environ.get(provider["api_key_env"], "")
            if not provider["api_key"]:
                raise ValueError("Vision provider key environment variable is not set")
    web.run_app(create_app(args.data_dir, os.environ.get("ATELIERX_SERVICE_TOKEN"), config.get("providers"), config.get("generation_sources"), config.get("profiles"), coordinator_url=config.get("coordinator_url")), host="127.0.0.1", port=args.port)


if __name__ == "__main__": main()
