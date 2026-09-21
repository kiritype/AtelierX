"""Run an isolated subprocess GPU-recovery smoke for one real plan item.

Only Core, Generation and Validation subprocesses created by this script are
killed.  ComfyUI and LM Studio are read before a real run and are never killed,
restarted, or manually released by this harness.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import time
from urllib.parse import urlparse

import aiohttp
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_TASK = {"generated", "failed", "cancelled"}
TERMINAL_RUN = {"completed", "failed", "cancelled"}


def local_url(value, name):
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError(f"{name} must be an http localhost URL")
    return value.rstrip("/")


def read_json(path, name):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {name}: {path}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return result


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def safe(value):
    """Never put tokens or credentials in the report or raised HTTP context."""
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items()
                if not any(word in k.lower() for word in ("token", "key", "secret"))}
    if isinstance(value, list):
        return [safe(v) for v in value]
    return value


class OwnedProcesses:
    def __init__(self, artifact, environment):
        self.artifact, self.environment, self.items = artifact, environment, {}

    async def start(self, name, command):
        old = self.items.get(name)
        if old and old.returncode is None:
            raise RuntimeError(f"{name} child is already running")
        out = (self.artifact / f"{name}.stdout.log").open("ab")
        err = (self.artifact / f"{name}.stderr.log").open("ab")
        try:
            self.items[name] = await asyncio.create_subprocess_exec(
                *command, cwd=str(ROOT), env=self.environment, stdout=out, stderr=err)
        finally:
            out.close(); err.close()

    async def kill(self, name, why):
        process = self.items.get(name)
        if not process or process.returncode is not None:
            raise RuntimeError(f"test-owned {name} child is unavailable for {why}")
        process.kill()
        await asyncio.wait_for(process.wait(), 15)
        return process.pid

    async def cleanup(self):
        for process in self.items.values():
            if process.returncode is None:
                process.terminate()
        for process in self.items.values():
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 15)
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def wait_for(predicate, description, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(.25)
    raise TimeoutError(f"Timed out waiting for {description}")


async def main_async(args):
    comfy = local_url(args.comfy_url, "--comfy-url")
    gpu_path = (ROOT / args.gpu_config).resolve()
    validation_path = (ROOT / args.validation_config).resolve()
    gpu = read_json(gpu_path, "GPU config")
    supplied = read_json(validation_path, "Validation config")
    lmstudio = local_url(gpu.get("lmstudio_url", ""), "GPU config lmstudio_url")
    provider = dict(supplied.get("providers", {}).get("local-vision", {}))
    single = dict(supplied.get("profiles", {}).get("single-default", {}))
    if not provider or not single:
        raise RuntimeError("Validation config must contain local-vision and single-default")
    if not provider.get("shared_gpu") or provider.get("model") != gpu.get("model"):
        raise RuntimeError("GPU and Validation configs must use the same shared local-vision model")
    local_url(str(provider.get("url", "")), "Validation local-vision URL")
    if args.timeout < 60:
        raise ValueError("--timeout must be at least 60 seconds")

    artifact = Path(args.run_root).resolve() if args.run_root else ROOT / "artifacts" / "plan-gpu-recovery-rest" / time.strftime("%Y%m%d-%H%M%S")
    artifact.mkdir(parents=True, exist_ok=False)
    config, data = artifact / "config", artifact / "data"
    config.mkdir(); data.mkdir()
    ports = {"generation": free_port(), "validation": free_port(), "core": free_port()}
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    token = secrets.token_urlsafe(32)
    vision_key = provider.get("api_key") or os.environ.get(provider.get("api_key_env", ""), "")
    if not vision_key:
        raise RuntimeError("local-vision API credential is unavailable")
    environment = dict(os.environ, ATELIERX_SERVICE_TOKEN=token,
        ATELIERX_GENERATION_TOKEN=token, ATELIERX_VALIDATION_TOKEN=token,
        ATELIERX_GPU_RECOVERY_VISION_KEY=str(vision_key))
    group = {"profile_id": "recovery-group", "revision": 1, "consistency": True}
    child_provider = {k: v for k, v in provider.items() if k not in {"api_key", "api_key_env"}}
    child_provider["api_key_env"] = "ATELIERX_GPU_RECOVERY_VISION_KEY"
    child_config = {"core": {"url": urls["validation"], "generation_server_id": "generation-local"},
        "generation_sources": {"generation-local": {"url": urls["generation"], "token_env": "ATELIERX_SERVICE_TOKEN"}},
        "providers": {"local-vision": child_provider},
        "profiles": {single["profile_id"]: single, group["profile_id"]: group},
        "coordinator_url": urls["core"]}
    child_config_path = config / "validation.json"
    child_config_path.write_text(json.dumps(child_config, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"started_at": time.time(), "dry_run": args.dry_run, "ports": ports,
        "scope": "one isolated Anima 1024 -> UltraSharp 1536 plan item", "events": [], "restarts": [],
        "inputs": {"gpu_config": str(gpu_path), "validation_config": str(validation_path)}}
    def save():
        (artifact / "report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")

    children = OwnedProcesses(artifact, environment)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60),
                                     headers={"Authorization": "Bearer " + token}) as session:
        async def request(base, method, path, body=None, expected=200, key=None):
            headers = {"Idempotency-Key": key} if key else {}
            async with session.request(method, base + path, json=body, headers=headers) as response:
                try: value = await response.json()
                except aiohttp.ContentTypeError: value = {"response": await response.text()}
                if response.status != expected:
                    raise RuntimeError(f"{method} {path} HTTP {response.status}: {safe(value)}")
                return value
        async def health(url):
            try:
                async with session.get(url + "/health") as response:
                    return response.status == 200
            except aiohttp.ClientError:
                return False
        async def unavailable(url):
            return not await health(url)
        async def external(base, path, headers=None):
            async with session.get(base + path, headers=headers) as response:
                value = await response.json()
                if response.status != 200:
                    raise RuntimeError(f"{base}{path} returned HTTP {response.status}")
                return value

        commands = {
          "generation": [sys.executable, "-m", "atelierx.generation", "--port", str(ports["generation"]),
                         "--data-dir", str(data / "generation"), "--comfy-url", comfy, "--coordinator-url", urls["core"]],
          "validation": [sys.executable, "-m", "atelierx.validation", "--port", str(ports["validation"]),
                         "--data-dir", str(data / "validation"), "--config", str(child_config_path)],
          "core": [sys.executable, "-m", "atelierx.core", "--port", str(ports["core"]),
                   "--db", str(data / "core.sqlite3"), "--generation-url", urls["generation"],
                   "--validation-config", str(child_config_path), "--gpu-config", str(gpu_path)]}
        async def stop_child(name, reason):
            old_pid = await children.kill(name, reason)
            await wait_for(lambda: unavailable(urls[name]), name + " child port closure", 10)
            return old_pid
        async def start_child(name, old_pid):
            """Restore an owned child on its originally allocated port."""
            await children.start(name, commands[name])
            await wait_for(lambda: health(urls[name]), name + " restart", 30)
            assert children.items[name].pid != old_pid
        async def restart_child(name, reason):
            """Fault and restore one owned child on its originally allocated port."""
            old_pid = await stop_child(name, reason)
            await start_child(name, old_pid)
            return old_pid
        try:
            if not args.dry_run:
                queue = await external(comfy, "/queue")
                if queue.get("queue_running") or queue.get("queue_pending"):
                    raise RuntimeError("ComfyUI is busy; no test job was submitted")
                models = await external(lmstudio, "/api/v1/models",
                    {"Authorization": "Bearer " + str(gpu.get("api_key", "lm-studio"))})
                report["preflight"] = {"comfy_queue": queue,
                    "lmstudio_models": [{"model": x.get("key"), "loaded_instances": [
                        {k: i.get(k) for k in ("id", "identifier", "status")} for i in x.get("loaded_instances", [])]
                        } for x in models.get("models", [])]}
                save()
            for name in ("generation", "validation", "core"):
                await children.start(name, commands[name])
                await wait_for(lambda name=name: health(urls[name]), name + " health", 30)
            report["events"].append({"event": "isolated_subprocesses_ready", "names": list(commands)})
            save()
            settings = await request(urls["core"], "GET", "/v1/settings")
            await request(urls["core"], "PATCH", "/v1/settings",
                          {"revision": settings["revision"], "auto_regeneration_enabled": False, "max_auto_regenerations": 0})
            work = await request(urls["core"], "POST", "/v1/works", {"name": "GPU recovery smoke"}, 201)
            character = await request(urls["core"], "POST", "/v1/characters",
                {"name": "Adult test subject", "parent_id": work["id"], "negative_prompt": ""}, 201)
            outfit = await request(urls["core"], "POST", "/v1/outfits", {"name": "Recovery portrait", "parent_id": character["id"],
                "components": {"appearance": "adult woman, silver hair, blue eyes", "upper": "white shirt", "lower": "black trousers"}}, 201)
            group_record = await request(urls["core"], "POST", "/v1/groups", {"outfit_id": outfit["id"]}, 201)
            fragment = await request(urls["core"], "POST", "/v1/prompt-fragments",
                {"name": "One recovery frame", "body": "calm studio portrait, centered composition", "include": {"upper": True, "lower": True}}, 201)
            example = read_json(ROOT / "custom_nodes/atelierx_anima/examples/anima-preview.api.json", "Anima example")
            raw_inputs = example["prompt"]["1"]["inputs"]
            inputs = {k: v for k, v in raw_inputs.items() if k not in {"positive_prompt", "negative_prompt", "lora_stack", "width", "height"}}
            inputs["seed"] = args.seed
            plan = await request(urls["core"], "POST", "/v1/production-plans", {
                "group_id": group_record["id"], "fragments": [{"id": fragment["id"], "revision": fragment["revision"]}],
                "generation_inputs": inputs, "validation": {"provider_id": "local-vision", "profile_id": single["profile_id"]},
                "group_validation": {"provider_id": "local-vision", "profile_id": group["profile_id"]}}, 201, "recovery-plan")
            item = (await request(urls["core"], "GET", f"/v1/production-plans/{plan['id']}/items"))["items"][0]
            report["plan"] = {"id": plan["id"], "item_index": item["index"]}
            snap = item["snapshot"]
            assert (snap["generation_inputs"]["width"], snap["generation_inputs"]["height"]) == (1024, 1024)
            assert snap["postprocess"]["upscale"] == {"upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5}
            if args.dry_run:
                # Exercise actual Core plan validation/snapshot persistence
                # before restart, while intentionally never starting a task.
                await restart_child("generation", "dry-run Generation restart")
                await restart_child("core", "dry-run Core restart")
                restored_plan = await request(urls["core"], "GET", f"/v1/production-plans/{plan['id']}")
                restored_items = await request(urls["core"], "GET", f"/v1/production-plans/{plan['id']}/items")
                assert restored_plan["state"] == "draft" and len(restored_items["items"]) == 1
                report["plan"]["dry_run_state"] = restored_plan["state"]
                report["restarts"].append("dry-run Generation and Core fixed-port restarts verified")
                report["finished_at"] = time.time(); save()
                return artifact / "report.json"
            await request(urls["core"], "POST", f"/v1/production-plans/{plan['id']}/start", {"plan_hash": plan["plan_hash"]}, 202)

            async def tracked():
                current = (await request(urls["core"], "GET", f"/v1/production-plans/{plan['id']}/items"))["items"][0]
                if not current.get("task_id"): return None
                task = await request(urls["core"], "GET", f"/v1/tasks/{current['task_id']}")
                if not task.get("generation_job_id"): return None
                job = await request(urls["generation"], "GET", f"/v1/jobs/{task['generation_job_id']}")
                if job["state"] != "running": return None
                comfy_queue = await external(comfy, "/queue")
                running_ids = {entry[1] for entry in comfy_queue.get("queue_running", [])}
                if job["prompt_id"] not in running_ids:
                    return None
                gpu_state = await request(urls["core"], "GET", "/v1/gpu")
                owner = {"phase": "generation", "job_id": job["job_id"]}
                return (current, task, job, gpu_state, comfy_queue) if gpu_state["owner"] == owner else None
            _, task, job, before, observed_queue = await wait_for(tracked, "running persisted prompt and generation GPU owner", args.timeout)
            report["plan"]["task_id"] = task["id"]
            report["plan"]["generation_job_id"] = job["job_id"]
            report["events"].append({"event": "prompt_persisted", "task_id": task["id"], "job_id": job["job_id"],
                "prompt_id": job["prompt_id"], "job_state": job["state"], "comfy_queue": observed_queue,
                "gpu_owner": before["owner"]}); save()

            report["restarts"].append("Generation killed after persisted prompt id")
            old_generation = await stop_child("generation", "Generation recovery probe")
            old_core = await stop_child("core", "Core persisted-owner recovery probe")
            report["restarts"].append("Core killed while Generation remained unavailable")
            await start_child("core", old_core)
            after = await request(urls["core"], "GET", "/v1/gpu")
            assert after["owner"] == before["owner"], after
            report["events"].append({"event": "core_restart_preserved_gpu_owner", "gpu_owner": after["owner"]}); save()
            await start_child("generation", old_generation)

            async def generated():
                value = await request(urls["core"], "GET", f"/v1/tasks/{task['id']}")
                return value if value["state"] in TERMINAL_TASK else None
            task = await wait_for(generated, "generated plan task", args.timeout)
            assert task["state"] == "generated", task
            assert len(task["images"]) == 2, task
            png = next((x for x in task["images"] if x["media_type"] == "image/png"), None)
            assert png, task
            async with session.get(urls["core"] + f"/v1/images/{png['id']}/content") as response:
                assert response.status == 200
                png_data = await response.read()
            assert hashlib.sha256(png_data).hexdigest() == png["sha256"]
            image = Image.open(io.BytesIO(png_data)); image.load()
            assert image.size == (1536, 1536), image.size
            async def validated():
                runs = []
                for output in task["images"]:
                    rows = await request(urls["core"], "GET", f"/v1/images/{output['id']}/validations")
                    if not rows["items"] or rows["items"][0]["state"] not in TERMINAL_RUN:
                        return None
                    runs.append(rows["items"][0])
                return runs
            results = await wait_for(validated, "all automatic single VLM results", args.timeout)
            assert all(result["state"] == "completed" and result["outcome"] in {"passed", "failed"} for result in results), results
            report["generation"] = {"task_id": task["id"], "output_count": len(task["images"]),
                "png_sha256": png["sha256"], "png_size": list(image.size)}
            report["validation"] = [{"run_id": result["id"], "state": result["state"], "outcome": result["outcome"]} for result in results]
            # A one-item plan cannot establish a reference.  Do not infer or
            # auto-confirm one: explicitly cancel this test plan after its
            # generation/quality evidence has been retained.
            await request(urls["core"], "POST", f"/v1/production-plans/{plan['id']}/cancel", expected=202)
            async def cancelled_plan():
                value = await request(urls["core"], "GET", f"/v1/production-plans/{plan['id']}")
                return value if value["state"] in {"cancelled", "failed"} else None
            terminal_plan = await wait_for(cancelled_plan, "explicit test-plan cancellation", args.timeout)
            assert terminal_plan["state"] == "cancelled", terminal_plan
            report["plan"]["terminal_state"] = terminal_plan["state"]
            async def released():
                gpu_state = await request(urls["core"], "GET", "/v1/gpu")
                return gpu_state if gpu_state["owner"] is None and gpu_state["waiting"] == [] else None
            report["final_gpu"] = await wait_for(released, "GPU release", args.timeout)
            history = await external(comfy, "/history/" + job["prompt_id"])
            assert job["prompt_id"] in history, history
            recovered_job = await request(urls["generation"], "GET", f"/v1/jobs/{job['job_id']}")
            assert recovered_job["prompt_id"] == job["prompt_id"], recovered_job
            report["comfy_recovery"] = {"prompt_id": job["prompt_id"], "history_contains_prompt": True,
                "restarted_job_id": recovered_job["job_id"], "restarted_prompt_id": recovered_job["prompt_id"]}
            report["plan"]["final"] = await request(urls["core"], "GET", f"/v1/production-plans/{plan['id']}")
            report["plan"]["items"] = await request(urls["core"], "GET", f"/v1/production-plans/{plan['id']}/items")
            report["final_queue"] = await request(urls["core"], "GET", "/v1/queue?limit=200")
            assert all(row["state"] in {"generated", "completed", "failed", "cancelled"} for row in report["final_queue"]["items"])
            report["finished_at"] = time.time(); save()
            return artifact / "report.json"
        except Exception as exc:
            report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
            report["finished_at"] = time.time(); save()
            raise
        finally:
            await children.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--gpu-config", default=".atelierx/gpu-config.json")
    parser.add_argument("--validation-config", default=".atelierx/validation-coordinated-config.json")
    parser.add_argument("--seed", type=int, default=2026091321)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--dry-run", action="store_true", help="only launch and authenticate isolated child services")
    parser.add_argument("--confirm-exclusive-gpu", action="store_true",
                        help="required for real GPU work; independent GPU clients cannot be atomically excluded")
    args = parser.parse_args()
    if not args.dry_run and not args.confirm_exclusive_gpu:
        parser.error("--confirm-exclusive-gpu is required for a real GPU run")
    try:
        print(asyncio.run(main_async(args)), flush=True)
    except Exception as exc:
        raise SystemExit(f"GPU recovery smoke failed: {exc}") from exc


if __name__ == "__main__":
    main()
