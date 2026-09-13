"""First Generation REST slice: registered Anima node, durable jobs and PNGs.

ComfyUI is accessed only over HTTP; this process imports neither Torch nor nodes.
Run one Generation process per data directory/GPU. Core scheduling comes later.
"""
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
import time
import uuid

import aiohttp
from aiohttp import web
from .common import ApiError, ProcessLock, canonical
from .gpu import permission
from .queue_api import attach_queue_api
from .generation_pipeline import NODES as POSTPROCESS_NODES, build_anima_prompt, validate_pipeline

NODE = "AtelierXAnimaGenerate"
TERMINAL = {"completed", "failed", "cancelled"}
SERVICE = web.AppKey("generation", object)


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_inputs(value, schema):
    if not isinstance(value, dict):
        raise ApiError("GEN_INVALID_INPUT", "inputs must be an object")
    required = schema["input"]["required"]
    allowed = set(required) | {"loras"}
    if set(value) - allowed or set(required) - set(value):
        raise ApiError("GEN_INVALID_INPUT", "Missing or unknown Anima fields")
    result = dict(value)
    for name, definition in required.items():
        kind, options = definition[0], definition[1] if len(definition) > 1 else {}
        item = value[name]
        choices = kind if isinstance(kind, list) else options.get("options")
        if choices is not None and (not isinstance(item, str) or item not in choices):
            raise ApiError("GEN_INVALID_INPUT", f"{name} is not registered in ComfyUI")
        if kind == "STRING" and not isinstance(item, str):
            raise ApiError("GEN_INVALID_INPUT", f"{name} must be text")
        if kind in ("INT", "FLOAT"):
            valid_type = type(item) is int if kind == "INT" else type(item) in (int, float)
            if not valid_type or not math.isfinite(item):
                raise ApiError("GEN_INVALID_INPUT", f"{name} must be a finite {kind}")
            if item < options.get("min", -math.inf) or item > options.get("max", math.inf):
                raise ApiError("GEN_INVALID_INPUT", f"{name} is out of range")
    if not value["positive_prompt"].strip():
        raise ApiError("GEN_INVALID_INPUT", "positive_prompt must not be empty")
    if any(value[name] % 16 for name in ("width", "height")):
        raise ApiError("GEN_INVALID_INPUT", "Dimensions must be multiples of 16")
    loras = result.pop("loras", [])
    lora_schema = schema["input"].get("optional", {}).get("lora_stack", [None, {}])[1]
    available = lora_schema.get("atelierx_lora_stack", {}).get("options", [])
    if not isinstance(loras, list):
        raise ApiError("GEN_INVALID_INPUT", "loras must be an array")
    for entry in loras:
        if not isinstance(entry, dict) or set(entry) != {"name", "strength"}:
            raise ApiError("GEN_INVALID_INPUT", "Each LoRA requires name and strength")
        if not isinstance(entry["name"], str) or entry["name"] not in available:
            raise ApiError("GEN_INVALID_INPUT", "LoRA is not registered")
        strength = entry["strength"]
        if type(strength) not in (int, float) or not math.isfinite(strength) or not -100 <= strength <= 100:
            raise ApiError("GEN_INVALID_INPUT", "LoRA strength must be finite and within -100..100")
    result["lora_stack"] = canonical(loras)
    return result


