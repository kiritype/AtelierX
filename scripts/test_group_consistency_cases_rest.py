"""Run six real-VLM group-consistency controls from preserved artifact images.

No image is generated or edited.  The two original group images are served by
an isolated Generation restore.  The verified blue-jacket image is uploaded to
an isolated Validation diagnostic store, retaining its original SHA-256 and
generation-prompt metadata in the report.  Each direct Validation group request
has a fixed expected terminal outcome and feature status.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from atelierx.core import create_app as core_app
from atelierx.generation import create_app as generation_app
from atelierx.validation import GROUP_EVALUATION_VERSION, SERVICE as VAL_SERVICE
from atelierx.validation import create_app as validation_app


DEFAULT_CLOTHING = "artifacts/backend-pipeline-rest/20260913-133748/encode.png"


def local_url(value, name):
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"{name} must be a localhost http URL")
    return value.rstrip("/")


async def start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def source_run(report):
    # The latest recheck preserves the visual hair-length result. Its accepted
    # request also has the frozen provider/profile revisions required here.
    recheck = report.get("group_run")
    if isinstance(recheck, dict) and isinstance(recheck.get("request"), dict):
        return recheck["request"]
    raise ValueError("artifact report has no frozen group request")


def find_metadata(image_path):
    """Find the original Generation job metadata by immutable image SHA-256."""
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    for candidate in image_path.parent.glob("generation/jobs/*.json"):
        job = json.loads(candidate.read_text(encoding="utf-8"))
        for image in job.get("images", []):
            if image.get("sha256") == digest:
                node = job.get("node_inputs", {})
                return {"sha256": digest, "media_type": image.get("media_type"),
                        "positive_prompt": node.get("positive_prompt"), "negative_prompt": node.get("negative_prompt")}
    raise ValueError("clothing image does not match a preserved generation job SHA-256")


def configured_provider(config, frozen_provider):
    """Merge transport credentials with the immutable request revision safely."""
    provider_id = frozen_provider["provider_id"]
    if provider_id not in config.get("providers", {}):
        raise ValueError("frozen provider is absent from --validation-config")
    return {**config["providers"][provider_id], **frozen_provider,
            "provider_id": provider_id, "shared_gpu": True}


def classify_case_result(current, expected):
    """Separate an execution/parse error from a completed quality verdict."""
    item = (current.get("result") or {}).get("items", [{}])[0]
    expectation_met = current.get("outcome") == expected["outcome"] and item.get("status") == expected["status"]
    execution_error = (current.get("state") != "completed" or current.get("error") is not None
                       or item.get("status") == "error" or item.get("error") is not None)
    return item, expectation_met, execution_error, not execution_error and not expectation_met


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", default="artifacts/group-batches-rest/20260913-142529")
    parser.add_argument("--clothing-image", default=DEFAULT_CLOTHING)
    parser.add_argument("--run-root", default=None, help="New diagnostic report directory")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--lmstudio-url", default="http://127.0.0.1:1234")
    parser.add_argument("--validation-config", default=".atelierx/validation-config.json")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-tokens", type=int, default=None, help="Use a new isolated provider snapshot with this response token cap")
    parser.add_argument("--response-format", choices=("json_schema", "json_object"), default=None,
                        help="Explicit diagnostic provider format; never an automatic fallback")
    parser.add_argument("--include-reference-control", action="store_true",
                        help="Add a same-bytes reference precheck positive control")
    parser.add_argument("--list-candidates", action="store_true", help="Print inputs and exit without starting services")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if args.max_tokens is not None and args.max_tokens < 1:
        parser.error("--max-tokens must be positive")
    root = Path(__file__).resolve().parents[1]
    artifact = (root / args.artifact_dir).resolve() if not Path(args.artifact_dir).is_absolute() else Path(args.artifact_dir)
    clothing_path = (root / args.clothing_image).resolve() if not Path(args.clothing_image).is_absolute() else Path(args.clothing_image)
    report_path = artifact / "report.json"
    if not artifact.is_dir() or not report_path.is_file() or not (artifact / "generation").is_dir():
        parser.error("--artifact-dir needs preserved report.json and generation state")
    if not clothing_path.is_file():
        parser.error("--clothing-image must name an existing PNG/WebP artifact")
    old = json.loads(report_path.read_text(encoding="utf-8"))
    request = source_run(old)
    representative, target = request["representative"], request["targets"][0]
    if request.get("identity") != {"appearance": "adult woman, silver hair, blue eyes", "upper": "white shirt"}:
        parser.error("this bounded control suite requires the preserved white-shirt group fixture")
    clothing_metadata = find_metadata(clothing_path)
    candidates = {
        "bob_reference": {"ref": representative["ref"], "source": representative["source"], "prompt": representative["positive_prompt"], "observed": "short bob hair; white shirt"},
        "long_target": {"ref": target["ref"], "source": target["source"], "prompt": target["positive_prompt"], "observed": "long straight hair; white shirt"},
        "blue_jacket": {"path": str(clothing_path), **clothing_metadata, "observed": "blue jacket and brooch; visible upper clothing"},
    }
    if args.list_candidates:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return
    manifest = [
        {"name": "self_reference", "sources": ["bob_reference", "bob_reference"], "identity": request["identity"], "expected": {"outcome": "passed", "status": "matched"}},
        {"name": "hair_length_negative", "sources": ["bob_reference", "long_target"], "identity": request["identity"], "expected": {"outcome": "failed", "status": "mismatch"}},
        {"name": "upper_expression_variation", "sources": ["bob_reference", "long_target"], "identity": {"upper": "white shirt"}, "expected": {"outcome": "passed", "status": "matched"}},
        {"name": "lower_not_visible", "sources": ["bob_reference", "long_target"], "identity": {"lower": "black boots"}, "expected": {"outcome": "incomplete", "status": "insufficient"}},
        {"name": "upper_clothing_change", "sources": ["bob_reference", "blue_jacket"], "identity": {"upper": "white shirt"}, "expected": {"outcome": "failed", "status": "mismatch"}},
        {"name": "conflicting_upper_references", "sources": ["bob_reference", "blue_jacket", "bob_reference"], "identity": {"upper": "white shirt"}, "expected": {"outcome": "incomplete", "status": "reference_conflict"}},
    ]
    if args.include_reference_control:
        manifest.append({"name": "consistent_reference_control", "sources": ["bob_reference"] * 3,
                         "identity": request["identity"], "expected": {"outcome": "passed", "status": "matched"}})
    output = Path(args.run_root) if args.run_root else root / "artifacts/group-consistency-cases" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    token, runners = secrets.token_urlsafe(32), []
    report = {"started_at": time.time(), "artifact_dir": str(artifact), "candidates": candidates,
              "group_evaluation_version": GROUP_EVALUATION_VERSION, "case_manifest": manifest, "cases": []}

    def save():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Preserve the complete expected-control manifest before any diagnostic
    # upload or provider submission can alter the run history.
    save()
    try:
        config = json.loads((root / args.validation_config).read_text(encoding="utf-8"))
        provider = configured_provider(config, request["provider"])
        if args.max_tokens is not None:
            # A diagnostic setting gets its own ID, never rewriting an old
            # provider revision or the user's live configuration.
            provider.update(provider_id=provider["provider_id"] + "-bounded", revision=1, max_tokens=args.max_tokens)
            request = copy.deepcopy(request)
            request["provider"] = {key: provider[key] for key in
                                   ("provider_id", "revision", "model", "timeout_seconds", "max_tokens")}
        if args.response_format is not None:
            provider.update(provider_id=provider["provider_id"] + "-" + args.response_format,
                            revision=1, response_format=args.response_format)
            request = copy.deepcopy(request)
            request["provider"] = dict(request["provider"], provider_id=provider["provider_id"], revision=1)
        provider_id = provider["provider_id"]
        report["provider_snapshot"] = request["provider"]
        report["response_format"] = provider.get("response_format", "json_object")
        save()
        comfy_url = local_url(args.comfy_url, "--comfy-url")
        lmstudio_url = local_url(args.lmstudio_url, "--lmstudio-url")
    except Exception as exc:
        report.update(startup_failure={"type": type(exc).__name__, "message": str(exc)}, finished_at=time.time())
        save()
        raise
    try:
        generation = generation_app(artifact / "generation", comfy_url, token, .25)
        runner, generation_url = await start(generation); runners.append(runner)
        validation = validation_app(output / "validation", token, providers={provider_id: provider},
                                    generation_sources={"generation-local": {"url": generation_url, "token": token}},
                                    profiles={request["profile"]["profile_id"]: request["profile"]}, poll=.2)
        runner, validation_url = await start(validation); runners.append(runner)
        core = core_app(output / "core.sqlite3", generation_url, token, poll=.25,
                        validation_config={"url": validation_url, "generation_server_id": "generation-local",
                                           "providers": {provider_id: provider}, "profiles": {}},
                        gpu_config={"comfy_url": comfy_url, "lmstudio_url": lmstudio_url, "model": provider["model"]})
        runner, core_url = await start(core); runners.append(runner)
        validation[VAL_SERVICE].coordinator_url = core_url
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            async with client.get(comfy_url + "/queue") as response:
                queue = await response.json()
            if response.status != 200 or queue["queue_running"] or queue["queue_pending"]:
                raise RuntimeError("ComfyUI busy: no interference")
            report["comfy_preflight"] = queue
            # Upload makes a new diagnostic Validation copy only. The original
            # generation artifact and Core source database remain untouched.
            async with client.post(validation_url + "/v1/uploads", data=clothing_path.read_bytes()) as response:
                uploaded = await response.json()
            if response.status != 201:
                raise RuntimeError(f"clothing upload failed: HTTP {response.status} {uploaded}")
            if uploaded["sha256"] != clothing_metadata["sha256"]:
                raise RuntimeError("uploaded clothing SHA-256 changed")
            blue = {"ref": "blue-jacket-upload", "positive_prompt": clothing_metadata["positive_prompt"],
                    "negative_prompt": clothing_metadata["negative_prompt"],
                    "source": {"type": "upload", "upload_id": uploaded["upload_id"], "sha256": uploaded["sha256"]}}

            def renamed(image, ref):
                value = copy.deepcopy(image); value["ref"] = ref; return value

            cases = [
                (representative, [], [renamed(representative, "self-target")]),
                (representative, [], [target]),
                (representative, [], [target]),
                (representative, [], [target]),
                (representative, [], [blue]),
                (representative, [blue], [renamed(representative, "white-target")]),
            ]
            if args.include_reference_control:
                cases.append((representative, [renamed(representative, "same-reference-auxiliary")],
                              [renamed(representative, "same-reference-target")]))
            for definition, (rep, auxiliaries, targets) in zip(manifest, cases, strict=True):
                case_started = time.monotonic()
                name, identity, expected = definition["name"], definition["identity"], definition["expected"]
                body = {"group_id": "diagnostic-" + name, "reference_revision": 1, "representative": rep,
                        "auxiliaries": auxiliaries, "targets": targets, "identity": identity,
                        "profile": request["profile"], "provider": request["provider"]}
                key = "consistency-case:" + name
                async with client.post(validation_url + "/v1/validations/group", json=body,
                                       headers={"Authorization": "Bearer " + token, "Idempotency-Key": key}) as response:
                    run = await response.json()
                if response.status != 202:
                    raise RuntimeError(f"{name} not accepted: HTTP {response.status} {run}")
                deadline = time.monotonic() + args.timeout
                while time.monotonic() < deadline:
                    async with client.get(validation_url + "/v1/validation-jobs/" + run["job_id"], headers={"Authorization": "Bearer " + token}) as response:
                        current = await response.json()
                    if response.status != 200:
                        raise RuntimeError(f"{name} lookup failed: HTTP {response.status} {current}")
                    if current.get("state") in {"completed", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(1)
                item, expectation_met, execution_error, verdict_mismatch = classify_case_result(current, expected)
                # A parsed provider-item error is a completed diagnostic job,
                # not a safe quality verdict.  Keep running the remaining
                # controls, but record it apart from a genuine verdict miss.
                record = {"name": name, "expected": expected, "expectation_met": expectation_met,
                          "execution_error": execution_error, "verdict_mismatch": verdict_mismatch,
                          "actual": current, "elapsed_seconds": round(time.monotonic() - case_started, 3)}
                report["cases"].append(record); save()
                if current.get("state") != "completed" or current.get("error") is not None:
                    raise AssertionError(f"{name} execution error: {current}")
                print(f"{name}: {current['outcome']}/{item['status']}", flush=True)
            gpu = None
            for _ in range(100):
                async with client.get(core_url + "/v1/gpu") as response:
                    gpu = await response.json()
                if gpu["owner"] is None and gpu["waiting"] == []:
                    break
                await asyncio.sleep(.2)
            if not gpu or gpu["owner"] is not None or gpu["waiting"]:
                raise AssertionError(f"GPU lease was not released: {gpu}")
            met = sum(case["expectation_met"] for case in report["cases"])
            execution_errors = [case["name"] for case in report["cases"] if case["execution_error"]]
            verdict_mismatches = [case["name"] for case in report["cases"] if case["verdict_mismatch"]]
            report.update(
                gpu_after=gpu,
                counts={"total": len(report["cases"]), "expectation_met": met,
                        "execution_error_cases": len(execution_errors),
                        "verdict_mismatch_cases": len(verdict_mismatches)},
                case_categories={"execution_error_cases": execution_errors,
                                 "verdict_mismatch_cases": verdict_mismatches},
                finished_at=time.time(),
            ); save()
            print(output / "report.json", flush=True)
            if met != len(report["cases"]):
                raise AssertionError("One or more consistency control verdicts differed from the fixed expectations")
    except Exception as exc:
        report.update(failure={"type": type(exc).__name__, "message": str(exc)}, finished_at=time.time()); save(); raise
    finally:
        for runner in reversed(runners):
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
