"""Real Anima group-batch and managed-validation-settings verification.

Runs isolated Core/Generation/Validation state on random localhost ports while
using the already-running local ComfyUI and LM Studio 8B configuration.  It is
deliberately an operator-run GPU test. The existing coordinator manages idle
model residency; the script does not install models or restart external services.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from atelierx.core import create_app as core_app
from atelierx.generation import SERVICE as GEN_SERVICE
from atelierx.generation import create_app as generation_app
from atelierx.validation import SERVICE as VAL_SERVICE
from atelierx.validation import create_app as validation_app


async def start(app, listen_url=None):
    runner = web.AppRunner(app)
    await runner.setup()
    if listen_url:
        parsed = urlparse(require_local_url(listen_url, "saved service endpoint"))
        if parsed.path not in {"", "/"} or parsed.port is None:
            raise ValueError("saved service endpoint must have a localhost port and no path")
        await web.TCPSite(runner, "127.0.0.1", parsed.port).start()
        return runner, f"http://127.0.0.1:{parsed.port}"
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def provider_setting(value):
    """Turn a public settings response back into a valid PATCH payload."""
    return {key: item for key, item in value.items() if key not in {
        "provider_id", "revision", "kind", "archived", "created_at",
        "updated_at", "synchronization",
    }}


def require_local_url(value, name):
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"{name} must be an http localhost URL")
    return value.rstrip("/")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", default=None, help="Artifact directory; defaults to artifacts/group-batches-rest/<timestamp>")
    parser.add_argument("--resume", metavar="ARTIFACT_DIR", help="Resume an awaiting batch without creating images, settings, or entities")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--lmstudio-url", default="http://127.0.0.1:1234")
    parser.add_argument("--validation-config", default=".atelierx/validation-config.json")
    parser.add_argument("--seed", type=int, default=2026091317)
    parser.add_argument("--timeout", type=int, default=1200, help="Per asynchronous stage timeout in seconds")
    args = parser.parse_args()
    if args.resume and args.run_root:
        parser.error("--resume cannot be combined with --run-root")
    args.comfy_url = require_local_url(args.comfy_url, "--comfy-url")
    args.lmstudio_url = require_local_url(args.lmstudio_url, "--lmstudio-url")
    root = Path(__file__).resolve().parents[1]
    if args.resume:
        destination = Path(args.resume)
        report_path = destination / "report.json"
        if not destination.is_dir() or not (destination / "core.sqlite3").is_file() or not report_path.is_file():
            parser.error("--resume requires an existing artifact directory with core.sqlite3 and report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        prior_batch = report.get("batch_accepted")
        if not isinstance(prior_batch, dict) or not prior_batch.get("items") or not prior_batch.get("group_validation_frozen"):
            parser.error("--resume report has no accepted group batch snapshot")
        generation_url = prior_batch["items"][0]["snapshot"]["generation_endpoint"]
        validation_url = prior_batch["group_validation_frozen"]["endpoint"]
        require_local_url(generation_url, "saved generation endpoint")
        require_local_url(validation_url, "saved validation endpoint")
        resume_attempt = {"started_at": time.time(), "batch_id": prior_batch["id"], "status": "running"}
        report.setdefault("resumes", []).append(resume_attempt)
    else:
        destination = Path(args.run_root) if args.run_root else root / "artifacts/group-batches-rest" / time.strftime("%Y%m%d-%H%M%S")
        destination.mkdir(parents=True, exist_ok=False)
        report = {"started_at": time.time(), "seed": args.seed, "provider_initial": None, "events": []}
        prior_batch = None
        generation_url = validation_url = None
        resume_attempt = None
    config = json.loads((root / args.validation_config).read_text(encoding="utf-8"))
    provider_id = "local-vision"
    provider_config = dict(config["providers"][provider_id], provider_id=provider_id, shared_gpu=True)
    require_local_url(provider_config["url"].rsplit("/v1", 1)[0], "configured provider URL")
    token, runners = secrets.token_urlsafe(32), []
    if not args.resume:
        report["provider_initial"] = {key: provider_config[key] for key in ("provider_id", "revision", "model", "timeout_seconds")}

    def write_report():
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    async def wait_for(fetch, terminal, label):
        deadline = time.monotonic() + args.timeout
        latest, observed = None, None
        while time.monotonic() < deadline:
            latest = await fetch()
            summary = latest.get("summary") if isinstance(latest, dict) else None
            observation = (latest.get("state"), json.dumps(summary, sort_keys=True) if summary is not None else None)
            if observation != observed:
                observed = observation
                report["latest_batch"] = {"state": latest.get("state"), "summary": summary}
                write_report()
                print(f"{label}: {latest.get('state')} {summary or ''}".rstrip(), flush=True)
            if latest.get("state") in terminal:
                return latest
            await asyncio.sleep(1)
        raise AssertionError(f"{label} timed out: {latest}")

    try:
        gen = generation_app(destination / "generation", args.comfy_url, token, .25)
        runner, gen_url = await start(gen, generation_url); runners.append(runner)
        validation = validation_app(destination / "validation", token, providers={provider_id: provider_config},
                                    generation_sources={"generation-local": {"url": gen_url, "token": token}}, profiles={}, poll=.2)
        runner, validation_url = await start(validation, validation_url); runners.append(runner)
        gpu_config = {"comfy_url": args.comfy_url, "lmstudio_url": args.lmstudio_url, "model": provider_config["model"]}

        def new_core():
            return core_app(destination / "core.sqlite3", gen_url, token, poll=.25,
                            validation_config={"url": validation_url, "generation_server_id": "generation-local",
                                               "providers": {provider_id: provider_config}, "profiles": {}}, gpu_config=gpu_config)

        runner, core_url = await start(new_core()); runners.append(runner)
        gen[GEN_SERVICE].coordinator_url = core_url
        validation[VAL_SERVICE].coordinator_url = core_url
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            async def call(method, path, body=None, expected=200, key=None):
                headers = {"Idempotency-Key": key} if key else {}
                async with client.request(method, core_url + path, json=body, headers=headers) as response:
                    value = await response.json()
                    assert response.status == expected, (method, path, response.status, value)
                    return value

            # Do not add work to a user's active ComfyUI queue.  The shared GPU
            # coordinator repeats this safety check before each phase.
            async with client.get(args.comfy_url + "/queue") as response:
                queue = await response.json()
            assert response.status == 200 and not queue["queue_running"] and not queue["queue_pending"], "ComfyUI busy: no interference"
            report["comfy_preflight"] = {"queue_running": queue["queue_running"], "queue_pending": queue["queue_pending"]}

            if args.resume:
                # The original process has already generated and single-checked
                # both images.  Rebind its saved endpoints and continue only at
                # the explicit reference confirmation boundary.
                batch = await call("GET", "/v1/group-batches/" + prior_batch["id"])
                assert batch["state"] == "awaiting_reference_confirmation", batch
                assert batch["group_validation_frozen"]["endpoint"] == validation_url, batch
                assert {item["snapshot"]["generation_endpoint"] for item in batch["items"]} == {gen_url}, batch
                assert len(batch["summary"]["passed_image_ids"]) == 2 and all(item["state"] == "passed" for item in batch["items"]), batch
                report["resume_batch_before_confirmation"] = batch
                candidate = await call("GET", f"/v1/groups/{batch['group_id']}/reference-candidate")
                assert candidate["state"] == "ready_for_confirmation", candidate
                updated_group = await call("PUT", f"/v1/groups/{batch['group_id']}/reference", {
                    "revision": 0, "representative_id": candidate["representative_id"], "auxiliary_ids": candidate["auxiliary_ids"]})
                resumed = await call("POST", "/v1/group-batches/" + batch["id"] + "/confirm-reference", {
                    "reference_revision": updated_group["reference"]["revision"]}, 202, "resume-batch-confirm")
                confirm_duplicate = await call("POST", "/v1/group-batches/" + batch["id"] + "/confirm-reference", {
                    "reference_revision": updated_group["reference"]["revision"]}, 200, "resume-batch-confirm")
                assert confirm_duplicate["id"] == resumed["id"]
                completed = await wait_for(lambda: call("GET", "/v1/group-batches/" + batch["id"]), {"completed", "failed", "cancelled"}, "resumed batch group validation")
                report["batch_completed"] = completed; write_report()
                assert completed["state"] == "completed", completed
                group_run = await call("GET", "/v1/group-validation-runs/" + completed["group_run_id"])
                assert group_run["state"] == "completed" and group_run["outcome"] in {"passed", "failed", "incomplete"}, group_run
                assert all(item["status"] != "error" for item in group_run["result"]["items"]), group_run
                report["group_run"] = group_run; write_report()

                await runners.pop().cleanup()
                runner, core_url = await start(new_core()); runners.append(runner)
                gen[GEN_SERVICE].coordinator_url = core_url
                validation[VAL_SERVICE].coordinator_url = core_url
                restored = await call("GET", "/v1/group-batches/" + batch["id"])
                assert restored == completed
                restored_run = await call("GET", "/v1/group-validation-runs/" + group_run["id"])
                assert restored_run == group_run
                gpu_after = await call("GET", "/v1/gpu")
                queue_after = await call("GET", "/v1/queue?limit=200")
                assert gpu_after["owner"] is None and gpu_after["waiting"] == [], gpu_after
                assert all(row["state"] in {"generated", "completed", "failed", "cancelled"} for row in queue_after["items"]), queue_after
                report["gpu_after"] = gpu_after
                report["queue_after"] = queue_after
                resume_attempt.update(status="completed", finished_at=time.time())
                report["restart_verified"] = True
                report["finished_at"] = time.time(); write_report()
                print(destination / "report.json", flush=True)
                return

            # The local provider is seeded from the isolated config.  Revision it
            # through the managed REST API before batch acceptance, then again
            # afterward to prove saved task snapshots retain the first revision.
            current_provider = await call("GET", f"/v1/validation-settings/providers/{provider_id}")
            managed_provider = await call("PATCH", f"/v1/validation-settings/providers/{provider_id}",
                                          {"revision": current_provider["revision"], "setting": provider_setting(current_provider)})
            report["provider_before_batch"] = managed_provider
            suffix = str(int(time.time()))
            single_id, group_id = "batch-single-" + suffix, "batch-group-" + suffix
            single = await call("POST", "/v1/validation-settings/single-profiles", {
                "profile_id": single_id, "revision": 1, "output_conditions": True, "positive_prompt": True,
                "negative_prompt": True, "body_parts": [], "metadata": False, "consistency": False}, 201)
            group_profile = await call("POST", "/v1/validation-settings/group-profiles", {"profile_id": group_id, "revision": 1, "consistency": True}, 201)
            report["managed_settings"] = {"provider": managed_provider, "single_profile": single, "group_profile": group_profile}

            work = await call("POST", "/v1/works", {"name": "Batch REST test"}, 201)
            character = await call("POST", "/v1/characters", {"name": "Safe adult", "parent_id": work["id"], "negative_prompt": ""}, 201)
            outfit = await call("POST", "/v1/outfits", {"name": "Portrait", "parent_id": character["id"], "components": {
                "appearance": "adult woman, silver hair, blue eyes", "upper": "white shirt", "lower": ""}}, 201)
            group = await call("POST", "/v1/groups", {"outfit_id": outfit["id"]}, 201)
            settings = await call("GET", "/v1/settings")
            settings = await call("PATCH", "/v1/settings", {"revision": settings["revision"], "positive_quality": "masterpiece, detailed anime illustration", "negative": "blurry, low quality",
                                                                 "auto_regeneration_enabled": False, "max_auto_regenerations": 0})
            assert settings["auto_regeneration_enabled"] is False and settings["max_auto_regenerations"] == 0
            report["generation_settings"] = settings
            template = json.loads((root / "custom_nodes/atelierx_anima/examples/anima-preview.api.json").read_text(encoding="utf-8"))["prompt"]["1"]["inputs"]
            inputs = {key: value for key, value in template.items() if key not in {"positive_prompt", "negative_prompt", "lora_stack"}}
            inputs.update(seed=args.seed, width=768, height=1024)
            items = []
            for index, expression in enumerate(("calm smile", "thoughtful expression")):
                item_inputs = dict(inputs, seed=args.seed + index)
                items.append({"framing": "upper_body", "expression": expression, "situation": "studio portrait",
                              "generation_inputs": item_inputs, "postprocess": {"encode": {"webp_enabled": False, "webp_quality": 90}},
                              "validation": {"profile_id": single_id, "provider_id": provider_id}})
            body = {"items": items, "group_validation": {"profile_id": group_id, "provider_id": provider_id}}
            batch = await call("POST", f"/v1/groups/{group['id']}/batches", body, 202, "live-group-batch")
            duplicate = await call("POST", f"/v1/groups/{group['id']}/batches", body, 200, "live-group-batch")
            assert duplicate["id"] == batch["id"]
            assert {item["snapshot"]["validation"]["provider"]["revision"] for item in batch["items"]} == {managed_provider["revision"]}
            report["batch_accepted"] = batch; write_report()

            changed_provider = await call("PATCH", f"/v1/validation-settings/providers/{provider_id}",
                                          {"revision": managed_provider["revision"], "setting": provider_setting(managed_provider)})
            report["provider_after_batch"] = changed_provider
            assert changed_provider["revision"] == managed_provider["revision"] + 1
            batch = await wait_for(lambda: call("GET", "/v1/group-batches/" + batch["id"]), {"awaiting_reference_confirmation", "insufficient_images", "failed", "cancelled"}, "batch single validation")
            report["batch_after_single"] = batch; write_report()
            assert batch["state"] == "awaiting_reference_confirmation", batch
            passed = batch["summary"]["passed_image_ids"]
            assert len(passed) == 2, batch
            for item in batch["items"]:
                assert item["state"] == "passed", item
                assert item["snapshot"]["validation"]["provider"]["revision"] == managed_provider["revision"]
            candidate = await call("GET", f"/v1/groups/{group['id']}/reference-candidate")
            assert candidate["state"] == "ready_for_confirmation", candidate
            updated_group = await call("PUT", f"/v1/groups/{group['id']}/reference", {
                "revision": 0, "representative_id": candidate["representative_id"], "auxiliary_ids": candidate["auxiliary_ids"]})
            resumed = await call("POST", "/v1/group-batches/" + batch["id"] + "/confirm-reference", {"reference_revision": updated_group["reference"]["revision"]}, 202, "live-batch-confirm")
            confirm_duplicate = await call("POST", "/v1/group-batches/" + batch["id"] + "/confirm-reference", {"reference_revision": updated_group["reference"]["revision"]}, 200, "live-batch-confirm")
            assert confirm_duplicate["id"] == resumed["id"]
            completed = await wait_for(lambda: call("GET", "/v1/group-batches/" + batch["id"]), {"completed", "failed", "cancelled"}, "batch group validation")
            report["batch_completed"] = completed; write_report()
            assert completed["state"] == "completed", completed
            group_run = await call("GET", "/v1/group-validation-runs/" + completed["group_run_id"])
            # A visual mismatch is a valid completed verdict.  Provider/contract
            # execution errors are not and must remain distinguishable in report.
            assert group_run["state"] == "completed" and group_run["outcome"] in {"passed", "failed", "incomplete"}, group_run
            assert all(item["status"] != "error" for item in group_run["result"]["items"]), group_run
            report["group_run"] = group_run; write_report()

            await runners.pop().cleanup()
            runner, core_url = await start(new_core()); runners.append(runner)
            gen[GEN_SERVICE].coordinator_url = core_url
            validation[VAL_SERVICE].coordinator_url = core_url
            restored = await call("GET", "/v1/group-batches/" + batch["id"])
            assert restored == completed
            restored_run = await call("GET", "/v1/group-validation-runs/" + group_run["id"])
            assert restored_run == group_run
            gpu_after = await call("GET", "/v1/gpu")
            queue_after = await call("GET", "/v1/queue?limit=200")
            assert gpu_after["owner"] is None and gpu_after["waiting"] == [], gpu_after
            assert all(row["state"] in {"generated", "completed", "failed", "cancelled"} for row in queue_after["items"]), queue_after
            report["gpu_after"] = gpu_after
            report["queue_after"] = queue_after
            report["restart_verified"] = True
            report["finished_at"] = time.time(); write_report()
            print(destination / "report.json", flush=True)
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}
        if resume_attempt is not None:
            resume_attempt.update(status="failed", failure=failure, finished_at=time.time())
        else:
            report["failure"] = failure
        report["finished_at"] = time.time()
        write_report()
        raise
    finally:
        for runner in reversed(runners):
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
