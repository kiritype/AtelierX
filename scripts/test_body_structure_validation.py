"""Manifest-driven, operator-run body anatomy VLM evaluation.

This harness never derives a verdict from an image name.  Its checked-in cases
carry the original generation prompt and immutable file digest, while the
operator records expected outcome and per-part evidence before a live run.
``--dry-run`` performs all local manifest and image-integrity checks without
starting a service, acquiring GPU access, or calling a provider.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from atelierx.validation import create_app


ROOT = Path(__file__).resolve().parents[1]
PARTS = ("hands", "face", "limbs")
PROFILE_ID = "body-structure-eval"
NO_ASSESSABLE = "VAL_NO_ASSESSABLE_CHECKS"


def local_url(value, label):
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"{label} must be an http localhost URL")
    return value.rstrip("/")


def load_cases(path, requested=None):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("cases"), list):
        raise ValueError("body evaluation manifest must contain schema_version 1 and cases")
    wanted = set(requested.split(",")) if requested else None
    cases = [case for case in manifest["cases"] if wanted is None or case.get("id") in wanted]
    if wanted and {case.get("id") for case in cases} != wanted:
        raise ValueError("--cases contains an unknown case id")
    if not cases:
        raise ValueError("no cases selected")
    for case in cases:
        if set(case) - {"id", "image", "sha256", "positive_prompt", "expected", "provenance", "rationale"}:
            raise ValueError(f"{case.get('id', 'case')}: unexpected field")
        if not isinstance(case.get("id"), str) or not case["id"]:
            raise ValueError("case id is required")
        if not isinstance(case.get("image"), str) or Path(case["image"]).is_absolute() or ".." in Path(case["image"]).parts:
            raise ValueError(f"{case['id']}: image must be a workspace-relative path")
        if not isinstance(case.get("positive_prompt"), str) or not case["positive_prompt"].strip():
            raise ValueError(f"{case['id']}: positive_prompt is required")
        if not isinstance(case.get("sha256"), str) or len(case["sha256"]) != 64:
            raise ValueError(f"{case['id']}: sha256 is required")
        body_parts = list((case.get("expected") or {}).get("body_parts", {}))
        if not isinstance(body_parts, list) or not body_parts or len(set(body_parts)) != len(body_parts) or any(part not in PARTS for part in body_parts):
            raise ValueError(f"{case['id']}: body_parts must be a nonempty unique subset of hands, face, limbs")
        expected = case.get("expected")
        if not isinstance(expected, dict) or set(expected) != {"outcome", "error_code", "body_parts"}:
            raise ValueError(f"{case['id']}: expected must define outcome, error_code, body_parts")
        if not isinstance(expected["body_parts"], dict) or set(expected["body_parts"]) != set(body_parts):
            raise ValueError(f"{case['id']}: expected.body_parts must match body_parts")
    return cases


def materialize_cases(cases):
    rows = []
    for case in cases:
        image = ROOT / case["image"]
        data = image.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != case["sha256"]:
            raise ValueError(f"{case['id']}: source image sha256 differs from manifest")
        rows.append((case, data))
    return rows


def expectations_ready(case):
    expected = case["expected"]
    return expected["outcome"] in {"passed", "failed", "error"} and all(
        status in {"matched", "not_visible", "mismatch", "uncertain"} for status in expected["body_parts"].values()
    ) and (expected["outcome"] != "error" or isinstance(expected["error_code"], str))


def profile(case):
    # Body findings are deliberately independent from output and prompt presence.
    return {"profile_id": PROFILE_ID + "-" + case["id"], "revision": 1, "output_conditions": False,
            "positive_prompt": False, "negative_prompt": False, "body_parts": list(case["expected"]["body_parts"]),
            "metadata": False, "consistency": False}


def evidence_by_part(result):
    if not isinstance(result, dict):
        return {}
    candidates = result.get("body_parts", result.get("evidence", []))
    if isinstance(candidates, dict):
        return {part: value.get("status") if isinstance(value, dict) else value for part, value in candidates.items() if part in PARTS}
    if isinstance(candidates, list):
        found = {}
        for item in candidates:
            if not isinstance(item, dict):
                continue
            part = item.get("part")
            if not part and item.get("kind") == "body":
                part = item.get("requirement")
            if not part:
                part = item.get("id", "").removeprefix("body-")
            if part in PARTS:
                found[part] = item.get("status")
        return found
    return {}


def evaluate(case, job):
    actual = {"outcome": job.get("outcome"), "error_code": (job.get("error") or {}).get("code"),
              "body_parts": evidence_by_part(job.get("result"))}
    expected = case["expected"]
    matches = actual["outcome"] == expected["outcome"] and actual["error_code"] == expected["error_code"]
    if actual["outcome"] == "error":
        # VAL_NO_ASSESSABLE_CHECKS has result=None by contract; its pre-error
        # evidence is not fabricated into the report.
        return actual, matches
    matches = matches and all(actual["body_parts"].get(part) == value for part, value in expected["body_parts"].items())
    # No assessable part is an error, never a pass.  It is valid only when the
    # recorded expectation says so; the service owns that verdict.
    if not actual["body_parts"] and actual["outcome"] != "error":
        matches = False
    return actual, matches


async def start_isolated(directory, token, provider, coordinator_url, profiles):
    app = create_app(directory, token, providers={"local-vision": provider}, profiles=profiles,
                     poll=.1, coordinator_url=coordinator_url)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


async def wait_for_job(client, url, job_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with client.get(url + "/v1/validation-jobs/" + job_id) as response:
            value = await response.json()
        if value.get("state") in {"completed", "failed", "cancelled"}:
            return value
        await asyncio.sleep(.5)
    raise TimeoutError(f"validation job {job_id} did not finish within {timeout} seconds")


async def wait_for_gpu_release(client, service_url, job_id, timeout):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        async with client.get(service_url + "/v1/validation-jobs/" + job_id) as response:
            if response.status == 200:
                last = await response.json()
                if last.get("gpu_released") is True or last.get("gpu_requested") is False:
                    return last
        await asyncio.sleep(.5)
    raise TimeoutError(f"GPU release acknowledgement was not observed for {job_id}: {last}")


async def run(args, cases):
    rows = materialize_cases(cases)
    output = Path(args.output_dir) if args.output_dir else ROOT / "artifacts" / "body-structure-validation" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    report = {"started_at": time.time(), "dry_run": args.dry_run, "cases": []}
    for case, data in rows:
        report["cases"].append({"case": case["id"], "source": case["image"], "source_sha256": hashlib.sha256(data).hexdigest(),
                                "provenance": case.get("provenance"), "rationale": case.get("rationale"),
                                "expected": case["expected"], "actual": None, "elapsed_seconds": None})
    if args.dry_run:
        report["finished_at"] = time.time()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return output / "report.json"
    if not all(expectations_ready(case) for case, _ in rows):
        raise ValueError("live run blocked: operator must set expected outcome and all body-part statuses in the manifest")
    config = json.loads((ROOT / args.config).read_text(encoding="utf-8"))
    provider = dict(config["providers"]["local-vision"])
    provider_url = local_url(provider["url"].removesuffix("/v1"), "local-vision provider URL")
    if provider_url not in {"http://localhost:1234", "http://127.0.0.1:1234"}:
        raise ValueError("body evaluation is restricted to the local LM Studio endpoint")
    coordinator_url = local_url(args.coordinator_url or config.get("coordinator_url", ""), "Core coordinator URL")
    token = os.environ.get("ATELIERX_SERVICE_TOKEN")
    if not token:
        raise ValueError("ATELIERX_SERVICE_TOKEN is required for a live run")
    provider.update(provider_id="local-vision", shared_gpu=True)
    provider_audit = {key: provider[key] for key in ("provider_id", "model", "revision")}
    report["provider"] = provider_audit
    for record in report["cases"]:
        record["provider"] = provider_audit
    configured_profiles = {profile(case)["profile_id"]: profile(case) for case, _ in rows}
    report["profiles"] = list(configured_profiles.values())
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    runner, service_url = await start_isolated(output / "validation", token, provider, coordinator_url, configured_profiles)
    try:
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            for record, (case, data) in zip(report["cases"], rows, strict=True):
                started = time.monotonic()
                async with client.post(service_url + "/v1/uploads", data=data) as response:
                    upload = await response.json()
                    if response.status != 201:
                        raise RuntimeError(f"{case['id']}: upload failed: {upload}")
                request = {"image": {"ref": case["id"], "source": {"type": "upload", "upload_id": upload["upload_id"], "sha256": upload["sha256"]},
                                     "positive_prompt": case["positive_prompt"], "negative_prompt": "", "negative_sources": {"global": "", "character": ""}},
                           "generation_attempt_id": None, "generation_settings": None, "expected_output": None,
                           "profile": profile(case), "provider": {key: provider[key] for key in ("provider_id", "revision", "model", "timeout_seconds") if key in provider}}
                async with client.post(service_url + "/v1/validations/single", json=request,
                                       headers={"Idempotency-Key": "body-eval-" + case["id"]}) as response:
                    accepted = await response.json()
                    if response.status != 202:
                        raise RuntimeError(f"{case['id']}: submission failed: {accepted}")
                job = await wait_for_job(client, service_url, accepted["job_id"], args.timeout)
                actual, matches = evaluate(case, job)
                release = await wait_for_gpu_release(client, service_url, accepted["job_id"], args.release_timeout)
                record.update(actual=actual, expected_matches=matches, elapsed_seconds=round(time.monotonic() - started, 2),
                              job=job, gpu_release=release)
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        await runner.cleanup()
    report["finished_at"] = time.time()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output / "report.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="scripts/body_structure_validation_cases.json")
    parser.add_argument("--config", default=".atelierx/validation-config.json")
    parser.add_argument("--coordinator-url", help="required for a live shared-GPU run unless set in the config")
    parser.add_argument("--cases", help="comma-separated manifest case IDs")
    parser.add_argument("--output-dir")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--release-timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.timeout < 1 or args.release_timeout < 1:
        parser.error("--timeout and --release-timeout must be positive")
    cases = load_cases(ROOT / args.manifest, args.cases)
    print(asyncio.run(run(args, cases)), flush=True)


if __name__ == "__main__":
    main()
