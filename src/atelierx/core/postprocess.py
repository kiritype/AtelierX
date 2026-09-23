"""Core-owned tracking for postprocessing already-registered Core images."""
import hashlib
import json
import re
import time
import uuid

from ..common import ApiError, canonical
from .presets import validate_postprocess_settings
from ._output_names import build_output_name

TERMINAL = {"completed", "failed", "cancelled"}
OBSERVATION_SECONDS = 300  # Operator recovery bound; not a product retention policy.


class CorePostprocess:
    def __init__(self, core):
        self.core = core
        core.store.db.execute("CREATE TABLE IF NOT EXISTS postprocess_jobs (id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL, document TEXT NOT NULL)")
        core.store.db.commit()

    def get(self, job_id):
        row = self.core.store.db.execute("SELECT document FROM postprocess_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Postprocess job not found", 404)
        return json.loads(row[0])

    def by_key(self, key):
        row = self.core.store.db.execute("SELECT fingerprint,document FROM postprocess_jobs WHERE request_key=?", (key,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def save(self, job):
        job["updated_at"] = time.time()
        with self.core.store.db:
            self.core.store.db.execute("UPDATE postprocess_jobs SET state=?,document=? WHERE id=? AND state NOT IN ('completed','failed','cancelled')", (job["state"], canonical(job), job["id"]))

    def list(self, state=None, source_image_id=None, limit=50, offset=0):
        if state is not None and (not isinstance(state, str) or state not in {"queued", "dispatching", "generation_pending", "running", *TERMINAL}):
            raise ApiError("CORE_INVALID_INPUT", "Unknown postprocess job state")
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ApiError("CORE_INVALID_INPUT", "limit must be 1..200 and offset nonnegative")
        if source_image_id is not None:
            self.core.store.image(source_image_id)
        where = "(? IS NULL OR state=?) AND (? IS NULL OR json_extract(document, '$.source_image_id')=?)"
        rows = self.core.store.db.execute("SELECT document FROM postprocess_jobs WHERE " + where + " ORDER BY created_at DESC,id LIMIT ? OFFSET ?", (state, state, source_image_id, source_image_id, limit, offset)).fetchall()
        total = self.core.store.db.execute("SELECT COUNT(*) FROM postprocess_jobs WHERE " + where, (state, state, source_image_id, source_image_id)).fetchone()[0]
        return {"items": [json.loads(row[0]) for row in rows], "limit": limit, "offset": offset, "total": total}

    @staticmethod
    def public(job):
        fields = {"id", "state", "output_name", "source_image_id", "source_generation_image_id", "source_sha256", "source_media_type", "generation_job_id", "requested_postprocess", "postprocess", "preset_source", "error", "cancel_requested", "created_at", "updated_at"}
        result = {key: job[key] for key in fields if key in job}
        result["images"] = [{**{key: item[key] for key in ("image_id", "sha256", "bytes", "media_type", "content_url")}, "output_path": item["output_path"] if isinstance(item.get("output_path"), str) else None} for item in job.get("images", [])]
        return result

    def _resolve(self, body):
        if not isinstance(body, dict) or set(body) not in ({"postprocess"}, {"preset"}):
            raise ApiError("CORE_INVALID_INPUT", "Body requires postprocess or preset")
        if "postprocess" in body:
            if not isinstance(body["postprocess"], dict):
                raise ApiError("CORE_INVALID_INPUT", "postprocess must be an object")
            settings = validate_postprocess_settings(body["postprocess"])
            if not settings:
                raise ApiError("CORE_INVALID_INPUT", "At least one postprocess stage is required")
            return body["postprocess"], settings, None
        choice = body["preset"]
        if (not isinstance(choice, dict) or set(choice) != {"id", "revision"}
                or not isinstance(choice["id"], str) or not choice["id"]
                or type(choice["revision"]) is not int or choice["revision"] < 1):
            raise ApiError("CORE_INVALID_INPUT", "preset requires id and revision")
        frozen = self.core.presets.snapshot("postprocess", choice["id"], choice["revision"])
        if not frozen["settings"]:
            raise ApiError("CORE_INVALID_INPUT", "Preset has no postprocess stages")
        return frozen["settings"], frozen["settings"], frozen["preset"]

    def create(self, image_id, key, body):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ApiError("CORE_INVALID_INPUT", "Idempotency-Key of 1..200 characters is required")
        if not isinstance(body, dict):
            raise ApiError("CORE_INVALID_INPUT", "Body requires postprocess or preset")
        fingerprint = hashlib.sha256(canonical({"image_id": image_id, "body": body}).encode()).hexdigest()
        old = self.by_key(key)
        if old:
            if old[0] != fingerprint:
                raise ApiError("CORE_IDEMPOTENCY_CONFLICT", "Request key already has different content", 409)
            return old[1], False
        requested, resolved, preset = self._resolve(body)
        image = self.core.store.image(image_id)
        task = self.core.store.task(image["task_id"])
        endpoint = task["snapshot"].get("generation_endpoint")
        if not isinstance(endpoint, str) or endpoint != self.core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Image belongs to another Generation endpoint", 409)
        now = time.time()
        job = {"id": str(uuid.uuid4()), "state": "queued", "created_at": now, "updated_at": now,
               "output_name": build_output_name("AtelierX", "postprocess", time.strftime("%Y-%m-%d", time.localtime(now)), image_id[:8]),
               "source_image_id": image_id, "source_generation_image_id": image["generation_image_id"],
               "source_sha256": image["sha256"], "source_media_type": image["media_type"],
               "source_inputs": task["snapshot"]["generation_inputs"], "generation_endpoint": endpoint,
               "generation_job_id": None, "requested_postprocess": requested, "postprocess": resolved,
               "preset_source": preset, "images": [], "error": None}
        try:
            with self.core.store.db:
                self.core.store.db.execute("INSERT INTO postprocess_jobs VALUES(?,?,?,?,?,?)", (job["id"], key, fingerprint, job["state"], job["created_at"], canonical(job)))
        except Exception:
            old = self.by_key(key)
            if old and old[0] == fingerprint:
                return old[1], False
            raise
        return job, True

    def cancel(self, job_id):
        job = self.get(job_id)
        if job["state"] not in TERMINAL:
            job["cancel_requested"] = True
            if job["state"] == "queued":
                job["state"] = "cancelled"
            self.save(job)
        return self.get(job_id)

    def _verify(self, job, remote):
        try:
            if (not isinstance(remote, dict) or remote.get("kind") != "postprocess"
                    or remote.get("source_image_id") != job["source_generation_image_id"]
                    or remote.get("source_sha256") != job["source_sha256"]
                    or remote.get("source_media_type") != job["source_media_type"]
                    or remote.get("inputs") != job["source_inputs"]
                    or remote.get("requested_postprocess") != job["requested_postprocess"]
                    or not isinstance(remote.get("job_id"), str) or not re.fullmatch(r"[0-9a-f-]{36}", remote["job_id"])):
                raise ValueError()
        except (TypeError, ValueError):
            raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Generation postprocess job does not match saved request", 502)
        if job.get("generation_job_id") and job["generation_job_id"] != remote["job_id"]:
            raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Generation postprocess job ID changed", 502)
        job["generation_job_id"] = remote["job_id"]

    async def advance(self, job):
        job = self.get(job["id"])
        if job["state"] in TERMINAL:
            return
        if job["generation_endpoint"] != self.core.generation_url:
            raise ApiError("CORE_GENERATION_ENDPOINT_CHANGED", "Postprocess job targets another Generation endpoint", 409)
        internal_key = "core:postprocess:" + job["id"]
        if job.get("cancel_requested") and job.get("generation_job_id"):
            await self.core.generation("POST", "/v1/jobs/" + job["generation_job_id"] + "/cancel")
            job = self.get(job["id"])
            if job["state"] in TERMINAL:
                return
        if job["state"] == "queued":
            job["state"] = "dispatching"; job["observation_deadline"] = time.time() + OBSERVATION_SECONDS; self.save(job)
            remote = await self.core.generation("POST", "/v1/images/" + job["source_generation_image_id"] + "/postprocess-jobs", headers={"Idempotency-Key": internal_key}, json={"postprocess": job["requested_postprocess"], **({"output_name": job["output_name"]} if job.get("output_name") else {})})
        elif job["state"] == "dispatching":
            remote = await self.core.generation("GET", "/v1/jobs/by-key", headers={"Idempotency-Key": internal_key})
            if remote is None:
                raise ApiError("CORE_GENERATION_ACCEPTANCE_UNKNOWN", "No postprocess job found for persisted key; no automatic resubmission", 502)
        else:
            remote = await self.core.generation("GET", "/v1/jobs/" + job["generation_job_id"])
        if remote is None:
            raise ApiError("CORE_GENERATION_JOB_MISSING", "Generation postprocess job is missing", 502)
        latest = self.get(job["id"])
        if latest["state"] in TERMINAL:
            return
        job = latest
        self._verify(job, remote)
        job.pop("unavailable_since", None)
        state = remote.get("state")
        if state == "completed":
            images, seen = [], set()
            remote_images = remote.get("images")
            if not isinstance(remote_images, list):
                raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Completed postprocess job has invalid images", 502)
            for item in remote_images:
                if (not isinstance(item, dict) or not isinstance(item.get("image_id"), str) or item["image_id"] in seen
                        or not re.fullmatch(re.escape(job["generation_job_id"]) + r"-\d+", item["image_id"])
                        or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                        or type(item.get("bytes")) is not int or item["bytes"] <= 0 or item.get("media_type") not in {"image/png", "image/webp"}):
                    raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Invalid postprocess image descriptor", 502)
                seen.add(item["image_id"]); images.append({**item, "content_url": "/v1/postprocess-jobs/" + job["id"] + "/images/" + item["image_id"] + "/content"})
            if not images:
                raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Completed postprocess job has no images", 502)
            if job.get("cancel_requested"):
                job.update(state="cancelled", images=[], error=None, late_result={"state": "completed", "image_count": len(images)})
            else:
                job.update(state="completed", images=images, error=None)
        elif state == "cancelled": job.update(state="cancelled", error=None)
        elif state == "failed": job.update(state="failed", error={"code": "CORE_GENERATION_FAILED", "message": "Postprocess did not complete", "generation_error": remote.get("error")})
        elif state in {"queued", "submitting", "submitted", "running"}: job["state"] = "running" if state == "running" else "generation_pending"
        else: raise ApiError("CORE_GENERATION_PROTOCOL_ERROR", "Unknown Generation postprocess state", 502)
        self.save(job)

    async def content(self, job_id, image_id):
        job = self.get(job_id)
        image = next((item for item in job["images"] if item["image_id"] == image_id), None)
        if not image: raise ApiError("CORE_NOT_FOUND", "Postprocess image not found", 404)
        return job, image

    async def tick(self):
        rows = self.core.store.db.execute("SELECT document FROM postprocess_jobs WHERE state NOT IN ('completed','failed','cancelled') ORDER BY created_at,id").fetchall()
        for row in rows:
            job = json.loads(row[0])
            try:
                await self.advance(job)
            except ApiError as exc:
                current = self.get(job["id"])
                if exc.code == "CORE_GENERATION_UNAVAILABLE":
                    first = current.setdefault("unavailable_since", time.time())
                    if time.time() - first < OBSERVATION_SECONDS:
                        self.save(current)
                        continue
                if current["state"] not in TERMINAL:
                    code = "CORE_GENERATION_ACCEPTANCE_UNKNOWN" if exc.code == "CORE_GENERATION_UNAVAILABLE" else exc.code
                    current.update(state="failed", error={"code": code, "message": exc.message}); self.save(current)
            except Exception:
                current = self.get(job["id"])
                if current["state"] not in TERMINAL:
                    current.update(state="failed", error={"code": "CORE_INTERNAL_ERROR", "message": "Postprocess tracking failure"}); self.save(current)