class Generation:
    def __init__(self, directory, comfy_url, token, poll=1.0):
        self.directory = Path(directory)
        self.jobs_dir = self.directory / "jobs"
        self.images_dir = self.directory / "images"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.owner = ProcessLock(self.directory / "service.lock")
        self.comfy_url = comfy_url.rstrip("/")
        self.token = token
        self.poll = poll
        self.jobs = {}
        self.keys = {}
        self.lock = asyncio.Lock()
        for path in self.jobs_dir.glob("*.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            self.jobs[job["job_id"]] = job
            self.keys[job["idempotency_key"]] = job["job_id"]

    def save(self, job):
        if job.get("cancel_requested") and job["state"] in {"completed", "failed"}:
            job["late_error"] = job.get("error")
            job.update(state="cancelled", images=[], error=None)
        job["updated_at"] = time.time()
        atomic_json(self.jobs_dir / f'{job["job_id"]}.json', job)

    async def call(self, method, path, **kwargs):
        try:
            async with self.session.request(method, self.comfy_url + path, **kwargs) as response:
                if response.status >= 400:
                    raise ApiError("GEN_COMFY_REJECTED", f"ComfyUI returned HTTP {response.status}", 502)
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise ApiError("GEN_COMFY_UNAVAILABLE", "ComfyUI response unavailable", 503) from exc

    async def node_schema(self):
        result = await self.call("GET", f"/object_info/{NODE}")
        if NODE not in result:
            raise ApiError("GEN_NODE_UNAVAILABLE", "Anima node is not registered", 503)
        output = await self.call("GET", "/object_info/SaveImage")
        if "SaveImage" not in output:
            raise ApiError("GEN_NODE_UNAVAILABLE", "SaveImage output node is not registered", 503)
        return result[NODE]

    async def node_info(self):
        """Read the exact registration snapshot used to validate a job."""
        names = [NODE, "SaveImage", "LoraLoaderModelOnly"] + [node for nodes in POSTPROCESS_NODES.values() for node in nodes]
        values = await asyncio.gather(*(self.call("GET", f"/object_info/{name}") for name in names))
        return {name: value[name] for name, value in zip(names, values) if name in value}

    def public(self, job):
        result = {key: value for key, value in job.items() if key not in {"node_inputs", "idempotency_key", "fingerprint"}}
        result.setdefault("requested_postprocess", {})
        result.setdefault("postprocess", {})
        return result

    def lookup(self, job_id):
        if job_id not in self.jobs:
            raise ApiError("GEN_JOB_NOT_FOUND", "Job not found", 404)
        return self.jobs[job_id]

    def image_source(self, image_id):
        for job in self.jobs.values():
            for image in job.get("images", []):
                if image["image_id"] == image_id:
                    suffix = image["media_type"].split("/")[-1]
                    path = self.images_dir / f"{image_id}.{suffix}"
                    if not path.is_file(): raise ApiError("GEN_OUTPUT_MISSING", "Stored image is missing", 404)
                    return job, image, path
        raise ApiError("GEN_IMAGE_NOT_FOUND", "Image not found", 404)

    async def submit_independent(self, key, image_id, postprocess):
        if not key or len(key) > 200:
            raise ApiError("GEN_INVALID_KEY", "Idempotency-Key (1..200 characters) is required")
        fingerprint = hashlib.sha256(canonical({"kind": "postprocess", "image_id": image_id, "postprocess": postprocess}).encode()).hexdigest()
        async with self.lock:
            if key in self.keys:
                job = self.jobs[self.keys[key]]
                if job["fingerprint"] != fingerprint:
                    raise ApiError("GEN_IDEMPOTENCY_CONFLICT", "Key was used with different input", 409)
                return job, False
            source, image, path = self.image_source(image_id)
            if not source.get("node_inputs"):
                raise ApiError("GEN_POSTPROCESS_CONTEXT_MISSING", "Source image has no preserved Anima context", 409)
            info = await self.node_info()
            loader = await self.call("GET", "/object_info/LoadImage")
            if "LoadImage" not in loader:
                raise ApiError("GEN_NODE_UNAVAILABLE", "LoadImage is not registered", 503)
            pipeline = validate_pipeline(postprocess, info, bool(json.loads(source["node_inputs"].get("lora_stack", "[]"))))
            if not pipeline:
                raise ApiError("GEN_INVALID_POSTPROCESS", "At least one postprocess stage is required")
            if "detailer" in pipeline:
                for node, field, input_name in (("UNETLoader", "unet_name", "diffusion_model"), ("CLIPLoader", "clip_name", "text_encoder"), ("VAELoader", "vae_name", "vae")):
                    if source["node_inputs"].get(input_name) not in self._options(info[node], field):
                        raise ApiError("GEN_INVALID_POSTPROCESS", f"detailer {input_name} is not registered for {node}")
            job_id = str(uuid.uuid4())
            job = dict(job_id=job_id, prompt_id=job_id, kind="postprocess", state="queued", created_at=time.time(),
                       inputs=json.loads(canonical(source["inputs"])), node_inputs=json.loads(canonical(source["node_inputs"])),
                       source_image_id=image_id, source_sha256=image["sha256"], source_media_type=image["media_type"],
                       requested_postprocess=postprocess, postprocess=pipeline, fingerprint=fingerprint,
                       idempotency_key=key, images=[], error=None)
            self.save(job)
            self.jobs[job_id] = job
            self.keys[key] = job_id
            return job, True

    async def submit(self, key, inputs, postprocess=None):
        if not key or len(key) > 200:
            raise ApiError("GEN_INVALID_KEY", "Idempotency-Key (1..200 characters) is required")
        try:
            fingerprint_source = inputs if not postprocess else {"inputs": inputs, "postprocess": postprocess}
            fingerprint = hashlib.sha256(canonical(fingerprint_source).encode()).hexdigest()
        except (TypeError, ValueError):
            raise ApiError("GEN_INVALID_INPUT", "Input must be finite JSON")
        async with self.lock:
            if key in self.keys:
                job = self.jobs[self.keys[key]]
                if job["fingerprint"] != fingerprint:
                    raise ApiError("GEN_IDEMPOTENCY_CONFLICT", "Key was used with different input", 409)
                return job, False
            info = await self.node_info()
            if NODE not in info:
                raise ApiError("GEN_NODE_UNAVAILABLE", "Anima node is not registered", 503)
            node_inputs = validate_inputs(inputs, info[NODE])
            pipeline = validate_pipeline(postprocess, info, bool(json.loads(node_inputs["lora_stack"])))
            if "detailer" in pipeline:
                loaders = (("UNETLoader", "unet_name", "diffusion_model"), ("CLIPLoader", "clip_name", "text_encoder"), ("VAELoader", "vae_name", "vae"))
                for node, field, input_name in loaders:
                    if node_inputs[input_name] not in self._options(info[node], field):
                        raise ApiError("GEN_INVALID_POSTPROCESS", f"detailer {input_name} is not registered for {node}")
            job_id = str(uuid.uuid4())
            job = dict(job_id=job_id, prompt_id=job_id, state="queued", created_at=time.time(),
                       inputs=inputs, requested_postprocess=postprocess or {}, postprocess=pipeline, node_inputs=node_inputs, fingerprint=fingerprint,
                       idempotency_key=key, images=[], error=None)
            self.save(job)
            self.jobs[job_id] = job
            self.keys[key] = job_id
            return job, True

    @staticmethod
    def _options(schema, field):
        item = schema.get("input", {}).get("required", {}).get(field, [None, {}])
        if not isinstance(item, list) or not item:
            return []
        if isinstance(item[0], list):
            return item[0]
        return item[1].get("options", []) if len(item) > 1 and isinstance(item[1], dict) else []

    async def capture(self, job, record):
        status = record.get("status", {})
        if status.get("completed") or any(name in {"execution_start", "execution_cached", "execution_error"} for name, _ in status.get("messages", [])):
            job["execution_started"] = True
            self.save(job)
        if status.get("status_str") == "error":
            failures = [data for name, data in status.get("messages", []) if name == "execution_error"]
            stage = failures[-1].get("node_id") if failures else None
            raise ApiError("GEN_EXECUTION_FAILED", f"ComfyUI execution failed at node {stage}", 502)
        if not status.get("completed"):
            return False
        output_node = str(job.get("output_node", "2"))
        output_data = record.get("outputs", {}).get(output_node, {})
        outputs = output_data.get("atelierx_files") or output_data.get("images", [])
        if not outputs:
            raise ApiError("GEN_OUTPUT_MISSING", "Completed job has no saved image", 502)
        images = []
        for index, descriptor in enumerate(outputs):
            image_id = f'{job["job_id"]}-{index}'
            declared = descriptor.get("format", "png").lower()
            if declared not in {"png", "webp"}:
                raise ApiError("GEN_OUTPUT_INVALID", "Output format is not PNG or WebP", 502)
            path = self.images_dir / f"{image_id}.{declared}"
            tmp = path.with_suffix(".part")
            digest, size, prefix = hashlib.sha256(), 0, b""
            async with self.session.get(self.comfy_url + "/view", params=descriptor) as response:
                if response.status != 200:
                    raise ApiError("GEN_OUTPUT_UNAVAILABLE", "Cannot retrieve ComfyUI output", 502)
                with tmp.open("wb") as stream:
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > 128 * 1024 * 1024:
                            raise ApiError("GEN_OUTPUT_TOO_LARGE", "Output exceeds 128 MiB", 502)
                        prefix = (prefix + chunk)[:12]
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
            valid = prefix.startswith(b"\x89PNG\r\n\x1a\n") if declared == "png" else prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
            if not valid:
                raise ApiError("GEN_OUTPUT_INVALID", f"Output is not {declared.upper()}", 502)
            tmp.replace(path)
            images.append(dict(image_id=image_id, sha256=digest.hexdigest(), bytes=size,
                               url=f"/v1/images/{image_id}", media_type=f"image/{declared}"))
        job.update(state="completed", images=images, error=None)
        self.save(job)
        return True

    async def run_job(self, job):
        # Submitted IDs are persisted before the only POST. Recovery never reposts.
        if job["state"] == "queued":
            if not await permission(self, job, "generation"):
                return
            if job["state"] in TERMINAL:
                return
            queue = await self.call("GET", "/queue")
            if queue["queue_running"] or queue["queue_pending"]:
                return
            if not job.get("source_image_id"):
                await self.node_schema()
            job["state"] = "submitting"
            self.save(job)
            prompt, output_node = build_anima_prompt(job["node_inputs"], job.get("postprocess", {}), job["job_id"])
            if job.get("source_image_id"):
                _, image, path = self.image_source(job["source_image_id"])
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != job["source_sha256"]:
                    raise ApiError("GEN_IMAGE_INTEGRITY", "Source image changed before postprocessing", 422)
                form = aiohttp.FormData()
                extension = image["media_type"].split("/")[-1]
                filename = f"atelierx-{job['job_id']}.{extension}"
                form.add_field("image", data, filename=filename, content_type=image["media_type"])
                form.add_field("overwrite", "false")
                uploaded = await self.call("POST", "/upload/image", data=form)
                name = uploaded.get("name")
                subfolder = uploaded.get("subfolder", "")
                if name != filename or subfolder or uploaded.get("type", "input") != "input":
                    raise ApiError("GEN_COMFY_REJECTED", "ComfyUI returned unexpected uploaded image location", 502)
                prompt["1"] = {"class_type": "LoadImage", "inputs": {"image": name}}
            job["output_node"] = output_node
            self.save(job)
            try:
                result = await self.call("POST", "/prompt", json={
                    "prompt": prompt, "prompt_id": job["prompt_id"], "client_id": "atelierx-generation"})
                if result.get("prompt_id") != job["prompt_id"]:
                    raise ApiError("GEN_PROTOCOL_ERROR", "ComfyUI did not preserve prompt_id", 502)
            except ApiError as exc:
                if exc.code != "GEN_COMFY_UNAVAILABLE":
                    raise
                # Acceptance may have happened. Only observe the known ID.
            job["state"] = "submitted"
            self.save(job)
        record = (await self.call("GET", f'/history/{job["prompt_id"]}')).get(job["prompt_id"])
        if record:
            await self.capture(job, record)
            return
        queue = await self.call("GET", "/queue")
        running = {entry[1] for entry in queue["queue_running"]}
        pending = {entry[1] for entry in queue["queue_pending"]}
        if job["prompt_id"] in running | pending:
            state = "running" if job["prompt_id"] in running else "submitted"
            if state == "running":
                job["execution_started"] = True
                self.save(job)
            if job["state"] != state:
                job["state"] = state
                self.save(job)
            return
        # History could have been written between history and queue reads.
        record = (await self.call("GET", f'/history/{job["prompt_id"]}')).get(job["prompt_id"])
        if record:
            await self.capture(job, record)
            return
        raise ApiError("GEN_EXECUTION_UNKNOWN", "Job absent from ComfyUI history and queue; no automatic resubmission", 502)

    async def worker(self):
        while True:
            for done in list(self.jobs.values()):
                if done["state"] in TERMINAL and done.get("gpu_requested") and (done.get("error") or done.get("late_error") or {}).get("code") != "GEN_EXECUTION_UNKNOWN":
                    try: await permission(self, done, "generation", release=True)
                    except (aiohttp.ClientError, asyncio.TimeoutError): pass
            candidates = sorted((j for j in self.jobs.values() if j["state"] not in TERMINAL),
                                key=lambda j: j["created_at"])
            if candidates:
                job = candidates[0]
                try:
                    await self.run_job(job)
                except ApiError as exc:
                    if exc.code == "GEN_COMFY_UNAVAILABLE":
                        # Keep tracking, without sending generation again.
                        pass
                    else:
                        job.update(state="failed", error={"code": exc.code, "message": exc.message})
                        self.save(job)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                except Exception:
                    logging.exception("Job %s failed", job["job_id"])
                    job.update(state="failed", error={"code": "GEN_INTERNAL_ERROR", "message": "Generation internal failure"})
                    self.save(job)
            await asyncio.sleep(self.poll)


@web.middleware
async def errors(request, handler):
    service = request.app[SERVICE]
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied.encode(), ("Bearer " + service.token).encode()):
        return web.json_response({"error": {"code": "GEN_UNAUTHORIZED", "message": "Bearer token required"}}, status=401)
    try:
        return await handler(request)
    except ApiError as exc:
        return web.json_response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": {"code": "GEN_INVALID_JSON", "message": "Invalid JSON"}}, status=400)


