"""Core-owned durable FIFO permission for a configured shared GPU.

Permissions never expire: a missing service must not cause concurrent inference.
"""
import asyncio
import json
import time

import aiohttp
from .common import ApiError, canonical


class GpuCoordinator:
    def __init__(self, store, config=None):
        self.store, self.config = store, config
        self.lock = asyncio.Lock()
        store.db.execute("CREATE TABLE IF NOT EXISTS gpu_state (id INTEGER PRIMARY KEY, document TEXT NOT NULL)")
        store.db.commit()

    def state(self):
        row = self.store.db.execute("SELECT document FROM gpu_state WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {"owner": None, "waiting": [], "blocked": None}

    def save(self, state):
        with self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO gpu_state VALUES(1,?)", (canonical(state),))

    async def prepare(self, session, phase):
        config = self.config
        async def request(method, url, **kwargs):
            async with session.request(method, url, **kwargs) as response:
                if response.status != 200:
                    raise ApiError("CORE_GPU_PREPARE_FAILED", "GPU runtime preparation failed", 503)
                raw = await response.read()
                return json.loads(raw) if raw else {}
        comfy = config["comfy_url"].rstrip("/")
        queue = await request("GET", comfy + "/queue")
        if queue["queue_running"] or queue["queue_pending"]:
            return False, "ComfyUI is busy"
        if phase == "generation":
            lm = config["lmstudio_url"].rstrip("/")
            headers = {"Authorization": "Bearer " + config.get("api_key", "lm-studio")}
            models = await request("GET", lm + "/api/v1/models", headers=headers)
            for model in models["models"]:
                instances = model.get("loaded_instances", [])
                if instances and model["key"] != config["model"]:
                    return False, "An unmanaged LM Studio model is loaded"
                if instances:
                    process = await asyncio.create_subprocess_exec(config.get("lms_executable", "lms"), "ps", "--json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, _ = await asyncio.wait_for(process.communicate(), 10)
                    if process.returncode:
                        return False, "LM Studio activity could not be checked"
                    activity = json.loads(stdout)
                    for instance in instances:
                        observed = next((item for item in activity if item.get("identifier") == instance["id"]), None)
                        if observed is None or observed.get("status") != "idle" or observed.get("queued", 0):
                            return False, "LM Studio is busy"
                for instance in instances:
                    await request("POST", lm + "/api/v1/models/unload", headers=headers, json={"instance_id": instance["id"]})
        # Clear cached generation models before switching or measuring headroom.
        await request("POST", comfy + "/free", json={"unload_models": True, "free_memory": True})
        minimum = config.get("minimum_free_mib", {}).get(phase, 18000)
        if phase in {"validation", "planner"}:
            lm = config["lmstudio_url"].rstrip("/")
            models = await request("GET", lm + "/api/v1/models", headers={"Authorization": "Bearer " + config.get("api_key", "lm-studio")})
            if any(m["key"] == config["model"] and m.get("loaded_instances") for m in models["models"]):
                minimum = config.get("resident_minimum_free_mib", 128)
        for _ in range(10):
            process = await asyncio.create_subprocess_exec("nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits", "-i", str(config.get("gpu_index", 0)), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await asyncio.wait_for(process.communicate(), 10)
            if process.returncode != 0:
                raise ApiError("CORE_GPU_TELEMETRY_FAILED", "GPU memory could not be checked", 503)
            if int(stdout.strip()) >= minimum:
                return True, None
            await asyncio.sleep(.5)
        return False, "Insufficient free GPU memory"

    async def acquire(self, session, phase, job_id):
        if not self.config:
            raise ApiError("CORE_GPU_UNCONFIGURED", "Shared GPU coordinator is not configured", 503)
        identity = {"phase": phase, "job_id": job_id}
        async with self.lock:
            state = self.state()
            if state["owner"] == identity:
                return {"granted": True}
            if identity not in state["waiting"]:
                state["waiting"].append(identity)
                self.save(state)
            if state["owner"] or state["waiting"][0] != identity:
                return {"granted": False, "reason": "Waiting for GPU owner or earlier request"}
            try:
                ready, reason = await self.prepare(session, phase)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, ApiError):
                ready, reason = False, "Runtime preparation unavailable; GPU permission withheld"
            state["blocked"] = reason
            if ready:
                state["owner"] = identity
                state["waiting"].pop(0)
            self.save(state)
            return {"granted": ready, "reason": reason}

    async def release(self, phase, job_id):
        identity = {"phase": phase, "job_id": job_id}
        async with self.lock:
            state = self.state()
            if state["owner"] == identity:
                state["owner"] = None
            state["waiting"] = [item for item in state["waiting"] if item != identity]
            self.save(state)
        return {"released": True}


async def permission(service, job, phase, release=False):
    try:
        return await _permission(service, job, phase, release)
    # A coordinator reply is an inter-service boundary.  A malformed success
    # response must be treated exactly like an unavailable coordinator: do not
    # grant or release based on an unparseable acknowledgement, and keep the
    # service worker alive to retry its durable state later.
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, AttributeError):
        return False


async def _permission(service, job, phase, release=False):
    url = getattr(service, "coordinator_url", None)
    if not url:
        return True
    if not release and not job.get("gpu_requested"):
        job["gpu_requested"] = True
        service.save(job)
    suffix = "release" if release else "acquire"
    async with service.session.post(url.rstrip("/") + "/v1/gpu/" + suffix,
                                    headers={"Authorization": "Bearer " + service.token},
                                    json={"phase": phase, "job_id": job["job_id"]}) as response:
        if response.status != 200:
            return False
        result = await response.json()
        # JSON numbers are truthy in Python, but only the protocol's literal
        # boolean acknowledgement may change durable GPU ownership state.
        success = result.get("released" if release else "granted") is True
        if release and success:
            job["gpu_requested"] = False
            service.save(job)
        return success
