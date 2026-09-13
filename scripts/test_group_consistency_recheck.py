"""Recheck an existing artifact's group consistency without generating images.

By default this restores isolated Generation, Validation, and Core services on
the artifact's saved localhost endpoints and SQLite database. It creates no
generation request, entity, image, or upload. `--core-url` instead uses an
already restarted Core service.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from atelierx.core import create_app as core_app
from atelierx.generation import SERVICE as GEN_SERVICE, create_app as generation_app
from atelierx.validation import SERVICE as VAL_SERVICE, create_app as validation_app


def local_url(value, name):
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"{name} must be a localhost http URL")
    return value.rstrip("/")


async def start(app, saved_url):
    parsed = urlparse(local_url(saved_url, "saved service endpoint"))
    if parsed.path not in {"", "/"} or parsed.port is None:
        raise ValueError("saved service endpoint needs a localhost port and no path")
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", parsed.port).start()
    return runner, f"http://127.0.0.1:{parsed.port}"


def source_run(report):
    run = report.get("group_run")
    if not isinstance(run, dict) or not isinstance(run.get("request"), dict):
        raise ValueError("artifact report has no completed group_run request")
    request = run["request"]
    needed = {"group_id", "reference_revision", "targets", "profile", "provider"}
    if not needed <= set(request) or not isinstance(request["targets"], list):
        raise ValueError("artifact group_run does not contain a reusable frozen request")
    targets = [item.get("ref") for item in request["targets"]]
    if not targets or any(not isinstance(item, str) for item in targets):
        raise ValueError("artifact group_run has no reusable target image IDs")
    return run, request, targets


def saved_endpoints(report):
    batch = report.get("batch_accepted")
    if not isinstance(batch, dict) or not batch.get("items") or not isinstance(batch.get("group_validation_frozen"), dict):
        raise ValueError("artifact report has no batch endpoint snapshots")
    generation_url = batch["items"][0].get("snapshot", {}).get("generation_endpoint")
    validation_url = batch["group_validation_frozen"].get("endpoint")
    return local_url(generation_url, "saved generation endpoint"), local_url(validation_url, "saved validation endpoint")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, help="Existing artifacts/group-batches-rest run directory")
    parser.add_argument("--core-url", help="Use an already restarted Core service instead of isolated restoration")
    parser.add_argument("--token-env", default="ATELIERX_SERVICE_TOKEN", help="Bearer token env for --core-url mode")
    parser.add_argument("--validation-config", default=".atelierx/validation-config.json")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--lmstudio-url", default="http://127.0.0.1:1234")
    parser.add_argument("--timeout", type=int, default=600, help="Group-run poll timeout in seconds")
    parser.add_argument("--report-name", default="group-consistency-recheck.json")
    args = parser.parse_args()
    if args.timeout < 1: parser.error("--timeout must be positive")
    directory = Path(args.artifact_dir); report_path = directory / "report.json"
    if not directory.is_dir() or not report_path.is_file(): parser.error("--artifact-dir needs report.json")
    old_report = json.loads(report_path.read_text(encoding="utf-8"))
    old_run, request, targets = source_run(old_report)
    root = Path(__file__).resolve().parents[1]
    runners = []
    if args.core_url:
        core_url, token = local_url(args.core_url, "--core-url"), os.environ.get(args.token_env)
        if not token: parser.error(f"{args.token_env} is not set")
        mode = "external_core"
    else:
        generation_url, validation_url = saved_endpoints(old_report)
        config = json.loads((root / args.validation_config).read_text(encoding="utf-8"))
        provider_id = request["provider"]["provider_id"]
        if provider_id not in config.get("providers", {}): parser.error("saved provider is absent from --validation-config")
        provider = dict(config["providers"][provider_id], provider_id=provider_id, shared_gpu=True)
        if provider.get("api_key_env"):
            provider["api_key"] = os.environ.get(provider["api_key_env"], "")
            if not provider["api_key"]: parser.error(f"{provider['api_key_env']} is not set")
        token = secrets.token_urlsafe(32)
        gen = generation_app(directory / "generation", local_url(args.comfy_url, "--comfy-url"), token, .25)
        runner, generation_url = await start(gen, generation_url); runners.append(runner)
        validation = validation_app(directory / "validation", token, providers={provider_id: provider},
                                    generation_sources={"generation-local": {"url": generation_url, "token": token}}, profiles={}, poll=.2)
        runner, validation_url = await start(validation, validation_url); runners.append(runner)
        core = core_app(directory / "core.sqlite3", generation_url, token, poll=.25,
                        validation_config={"url": validation_url, "generation_server_id": "generation-local", "providers": {provider_id: provider}, "profiles": {}},
                        gpu_config={"comfy_url": local_url(args.comfy_url, "--comfy-url"), "lmstudio_url": local_url(args.lmstudio_url, "--lmstudio-url"), "model": provider["model"]})
        # Core has no saved endpoint; bind an ephemeral local port.
        runner = web.AppRunner(core); await runner.setup(); await web.TCPSite(runner, "127.0.0.1", 0).start(); runners.append(runner)
        core_url = f"http://127.0.0.1:{runner.addresses[0][1]}"
        gen[GEN_SERVICE].coordinator_url = core_url; validation[VAL_SERVICE].coordinator_url = core_url
        mode = "isolated_restore"
    output_path = directory / args.report_name
    report = {"started_at": time.time(), "mode": mode, "core_url": core_url, "source_group_run_id": old_run.get("id"), "group_id": request["group_id"],
              "reference_revision": request["reference_revision"], "target_image_ids": targets,
              "selection": {"profile_id": request["profile"]["profile_id"], "provider_id": request["provider"]["provider_id"]}}
    def save(): output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    key = "group-consistency-recheck:" + secrets.token_hex(12)
    try:
        async with aiohttp.ClientSession() as client:
            headers = {"Authorization": "Bearer " + token, "Idempotency-Key": key}
            body = {"reference_revision": request["reference_revision"], "target_ids": targets, "validation": report["selection"]}
            async with client.post(f"{core_url}/v1/groups/{request['group_id']}/validations", json=body, headers=headers) as response:
                value = await response.json()
                if response.status != 202: raise RuntimeError(f"group recheck was not accepted: HTTP {response.status} {value}")
            report["accepted_run"] = value; save(); deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                async with client.get(f"{core_url}/v1/group-validation-runs/{value['id']}", headers={"Authorization": "Bearer " + token}) as response:
                    current = await response.json()
                    if response.status != 200: raise RuntimeError(f"group recheck lookup failed: HTTP {response.status} {current}")
                if current.get("state") in {"completed", "failed", "cancelled"}:
                    report.update(result=current, verdict=current.get("outcome") if current.get("state") == "completed" else "error", finished_at=time.time()); save(); print(output_path); return
                await asyncio.sleep(1)
            raise TimeoutError("group recheck did not reach a terminal state before timeout")
    except Exception as exc:
        report.update(finished_at=time.time(), failure={"type": type(exc).__name__, "message": str(exc)}); save(); raise
    finally:
        for runner in reversed(runners): await runner.cleanup()


if __name__ == "__main__": asyncio.run(main())
