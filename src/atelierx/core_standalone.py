"""Durable group-independent generation jobs owned by Core."""
import asyncio
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from urllib.parse import urlparse

import aiohttp

from .common import ApiError, canonical


class StandaloneJobs:
    def __init__(self, core, config, generation_settings, validate_postprocess_settings):
        self.core, self.config = core, config
        if config is not None:
            required = {"generation_inputs", "postprocess", "llm"}
            if not isinstance(config, dict) or set(config) - (required | {"seed_mode"}) or not required.issubset(config):
                raise ValueError("standalone config must contain generation_inputs, postprocess, and llm")
            if not isinstance(config.get("seed_mode", "fixed"), str) or config.get("seed_mode", "fixed") not in {"fixed", "random"}:
                raise ValueError("standalone seed_mode must be fixed or random")
            llm = config["llm"]
            if not isinstance(llm, dict) or set(llm) != {"url", "model", "api_key_env", "timeout_seconds"}:
                raise ValueError("standalone llm config is invalid")
            parsed = urlparse(llm.get("url", ""))
            if not all(isinstance(llm[key], str) and llm[key] for key in ("url", "model", "api_key_env")) or parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password or parsed.query or parsed.fragment or type(llm["timeout_seconds"]) not in (int, float) or not 0 < llm["timeout_seconds"] <= 120:
                raise ValueError("standalone llm config is invalid")
            generation = config["generation_inputs"]
            if not isinstance(generation, dict) or "negative_prompt" not in generation or not isinstance(generation["negative_prompt"], str):
                raise ValueError("standalone generation_inputs requires negative_prompt")
            normalized = generation_settings({key: value for key, value in generation.items() if key != "negative_prompt"})
            config = {**config, "generation_inputs": {**normalized, "negative_prompt": generation["negative_prompt"]}}
            if core.gpu.config and llm["model"] != core.gpu.config.get("model"):
                raise ValueError("standalone planner model must equal configured shared GPU model")
            if not isinstance(config["postprocess"], dict):
                raise ValueError("standalone postprocess must be an object")
            config["postprocess"] = validate_postprocess_settings(config["postprocess"])
            self.config = config
        core.store.db.execute("CREATE TABLE IF NOT EXISTS standalone_jobs (id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL, document TEXT NOT NULL)")
        core.store.db.commit()

    def get(self, job_id):
        row = self.core.store.db.execute("SELECT document FROM standalone_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Standalone job not found", 404)
        return json.loads(row[0])

    @staticmethod
    def public(job):
        result = {key: job[key] for key in ("id", "state", "images", "error", "validation", "created_at")}
        if type(job.get("seed")) is int:
            result["seed"] = job["seed"]
        return result

    def by_key(self, key):
        row = self.core.store.db.execute("SELECT fingerprint,document FROM standalone_jobs WHERE request_key=?", (key,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def save(self, job):
        with self.core.store.db:
            self.core.store.db.execute("UPDATE standalone_jobs SET state=?,document=? WHERE id=?", (job["state"], canonical(job), job["id"]))

    def create(self, key, body):
        if self.config is None:
            raise ApiError("CORE_STANDALONE_DISABLED", "Standalone jobs are not configured", 503)
        if not key or len(key) > 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key of 1..200 characters is required")
        allowed = {"prompt", "mode", "negative_prompt"}
        if not isinstance(body, dict) or set(body) - allowed or "prompt" not in body:
            raise ApiError("CORE_INVALID_INPUT", "Body requires a prompt and optional mode or negative_prompt")
        mode = body.get("mode", "direct")
        if not isinstance(mode, str):
            raise ApiError("CORE_INVALID_INPUT", "Mode must be natural or direct")
        mode = mode.strip().lower()
        if (mode not in ("natural", "direct") or not isinstance(body["prompt"], str)
                or not body["prompt"].strip() or len(body["prompt"]) > 20000
                or ("negative_prompt" in body and (not isinstance(body["negative_prompt"], str)
                                                    or len(body["negative_prompt"]) > 20000))):
            raise ApiError("CORE_INVALID_INPUT", "Body requires a nonempty prompt, supported mode, and optional negative_prompt")
        # Keep the legacy fingerprint for explicit lowercase direct requests
        # without a Negative, while making omitted and case-insensitive modes
        # semantically idempotent.
        body = {**body, "mode": mode}
        fingerprint = hashlib.sha256(canonical(body).encode()).hexdigest()
        old = self.by_key(key)
        if old:
            if old[0] != fingerprint:
                raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Request key already has different content", 409)
            return old[1], False
        inputs = dict(self.config["generation_inputs"])
        requested_negative = body.get("negative_prompt")
        if isinstance(requested_negative, str) and requested_negative.strip():
            default_negative = inputs["negative_prompt"]
            inputs["negative_prompt"] = (default_negative + ", " + requested_negative
                                         if default_negative.strip() else requested_negative)
        if self.config.get("seed_mode", "fixed") == "random":
            # Keep random bot seeds exactly representable by Worker/Discord JavaScript clients.
            inputs["seed"] = secrets.randbelow(2**53)
        job = {"id": str(uuid.uuid4()), "state": "queued", "created_at": time.time(), "request": body, "config": self.config, "generation_endpoint": self.core.generation_url,
               "generation_job_id": None, "generation_inputs": inputs, "seed": inputs["seed"], "images": [], "error": None,
               "validation": {"state": "not_requested", "outcome": None}}
        try:
            with self.core.store.db:
                self.core.store.db.execute("INSERT INTO standalone_jobs VALUES(?,?,?,?,?,?)", (job["id"], key, fingerprint, job["state"], job["created_at"], canonical(job)))
        except Exception:
            old = self.by_key(key)
            if old and old[0] == fingerprint:
                return old[1], False
            raise
        return job, True

    async def _plan(self, job):
        llm = job["config"]["llm"]
        secret = os.environ.get(llm["api_key_env"])
        if not secret:
            raise ApiError("CORE_PLANNER_UNAVAILABLE", "Configured planner credential is unavailable", 503)
        payload = {"model": llm["model"], "messages": [{"role": "system", "content": "Return only a concise positive image prompt. Do not answer conversationally or call tools."}, {"role": "user", "content": job["request"]["prompt"]}], "temperature": 0, "max_tokens": 1024}
        try:
            async with self.core.session.post(llm["url"], json=payload, headers={"Authorization": "Bearer " + secret}, timeout=aiohttp.ClientTimeout(total=llm["timeout_seconds"]), allow_redirects=False) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        raise ApiError("CORE_PLANNER_UNAVAILABLE", "Planner response exceeded size limit", 502)
                # A completed reply or explicit input/auth rejection proves this
                # inference has ended; transport loss and gateways do not.
                if response.status == 200 or response.status in (400, 401, 403, 404, 422, 429):
                    job["planner_response_received"] = True
                    self.save(job)
                if response.status != 200:
                    raise ApiError("CORE_PLANNER_REJECTED", "Local planner rejected the request", 502)
                value = json.loads(raw)
            prompt = value["choices"][0]["message"]["content"]
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
                raise ValueError()
            return prompt
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise ApiError("CORE_PLANNER_UNAVAILABLE", "Local planner response unavailable", 503) from exc

    async def advance(self, job):
        job = self.get(job["id"])
        if job["state"] in {"completed", "failed"}:
            return
        if job["generation_endpoint"] != self.core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Standalone job targets another Generation endpoint", 409)
        if job["state"] == "planning":
            if job.get("planner_response_received"):
                await self.core.gpu.release("planner", job["id"])
            raise ApiError("CORE_PLANNER_ACCEPTANCE_UNKNOWN", "Planner result is unknown after restart; no automatic retry", 502)
        if job["state"] == "queued":
            # Pre-seed persisted jobs created before seed snapshots were introduced.
            # They retain their configured fixed seed and are never rerandomized.
            if job.get("generation_inputs") is None:
                job["generation_inputs"] = dict(job["config"]["generation_inputs"])
                job["seed"] = job["generation_inputs"]["seed"]
                self.save(job)
            if job["request"]["mode"] == "natural":
                if self.core.gpu.config and job["config"]["llm"]["model"] != self.core.gpu.config.get("model"):
                    raise ApiError("CORE_PLANNER_MODEL_CHANGED", "Saved planner model differs from GPU configuration", 409)
                if not os.environ.get(job["config"]["llm"]["api_key_env"]):
                    raise ApiError("CORE_PLANNER_UNAVAILABLE", "Configured planner credential is unavailable", 503)
                granted = await self.core.gpu.acquire(self.core.session, "planner", job["id"])
                if not granted["granted"]: return
                job["state"] = "planning"; self.save(job)
                try:
                    positive = await self._plan(job)
                except ApiError:
                    # Planner acceptance is unknown after a failed call; retain the lease.
                    if job.get("planner_response_received"):
                        await self.core.gpu.release("planner", job["id"])
                    raise
                job["generation_inputs"] = {**job["generation_inputs"], "positive_prompt": positive}
                job["state"] = "planner_completed"; self.save(job)
                await self.core.gpu.release("planner", job["id"])
            else:
                job["generation_inputs"] = {**job["generation_inputs"], "positive_prompt": job["request"]["prompt"]}
                self.save(job)
            job["state"] = "ready_to_dispatch"; self.save(job)
            return
        if job["state"] == "planner_completed":
            await self.core.gpu.release("planner", job["id"])
            job["state"] = "ready_to_dispatch"; self.save(job)
            return
        key = "standalone:" + job["id"]
        if job["state"] == "ready_to_dispatch":
            job["state"] = "dispatching"; self.save(job)
            remote = await self.core.generation("POST", "/v1/nodes/anima/jobs", headers={"Idempotency-Key": key}, json={"inputs": job["generation_inputs"], "postprocess": job["config"]["postprocess"]})
        elif job["state"] == "dispatching":
            remote = await self.core.generation("GET", "/v1/jobs/by-key", headers={"Idempotency-Key": key})
        else:
            remote = await self.core.generation("GET", "/v1/jobs/" + job["generation_job_id"])
        if remote is None:
            raise ApiError("CORE_GENERATION_ACCEPTANCE_UNKNOWN", "No job found for persisted key; no automatic resubmission", 502)
        if (not isinstance(remote, dict) or remote.get("inputs") != job["generation_inputs"]
                or not isinstance(remote.get("job_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", remote["job_id"])
                or remote.get("requested_postprocess", {}) != job["config"]["postprocess"]):
            raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Generation Job does not match saved request", 502)
        job["generation_job_id"] = remote["job_id"]
        state = remote.get("state")
        if state == "completed":
            images = remote.get("images")
            if not isinstance(images, list) or not images:
                raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Generation returned no images", 502)
            seen = set()
            for item in images:
                if (not isinstance(item, dict) or not isinstance(item.get("image_id"), str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", item["image_id"])
                        or item["image_id"] in seen or type(item.get("bytes")) is not int or not 0 < item["bytes"] <= 128 * 1024 * 1024
                        or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                        or item.get("media_type") not in ("image/png", "image/webp")):
                    raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Invalid Generation image descriptor", 502)
                seen.add(item["image_id"])
            job["images"] = [{"image_id": item["image_id"], "generation_image_id": item["image_id"], "sha256": item["sha256"], "bytes": item["bytes"], "media_type": item["media_type"], "content_url": "/v1/standalone-jobs/" + job["id"] + "/images/" + item["image_id"] + "/content"} for item in remote.get("images", [])]
            job["state"] = "completed"
        elif state == "failed": job.update(state="failed", error={"code": "CORE_GENERATION_FAILED", "message": "Generation did not complete"})
        elif state == "cancelled": job.update(state="failed", error={"code": "CORE_GENERATION_CANCELLED", "message": "Generation was cancelled"})
        elif state in {"queued", "submitting", "submitted", "running"}: job["state"] = "running" if state == "running" else "generation_pending"
        else: raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Unknown Generation state", 502)
        self.save(job)

    async def tick(self):
        for row in self.core.store.db.execute("SELECT document FROM standalone_jobs WHERE state NOT IN ('completed','failed') ORDER BY created_at,id").fetchall():
            job = json.loads(row[0])
            try:
                await self.advance(job)
            except ApiError as exc:
                if exc.code == "CORE_GENERATION_UNAVAILABLE":
                    continue
                latest = self.get(job["id"])
                latest.update(state="failed", error={"code": exc.code, "message": exc.message}); self.save(latest)
            except Exception:
                latest = self.get(job["id"])
                latest.update(state="failed", error={"code": "CORE_INTERNAL_ERROR", "message": "Standalone job processing failure"}); self.save(latest)

    async def content(self, job_id, image_id):
        job = self.get(job_id)
        if job["generation_endpoint"] != self.core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Standalone image belongs to another Generation endpoint", 409)
        image = next((item for item in job["images"] if item["image_id"] == image_id), None)
        if not image: raise ApiError("CORE_NOT_FOUND", "Standalone image not found", 404)
        return image
