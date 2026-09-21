"""Explicit real local-VLM smoke; diagnostic prompt changes never edit Core history."""
import asyncio
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import time

import aiohttp
from aiohttp import web

from atelierx.validation import create_app


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", help="Comma-separated case names; default runs all")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / ".atelierx/validation-config.json").read_text(encoding="utf-8"))
    provider_id = "local-vision"
    provider = config["providers"][provider_id]
    if provider["url"].rstrip("/") not in {"http://localhost:1234/v1", "http://127.0.0.1:1234/v1"}:
        raise RuntimeError("This test is authorized only for the local LM Studio server")
    profile = config["profiles"]["single-default"]
    source = root / "artifacts/backend-pipeline-rest/20260913-042429"
    original_task = next(row["task"] for row in json.loads((source / "report.json").read_text(encoding="utf-8")) if row.get("name") == "detailer")
    gen = original_task["snapshot"]["generation_inputs"]
    data = (source / "detailer.png").read_bytes()
    destination = root / "artifacts/lmstudio-validation" / time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True)
    (destination / "input.png").write_bytes(data)
    token = secrets.token_urlsafe(32)
    runner = web.AppRunner(create_app(destination / "validation", token,
        providers={provider_id: provider}, profiles={profile["profile_id"]: profile}, poll=.1))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    reports = []
    try:
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            async with client.get("http://127.0.0.1:8188/queue") as response:
                queue = await response.json()
                if queue["queue_running"] or queue["queue_pending"]:
                    raise RuntimeError("ComfyUI is busy; VLM test not submitted")
            async with client.post(url + "/v1/uploads", data=data) as response:
                upload = await response.json()
                assert response.status == 201, upload
            cases = [("actual-generation-prompt", gen["positive_prompt"], gen["negative_prompt"], None),
                     ("diagnostic-wrong-colors", gen["positive_prompt"].replace("silver hair", "bright red hair").replace("blue eyes", "green eyes"), gen["negative_prompt"], "failed"),
                     ("diagnostic-hidden-footwear", gen["positive_prompt"] + ", clearly visible black boots", gen["negative_prompt"], "failed"),
                     ("diagnostic-missing-prop", gen["positive_prompt"] + ", holding a red umbrella", gen["negative_prompt"], "failed"),
                     ("diagnostic-prohibited-hairpin", gen["positive_prompt"], gen["negative_prompt"] + ", hairpin", "failed"),
                     ("global-negative-hairpin-excluded", gen["positive_prompt"], gen["negative_prompt"] + ", hairpin", "passed")]
            for name, positive, negative, expected in cases:
                if args.cases and name not in args.cases.split(","):
                    continue
                request = {"image": {"ref": "local-test-image", "source": {"type": "upload", "upload_id": upload["upload_id"], "sha256": upload["sha256"]},
                           "positive_prompt": positive, "negative_prompt": negative,
                           "negative_sources": {"global": gen["negative_prompt"], "character": "hairpin"} if name == "diagnostic-prohibited-hairpin" else {"global": negative, "character": ""}},
                           "generation_attempt_id": original_task["id"] if expected is None else None,
                           "profile": profile, "provider": {"provider_id": provider_id, **{key: provider[key] for key in ("revision", "model", "timeout_seconds")}},
                           "expected_output": {"width": 768, "height": 1024, "media_type": "image/png", "alpha": "not_required"}}
                started = time.monotonic()
                async with client.post(url + "/v1/validations/single", json=request, headers={"Idempotency-Key": name}) as response:
                    job = await response.json()
                    assert response.status == 202, job
                print(name + ": submitted", flush=True)
                for _ in range(240):
                    async with client.get(url + "/v1/validation-jobs/" + job["job_id"]) as response:
                        job = await response.json()
                    if job["state"] in {"completed", "failed"}: break
                    await asyncio.sleep(1)
                record = {"case": name, "expected_diagnostic_outcome": expected,
                          "expectation_met": job.get("outcome") == expected if expected else None,
                          "elapsed_seconds": round(time.monotonic()-started, 2), "job": job}
                reports.append(record)
                (destination / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"case": name, "outcome": job.get("outcome"), "error": job.get("error"),
                                  "findings": (job.get("result") or {}).get("findings")}, ensure_ascii=False), flush=True)
                if job.get("outcome") == "error":
                    break
            print(destination / "report.json", flush=True)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