def create_app(directory, comfy_url, token, poll=1.0, coordinator_url=None):
    if not token:
        raise ValueError("ATELIERX_SERVICE_TOKEN must be set")
    app = web.Application(middlewares=[errors], client_max_size=2 * 1024 * 1024)
    service = Generation(directory, comfy_url, token, poll)
    service.coordinator_url = coordinator_url
    attach_queue_api(app, lambda: [service.public(job) for job in service.jobs.values()])
    app[SERVICE] = service

    async def lifecycle(app):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            service.session = session
            worker = asyncio.create_task(service.worker())
            yield
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        service.owner.close()
    app.cleanup_ctx.append(lifecycle)

    async def health(request):
        return web.json_response({"service": "generation", "status": "ok"})

    async def nodes(request):
        info = await service.node_info()
        anima = info.get(NODE)
        if not anima:
            raise ApiError("GEN_NODE_UNAVAILABLE", "Anima node is not registered", 503)
        post = []
        for stage, required in POSTPROCESS_NODES.items():
            registered = all(node in info for node in required)
            ready, reason = registered, None
            if not registered:
                reason = "Required ComfyUI node is not registered"
            elif stage == "upscale":
                models = service._options(info["AtelierXUpscale"], "upscale_model")
                ready = bool(models)
                if not ready:
                    reason = "No upscale model is registered in ComfyUI"
            post.append({"id": stage, "class_types": list(required), "registered": registered,
                         "ready": ready, "api_supported": True, "reason": reason})
        return web.json_response({"nodes": [{"id": "anima", "class_type": NODE, "registered": True, "schema": anima,
                                             "scope": "image generation and ordered multi-LoRA; presets not implemented"}], "postprocess": post})

    async def submit(request):
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) - {"inputs", "postprocess"} or "inputs" not in payload:
            raise ApiError("GEN_INVALID_INPUT", "Body must contain inputs and optional postprocess")
        job, created = await service.submit(request.headers.get("Idempotency-Key"), payload["inputs"], payload.get("postprocess"))
        return web.json_response(service.public(job), status=202 if created else 200,
                                 headers={"Location": f'/v1/jobs/{job["job_id"]}'})

    async def independent_postprocess(request):
        payload=await request.json()
        if not isinstance(payload,dict) or set(payload)!={"postprocess"} or not isinstance(payload["postprocess"],dict):
            raise ApiError("GEN_INVALID_INPUT", "Body must contain only postprocess")
        job,created=await service.submit_independent(request.headers.get("Idempotency-Key"), request.match_info["image_id"], payload["postprocess"])
        return web.json_response(service.public(job), status=202 if created else 200, headers={"Location": f'/v1/jobs/{job["job_id"]}'})

    async def get_job(request):
        return web.json_response(service.public(service.lookup(request.match_info["job_id"])))

    async def by_key(request):
        key = request.headers.get("Idempotency-Key")
        if key not in service.keys:
            raise ApiError("GEN_JOB_NOT_FOUND", "Key not found", 404)
        return web.json_response(service.public(service.lookup(service.keys[key])))

    async def image(request):
        image_id = request.match_info["image_id"]
        for job in service.jobs.values():
            for item in job["images"]:
                if item["image_id"] == image_id:
                    suffix = item.get("media_type", "image/png").split("/", 1)[-1]
                    path = service.images_dir / f"{image_id}.{suffix}"
                    if not path.is_file():
                        raise ApiError("GEN_OUTPUT_MISSING", "Stored image is missing", 404)
                    return web.FileResponse(path, headers={"Content-Type": item.get("media_type", "image/png")})
        raise ApiError("GEN_IMAGE_NOT_FOUND", "Image not found", 404)

    async def cancel(request):
        job = service.lookup(request.match_info["job_id"])
        if job["state"] not in TERMINAL:
            job["cancel_requested"] = True
            if job["state"] == "queued": job["state"] = "cancelled"
            service.save(job)
        return web.json_response(service.public(job), status=200 if job["state"] in TERMINAL else 202)

    app.add_routes([web.post("/v1/jobs/{job_id}/cancel", cancel), web.get("/health", health), web.get("/v1/nodes", nodes),
                    web.post("/v1/nodes/anima/jobs", submit), web.post("/v1/images/{image_id}/postprocess-jobs", independent_postprocess), web.get("/v1/jobs/by-key", by_key),
                    web.get("/v1/jobs/{job_id}", get_job), web.get("/v1/images/{image_id}", image)])
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8189)
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--data-dir", default=".atelierx/generation")
    parser.add_argument("--coordinator-url")
    args = parser.parse_args()
    web.run_app(create_app(args.data_dir, args.comfy_url, os.environ.get("ATELIERX_SERVICE_TOKEN"), coordinator_url=args.coordinator_url),
                host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
