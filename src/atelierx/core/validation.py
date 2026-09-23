"""Core-owned, explicit single-image validation orchestration."""
import asyncio
import hashlib
import uuid
import copy
from decimal import Decimal, ROUND_HALF_UP

import aiohttp

from ..common import ApiError, canonical
from .validation_settings import ValidationSettings
from ..validation_registry import public_provider


class CoreValidation:
    def __init__(self, core, config=None, token=None):
        self.core = core
        self.config = config or {}
        legacy = {"profiles": self.config.get("profiles", {}), "group_profiles": self.config.get("group_profiles", {}), "providers": {key: {field: value for field, value in item.items() if field != "api_key"} for key, item in self.config.get("providers", {}).items()}}
        self.settings = ValidationSettings(core.store.db, legacy)
        self.url = self.config.get("url", "").rstrip("/")
        self.token = token or core.token

    def freeze(self, selection):
        if not self.url:
            raise ApiError("CORE_VALIDATION_UNCONFIGURED", "Validation service is not configured", 503)
        if not isinstance(selection, dict) or set(selection) != {"profile_id", "provider_id"} or any(not isinstance(v, str) for v in selection.values()):
            raise ApiError("CORE_INVALID_INPUT", "Select registered profile_id and provider_id")
        try:
            frozen = self.settings.freeze(selection, legacy_provider=self.config.get("providers", {}).get(selection["provider_id"]))
        except ApiError as exc:
            if exc.code != "CORE_VALIDATION_SELECTION_UNKNOWN":
                raise
            profile = self.config.get("profiles", {}).get(selection["profile_id"])
            provider = self.config.get("providers", {}).get(selection["provider_id"])
            if profile is None or provider is None:
                raise
            # Historical compact Core test/config snapshots contain only id and
            # revision; retain them unchanged for the legacy endpoint contract.
            public = public_provider(provider)
            frozen = {"selection": selection, "profile": profile, "provider": public}
        return copy.deepcopy(dict(frozen, endpoint=self.url))

    def freeze_group(self, selection):
        if not self.url:
            raise ApiError("CORE_VALIDATION_UNCONFIGURED", "Validation service is not configured", 503)
        if not isinstance(selection, dict) or set(selection) != {"profile_id", "provider_id"} or any(not isinstance(value, str) for value in selection.values()):
            raise ApiError("CORE_INVALID_INPUT", "Select registered profile_id and provider_id")
        frozen = self.settings.freeze_group(selection, self.config.get("providers", {}).get(selection["provider_id"]))
        return copy.deepcopy(dict(frozen, endpoint=self.url))

    def submit(self, image_id, key, selection, frozen=None):
        if not key or len(key) > 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key of 1..200 characters is required")
        if not isinstance(selection, dict) or set(selection) != {"profile_id", "provider_id"} or any(
                not isinstance(value, str) for value in selection.values()):
            raise ApiError("CORE_INVALID_INPUT", "Select registered profile_id and provider_id")
        fingerprint = hashlib.sha256(canonical(dict(image_id=image_id, selection=selection)).encode()).hexdigest()
        previous = self.core.store.validation_by_key(key)
        if previous:
            if previous[0] != fingerprint:
                raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Validation key already has different content", 409)
            return previous[1], False
        if not self.url:
            raise ApiError("CORE_VALIDATION_UNCONFIGURED", "Validation service is not configured", 503)
        frozen = frozen or self.freeze(selection)
        profile, provider = frozen["profile"], frozen["provider"]
        if frozen and frozen["endpoint"] != self.url:
            raise ApiError("CORE_VALIDATION_ENDPOINT_CHANGED", "Selected validation endpoint changed", 409)
        if profile is None or provider is None:
            raise ApiError("CORE_VALIDATION_SELECTION_UNKNOWN", "Unknown validation profile or provider", 400)
        image = self.core.store.image(image_id)
        task = self.core.store.task(image["task_id"])
        if task["state"] != "generated":
            raise ApiError("CORE_IMAGE_NOT_READY", "Image generation has not completed", 409)
        if task["snapshot"]["generation_endpoint"] != self.core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Image belongs to another Generation endpoint", 409)
        gen = task["snapshot"]["generation_inputs"]
        payload = dict(image={"ref": image["id"], "source": {
            "type": "generation", "server_id": self.config.get("generation_server_id", "generation-local"),
            "image_id": image["generation_image_id"], "sha256": image["sha256"]},
            "positive_prompt": gen["positive_prompt"], "negative_prompt": gen["negative_prompt"],
            "negative_sources": task["snapshot"].get("negative_sources", {"global": gen["negative_prompt"], "character": ""})},
            generation_attempt_id=task["id"], profile=profile, provider=provider,
            expected_output={"width": self.output_dimension(task, "width"), "height": self.output_dimension(task, "height"), "media_type": image["media_type"], "alpha": self.output_alpha(task)},
            generation_settings={key: gen[key] for key in ("seed", "steps", "cfg") if key in gen} or None)
        return self.core.store.create_validation(image_id, key, fingerprint, payload, self.url), True

    @staticmethod
    def output_alpha(task):
        """Derive the output check from the immutable generation snapshot."""
        postprocess = task.get("snapshot", {}).get("postprocess")
        return "transparency_required" if isinstance(postprocess, dict) and "alpha" in postprocess else "not_required"

    @staticmethod
    def output_dimension(task, axis):
        snapshot = task["snapshot"]
        scale = snapshot.get("postprocess", {}).get("upscale", {}).get("scale", 1.5) if "upscale" in snapshot.get("postprocess", {}) else 1
        return max(1, int((Decimal(snapshot["generation_inputs"][axis]) * Decimal(str(scale))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))

    async def call(self, method, path, **kwargs):
        headers = {"Authorization": "Bearer " + self.token}
        headers.update(kwargs.pop("headers", {}))
        try:
            async with self.core.session.request(method, self.url + path, headers=headers, allow_redirects=False, **kwargs) as response:
                if response.status == 404:
                    return None
                # A gateway/service timeout leaves a persisted dispatch intent
                # ambiguous. Keep it active so the next tick can resolve by
                # idempotency key. A Validation-originated VAL_* error retains
                # its explicit terminal meaning even when sent via a gateway.
                if response.status in (502, 503, 504):
                    try:
                        failure = await response.json()
                        error = failure.get("error", {})
                        if isinstance(error.get("code"), str) and error["code"].startswith("VAL_") and isinstance(error.get("message"), str):
                            raise ApiError(error["code"], error["message"], 502)
                    except ApiError:
                        raise
                    except (aiohttp.ClientError, ValueError, AttributeError):
                        pass
                    raise ApiError("CORE_VALIDATION_UNAVAILABLE", "Validation temporarily unavailable", 503)
                if response.status not in (200, 202):
                    try:
                        failure = await response.json()
                        error = failure.get("error", {})
                        if isinstance(error.get("code"), str) and error["code"].startswith("VAL_") and isinstance(error.get("message"), str):
                            raise ApiError(error["code"], error["message"], 502)
                    except (aiohttp.ClientError, ValueError, AttributeError):
                        pass
                    raise ApiError("CORE_VALIDATION_REJECTED", f"Validation returned HTTP {response.status}", 502)
                result = await response.json()
                if not isinstance(result, dict):
                    raise ValueError("Expected object")
                return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise ApiError("CORE_VALIDATION_UNAVAILABLE", "Validation response unavailable", 503) from exc

    async def sync_registry(self):
        """Register all known public revisions; Validation keeps credentials local."""
        if not self.url:
            raise ApiError("CORE_VALIDATION_UNCONFIGURED", "Validation service is not configured", 503)
        result = await self.call("POST", "/v1/registry/snapshot", json=self.settings.registry())
        if result is None:
            raise ApiError("CORE_VALIDATION_REGISTRY_UNAVAILABLE", "Validation registry endpoint is unavailable", 503)
        return result

    async def setting_saved(self, setting, status=200):
        """The local revision is durable even if Validation is currently offline."""
        from aiohttp import web
        try:
            await self.sync_registry()
            synchronization = {"state": "synced", "error": None}
        except ApiError as exc:
            synchronization = {"state": "pending", "error": {"code": exc.code, "message": exc.message}}
        return web.json_response(dict(setting, synchronization=synchronization), status=status)

    def attach(self, app):
        """Attach authenticated Core settings endpoints (called by core.create_app)."""
        from aiohttp import web
        kinds = {"single-profiles": "profile", "group-profiles": "group_profile", "providers": "provider"}
        def kind(request):
            value = kinds.get(request.match_info["kind"])
            if not value: raise ApiError("CORE_NOT_FOUND", "Unknown validation setting kind", 404)
            return value
        async def collection(request):
            setting_kind = kind(request)
            if request.method == "GET":
                return web.json_response({"items": self.settings.list(setting_kind, request.query.get("include_archived") == "true")})
            created = self.settings.create(setting_kind, await request.json())
            return await self.setting_saved(created, status=201)
        async def item(request):
            setting_kind, ident = kind(request), request.match_info["id"]
            if request.method == "GET": return web.json_response(self.settings._public(self.settings.current(setting_kind, ident)))
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"revision", "setting"} or type(body["revision"]) is not int:
                raise ApiError("CORE_INVALID_INPUT", "revision and setting are required")
            result = self.settings.update(setting_kind, ident, body["revision"], body["setting"])
            return await self.setting_saved(result)
        async def history(request): return web.json_response({"items": self.settings.history(kind(request), request.match_info["id"])})
        async def clone(request):
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"id"} or not isinstance(body["id"], str): raise ApiError("CORE_INVALID_INPUT", "Clone id is required")
            result = self.settings.clone(kind(request), request.match_info["id"], body["id"])
            return await self.setting_saved(result, status=201)
        async def archive(request):
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"revision"} or type(body["revision"]) is not int: raise ApiError("CORE_INVALID_INPUT", "revision is required")
            result = self.settings.archive(kind(request), request.match_info["id"], body["revision"])
            return await self.setting_saved(result)
        async def connection(request):
            self.settings.current("provider", request.match_info["id"])
            result = await self.call("GET", "/health")
            return web.json_response({"validation_service_reachable": bool(result), "service": result.get("service") if result else None})
        app.add_routes([web.get("/v1/validation-settings/{kind}", collection), web.post("/v1/validation-settings/{kind}", collection), web.get("/v1/validation-settings/{kind}/{id}", item), web.patch("/v1/validation-settings/{kind}/{id}", item), web.get("/v1/validation-settings/{kind}/{id}/revisions", history), web.post("/v1/validation-settings/{kind}/{id}/clone", clone), web.post("/v1/validation-settings/{kind}/{id}/archive", archive), web.get("/v1/validation-settings/providers/{id}/connection", connection)])

    async def advance(self, run):
        run = self.core.store.validation_run(run["id"])
        if run["state"] in {"completed", "failed", "cancelled"}: return
        if not self.url or run["endpoint"] != self.url:
            raise ApiError("CORE_VALIDATION_ENDPOINT_CHANGED", "Saved validation targets a different endpoint", 409)
        key = "core-validation:" + run["id"]
        if run.get("cancel_requested") and run.get("job_id"):
            await self.call("POST", "/v1/validation-jobs/" + run["job_id"] + "/cancel")
        if run["state"] == "queued":
            # Managed settings may have been saved while Validation was offline.
            # Re-register immutable public revisions immediately before dispatch.
            registry = self.settings.registry()
            if registry["providers"]:
                await self.sync_registry()
            run["state"] = "dispatching"
            self.core.store.update_validation(run)
            job = await self.call("POST", "/v1/validations/single", headers={"Idempotency-Key": key}, json=run["request"])
        elif run["state"] == "dispatching":
            job = await self.call("GET", "/v1/validation-jobs/by-key", headers={"Idempotency-Key": key})
            if job is None:
                raise ApiError("CORE_VALIDATION_ACCEPTANCE_UNKNOWN", "Saved key was not found; no automatic resubmission", 502)
        else:
            job = await self.call("GET", "/v1/validation-jobs/" + run["job_id"])
        if job is None:
            raise ApiError("CORE_VALIDATION_JOB_MISSING", "Validation job was not found", 502)
        try:
            job_id = str(uuid.UUID(job["job_id"]))
            if job_id != job["job_id"] or (run["job_id"] and run["job_id"] != job_id):
                raise ValueError("Job identity changed")
            expected = dict(run["request"], schema_version="0.1", kind="single")
            if job.get("request") != run["request"] and job.get("request") != expected:
                raise ValueError("Request does not match saved snapshot")
            state, outcome = job["state"], job.get("outcome")
            if state == "cancelled":
                run.update(state="cancelled", outcome=None, result=None, error=None)
            elif state in {"completed", "failed"}:
                if outcome not in {"passed", "failed", "error"}:
                    raise ValueError("Missing outcome")
                if outcome == "error" and (not isinstance(job.get("error"), dict) or job.get("result") is not None):
                    raise ValueError("Invalid execution error")
                if outcome != "error" and (state != "completed" or job.get("error") is not None or not isinstance(job.get("result"), dict)):
                    raise ValueError("Invalid validation result")
                run.update(state=state, outcome=outcome, error=job.get("error"), result=job.get("result"))
            elif state in {"queued", "running", "submitting"}:
                run["state"] = "pending"
            else:
                raise ValueError("Unknown validation state")
            run["job_id"] = job_id
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ApiError("CORE_VALIDATION_PROTOCOL_ERROR", "Validation job does not match the saved request", 502) from exc
        self.core.store.update_validation(run)

    def cancel(self, run_id):
        run = self.core.store.validation_run(run_id)
        if run["state"] not in {"completed", "failed", "cancelled"}:
            run["cancel_requested"] = True
            if run["state"] == "queued":
                run.update(state="cancelled", outcome=None, result=None, error=None)
            self.core.store.update_validation(run)
        return self.core.store.validation_run(run_id)

    async def tick(self):
        for task in self.core.store.generated_for_validation():
            frozen = task["snapshot"]["validation"]
            try:
                for image in task["images"]:
                    self.submit(image["id"], "auto:" + task["id"] + ":" + image["id"], frozen["selection"], frozen)
            except ApiError as exc:
                if exc.code != "CORE_VALIDATION_ACTIVE":
                    self.core.store.task_metadata(task["id"], automatic_validation_error={"code": exc.code, "message": exc.message})
        for run in self.core.store.pending_validations():
            try:
                await self.advance(run)
            except ApiError as exc:
                if exc.code == "CORE_VALIDATION_UNAVAILABLE":
                    continue
                run.update(state="failed", outcome="error", result=None,
                           error={"code": exc.code, "message": exc.message})
                self.core.store.update_validation(run)
