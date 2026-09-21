"""Operator-run Core-owned independent postprocess integration harness.

The source is an archived integration artifact, never a user data directory.
Before a live run this script copies its Core SQLite database and Generation
job/image state into a new artifact directory.  The copied SQLite fixture has
only its saved Generation endpoint remapped to the isolated service address.
It calls the new Core image-ID API only after the isolated services
are running.  Real ComfyUI work requires both explicit live flags.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from PIL import Image

from atelierx.core import create_app as core_app
from atelierx.generation import SERVICE as GENERATION_SERVICE
from atelierx.generation import create_app as generation_app


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "artifacts" / "backend-pipeline-rest" / "20260913-042429"


def local_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"{label} must be an http localhost URL")
    return value.rstrip("/")


def source_image(source: Path, requested: str | None):
    database = source / "core.sqlite3"
    generation = source / "generation"
    if not database.is_file() or not (generation / "jobs").is_dir() or not (generation / "images").is_dir():
        raise ValueError("source must contain core.sqlite3 and generation/jobs plus generation/images")
    with sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True) as connection:
        records = [json.loads(row[0]) for row in connection.execute("SELECT document FROM images")]
    candidates = [record for record in records if record.get("media_type") == "image/png"]
    selected = next((record for record in candidates if record["id"] == requested), None) if requested else (candidates[0] if candidates else None)
    if not selected:
        raise ValueError("requested source Core PNG image was not found")
    image_id = selected["generation_image_id"]
    path = generation / "images" / (image_id + ".png")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != selected["sha256"]:
        raise ValueError("archived Generation image does not match Core metadata")
    job_path = generation / "jobs" / (selected["generation_job_id"] + ".json")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job.get("state") != "completed" or not job.get("node_inputs"):
        raise ValueError("source Generation job must be completed with preserved Anima context")
    return selected, path


def assert_terminal_fixture(source: Path):
    terminal = {"generated", "completed", "failed", "cancelled", "insufficient_images", "awaiting_reference_confirmation"}
    with sqlite3.connect("file:" + str(source / "core.sqlite3") + "?mode=ro", uri=True) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in {"tasks", "validation_runs", "group_batches", "production_plans", "standalone_jobs", "postprocess_jobs", "regeneration_cycles"} & tables:
            for row in connection.execute("SELECT document FROM " + table):
                state = json.loads(row[0]).get("state")
                if state not in terminal:
                    raise ValueError(f"archived {table} fixture contains nonterminal state {state!r}")
    for path in (source / "generation" / "jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("state") not in {"completed", "failed", "cancelled"}:
            raise ValueError(f"archived Generation job {path.name} is not terminal")


def copy_fixture(source: Path, destination: Path, archived_endpoint: str, generation_endpoint: str, selected_generation_job_id: str):
    # Fixture-only endpoint remap is the sole direct database change. It keeps
    # immutable task context intact while making copied records address the new
    # isolated Generation server; no user database is ever opened for writing.
    with sqlite3.connect("file:" + str(source / "core.sqlite3") + "?mode=ro", uri=True) as origin, sqlite3.connect(destination / "core.sqlite3") as target:
        origin.backup(target)
    with sqlite3.connect(destination / "core.sqlite3") as connection:
        for rowid, raw in connection.execute("SELECT rowid,document FROM tasks"):
            task = json.loads(raw)
            snapshot = task.get("snapshot", {})
            if snapshot.get("generation_endpoint") == archived_endpoint:
                snapshot["generation_endpoint"] = generation_endpoint
                connection.execute("UPDATE tasks SET document=? WHERE rowid=?", (json.dumps(task, ensure_ascii=False, separators=(",", ":")), rowid))
    shutil.copytree(source / "generation", destination / "generation")
    for path in (destination / "generation" / "jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        # No archived job may contact the pilot coordinator on startup.
        job["gpu_requested"] = False
        path.write_text(json.dumps(job, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def reserve_local_endpoint():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


async def start(app, listen_url=None):
    runner = web.AppRunner(app)
    await runner.setup()
    parsed = urlparse(listen_url) if listen_url else None
    await web.TCPSite(runner, "127.0.0.1", parsed.port if parsed else 0).start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


async def call(client, method, url, path, expected, body=None, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    async with client.request(method, url + path, json=body, headers=headers) as response:
        value = await response.json()
    if response.status != expected:
        raise RuntimeError(f"{method} {path} returned {response.status}: {value}")
    return value


async def wait_for(client, url, job_id, timeout):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await call(client, "GET", url, "/v1/postprocess-jobs/" + job_id, 200)
        if last.get("state") in {"completed", "failed", "cancelled"}:
            return last
        await asyncio.sleep(.5)
    raise TimeoutError(f"postprocess job {job_id} did not finish: {last}")


async def wait_for_release(client, generation_url, generation_job_id, timeout):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await call(client, "GET", generation_url, "/v1/jobs/" + generation_job_id, 200)
        if last.get("gpu_released") is True or last.get("gpu_requested") is False:
            return last
        await asyncio.sleep(.5)
    raise TimeoutError(f"GPU release acknowledgement was not observed for {generation_job_id}: {last}")


def inspect_bytes(data: bytes):
    import io
    image = Image.open(io.BytesIO(data))
    image.load()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "size": list(image.size), "mode": image.mode}


async def run(args):
    source = Path(args.source).resolve()
    original, source_path = source_image(source, args.source_image_id)
    assert_terminal_fixture(source)
    source_job = json.loads((source / "generation" / "jobs" / (original["generation_job_id"] + ".json")).read_text(encoding="utf-8"))
    archived_endpoint = source_job.get("generation_endpoint")
    if not isinstance(archived_endpoint, str):
        with sqlite3.connect("file:" + str(source / "core.sqlite3") + "?mode=ro", uri=True) as connection:
            task = json.loads(connection.execute("SELECT document FROM tasks WHERE id=?", (original["task_id"],)).fetchone()[0])
        archived_endpoint = task["snapshot"].get("generation_endpoint")
    archived_endpoint = local_url(archived_endpoint, "archived Generation endpoint")
    destination = Path(args.output_dir) if args.output_dir else ROOT / "artifacts" / "core-independent-postprocess" / time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=False)
    report = {"started_at": time.time(), "mode": "dry-run" if args.dry_run else "live",
              "fixture": {"source": str(source), "copy_strategy": "SQLite backup and archived Generation copy; fixture-only task endpoint remap and archived GPU flags cleared",
                          "core_image_id": original["id"], "generation_image_id": original["generation_image_id"],
                          "source_sha256": original["sha256"], "source_path": str(source_path),
                          "archived_generation_endpoint": archived_endpoint}}
    if args.dry_run:
        report["finished_at"] = time.time()
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination / "report.json"
    if not args.run_live or not args.confirm_exclusive_gpu:
        raise ValueError("live work requires --run-live and --confirm-exclusive-gpu")
    token = os.environ.get("ATELIERX_SERVICE_TOKEN")
    if not token:
        raise ValueError("ATELIERX_SERVICE_TOKEN is required for the isolated Generation-to-coordinator connection")
    comfy_url = local_url(args.comfy_url, "--comfy-url")
    coordinator_url = local_url(args.coordinator_url, "--coordinator-url")
    # The browser-facing isolated Core gets a random token.  It uses the
    # process-local Generation token only for backend-to-backend requests.
    core_token = secrets.token_urlsafe(32)
    runners = []
    report["requested_postprocess"] = {"upscale": {"upscale_model": "4x-UltraSharp.safetensors", "scale": args.scale},
                                       "encode": {"webp_enabled": True, "webp_quality": 90}}
    try:
        generation_dir = destination / "generation"
        generation_url = reserve_local_endpoint()
        copy_fixture(source, destination, archived_endpoint, generation_url, original["generation_job_id"])
        generation = generation_app(generation_dir, comfy_url, token, .2)
        generation[GENERATION_SERVICE].coordinator_url = coordinator_url
        runner, generation_url = await start(generation, generation_url); runners.append(runner)
        core = core_app(destination / "core.sqlite3", generation_url, core_token, generation_token=token, poll=.2)
        runner, core_url = await start(core); runners.append(runner)
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + core_token}) as core_client, aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as gen_client:
            # Read-only preflight; the coordinator remains responsible for the
            # final queue/model/memory check at acquire time.
            async with gen_client.get(comfy_url + "/queue") as response:
                queue = await response.json()
            async with gen_client.get(coordinator_url + "/v1/gpu") as response:
                gpu = await response.json()
            report["preflight"] = {"comfy_queue": {"running": queue.get("queue_running"), "pending": queue.get("queue_pending")},
                                   "pilot_gpu": gpu}
            if queue.get("queue_running") or queue.get("queue_pending"):
                raise RuntimeError("ComfyUI is busy; no postprocess job submitted")
            async with core_client.get(core_url + f"/v1/images/{original['id']}/content") as response:
                if response.status != 200: raise RuntimeError("source Core image content is unavailable")
                source_before = await response.read()
            report["source_before"] = inspect_bytes(source_before)
            group_before = await call(core_client, "GET", core_url, "/v1/groups/" + original["group_id"], 200)
            if report["source_before"]["sha256"] != original["sha256"]:
                raise RuntimeError("isolated Core content differs from archived source digest")
            body = {"postprocess": report["requested_postprocess"]}
            key = "core-independent-upscale-encode"
            submitted = await call(core_client, "POST", core_url, f"/v1/images/{original['id']}/postprocess-jobs", 202, body, key)
            job_id = submitted.get("id", submitted.get("job_id"))
            if not isinstance(job_id, str): raise RuntimeError("Core did not return a postprocess job id")
            duplicate = await call(core_client, "POST", core_url, f"/v1/images/{original['id']}/postprocess-jobs", 200, body, key)
            if duplicate.get("id", duplicate.get("job_id")) != job_id: raise RuntimeError("idempotency returned a different Core postprocess job")
            completed = await wait_for(core_client, core_url, job_id, args.timeout)
            if completed.get("state") != "completed": raise RuntimeError(f"postprocess did not complete: {completed}")
            generation_job_id = completed.get("generation_job_id")
            if not isinstance(generation_job_id, str): raise RuntimeError("Core job has no Generation job id")
            report["gpu_release"] = await wait_for_release(gen_client, generation_url, generation_job_id, args.release_timeout)
            outputs = completed.get("images", [])
            if {item.get("media_type") for item in outputs} != {"image/png", "image/webp"}: raise RuntimeError("upscale+encode must produce one PNG and one WebP")
            report["job"] = completed
            report["outputs"] = []
            for image in outputs:
                async with core_client.get(core_url + f"/v1/postprocess-jobs/{job_id}/images/{image['image_id']}/content") as response:
                    if response.status != 200: raise RuntimeError("postprocess Core image content is unavailable")
                    data = await response.read()
                checked = inspect_bytes(data)
                if checked["sha256"] != image.get("sha256"): raise RuntimeError("Core postprocess content digest mismatch")
                expected_size = [int(report["source_before"]["size"][0] * args.scale + .5), int(report["source_before"]["size"][1] * args.scale + .5)]
                if checked["size"] != expected_size: raise RuntimeError(f"upscale size {checked['size']} differs from {expected_size}")
                report["outputs"].append({"image_id": image["image_id"], "media_type": image["media_type"], **checked})
            async with core_client.get(core_url + f"/v1/images/{original['id']}/content") as response:
                source_after = await response.read()
            report["source_after"] = inspect_bytes(source_after)
            if report["source_after"] != report["source_before"]: raise RuntimeError("source Core image changed after postprocess")
            group_after = await call(core_client, "GET", core_url, "/v1/groups/" + original["group_id"], 200)
            if group_after != group_before: raise RuntimeError("source group changed after postprocess")
            report["source_group_unchanged"] = True
        # Persistence verification touches only copied state.  Stop and restart
        # both isolated services after the per-job GPU release acknowledgement.
        for runner in reversed(runners): await runner.cleanup()
        runners.clear()
        generation = generation_app(destination / "generation", comfy_url, token, .2)
        generation[GENERATION_SERVICE].coordinator_url = coordinator_url
        runner, generation_url = await start(generation, generation_url); runners.append(runner)
        core = core_app(destination / "core.sqlite3", generation_url, core_token, generation_token=token, poll=.2)
        runner, core_url = await start(core); runners.append(runner)
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + core_token}) as client:
            restored = await call(client, "GET", core_url, "/v1/postprocess-jobs/" + job_id, 200)
        if restored != completed: raise RuntimeError("isolated restart did not preserve Core postprocess job")
        report["restart_persistence"] = True
        report["isolated_core_url"] = core_url if args.keep_alive else None
        token_path = destination / "isolated-core-token.txt"
        if args.keep_alive:
            token_path.write_text(core_token, encoding="utf-8")
            report["isolated_core_token_file"] = str(token_path)
        report["finished_at"] = time.time()
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.keep_alive:
            stop_path = destination / "stop"
            print(core_url, flush=True)
            print(token_path, flush=True)
            while not stop_path.exists():
                await asyncio.sleep(1)
        return destination / "report.json"
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        report["finished_at"] = time.time()
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        for runner in reversed(runners):
            await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--source-image-id")
    parser.add_argument("--output-dir")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--coordinator-url", default="http://127.0.0.1:8190")
    parser.add_argument("--scale", type=float, default=1.1)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--release-timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--confirm-exclusive-gpu", action="store_true")
    parser.add_argument("--keep-alive", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.run_live:
        parser.error("choose --dry-run or --run-live")
    if args.dry_run and args.run_live:
        parser.error("--dry-run and --run-live cannot be combined")
    if not 1 <= args.scale <= 4 or args.timeout < 1 or args.release_timeout < 1:
        parser.error("scale must be 1..4 and timeouts must be positive")
    print(asyncio.run(run(args)), flush=True)


if __name__ == "__main__":
    main()
