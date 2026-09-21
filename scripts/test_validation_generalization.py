"""Held-out existing images: fixed expectations recorded BEFORE real VLM calls."""
import asyncio
import json
from pathlib import Path
import secrets
import time

import aiohttp
from aiohttp import web

from atelierx.validation import create_app


async def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "artifacts/generation-rest/20260913-033051"
    originals = {row["name"]: row["job"] for row in json.loads((source / "report.json").read_text(encoding="utf-8"))["tests"]}
    cases = []

    def add(name, image_name, positive=None, negative=None, expected="failed", rationale=""):
        job = originals[image_name]
        cases.append({"name": name, "image": image_name + ".png", "expected": expected, "rationale": rationale,
                      "actual_generation_prompt": positive is None and negative is None,
                      "generation_job_id": job["job_id"], "positive_prompt": positive if positive is not None else job["inputs"]["positive_prompt"],
                      "negative_prompt": negative if negative is not None else job["inputs"]["negative_prompt"],
                      "negative_sources": {"global": job["inputs"]["negative_prompt"], "character": ""} if negative is None else {"global": "", "character": negative}})

    add("base-original", "anima-base", expected="passed", rationale="Clothed adult anime portrait; original prompt matches inspected image")
    add("base-small-accessories", "anima-base", positive="anime illustration, upper body, eyeglasses, dangling earring", negative="", expected="passed", rationale="Glasses and dangling earring both visibly present")
    add("base-weighted-compound", "anima-base", positive="anime illustration, (eyeglasses, dangling earring:1.2)", negative="", expected="passed", rationale="Same visible accessories expressed as one weighted compound clause")
    add("base-missing-hat", "anima-base", positive="anime illustration, upper body, wearing a large red hat", negative="", rationale="No hat anywhere in image")
    add("base-wrong-hair", "anima-base", positive="anime illustration, bright green hair", negative="", rationale="Visible orange/brown hair differs from green")
    add("lora-original", "anima-multi-lora", expected="passed", rationale="Clothed adult anime portrait; original prompt matches inspected image")
    add("lora-occluded-eye", "anima-multi-lora", positive="anime illustration, both eyes fully visible and not covered by hair", negative="", rationale="Hair covers most of one eye; explicit both-eyes requirement fails")
    add("lora-cropped-boots", "anima-multi-lora", positive="anime illustration, clearly visible black boots", negative="", rationale="Image ends around thighs; boots cannot be seen")
    add("lora-prohibited-blue-clothing", "anima-multi-lora", positive="anime illustration", negative="blue clothing", rationale="Blue outer garment visibly present")

    destination = root / "artifacts/validation-generalization" / time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True)
    (destination / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    config = json.loads((root / ".atelierx/validation-config.json").read_text(encoding="utf-8"))
    provider = config["providers"]["local-vision"]
    if provider["url"].rstrip("/") not in {"http://localhost:1234/v1", "http://127.0.0.1:1234/v1"}:
        raise RuntimeError("Only the authorized local LM Studio endpoint is supported")
    profile = config["profiles"]["single-default"]
    token = secrets.token_urlsafe(32)
    runner = web.AppRunner(create_app(destination / "validation", token, providers={"local-vision": provider}, profiles={profile["profile_id"]: profile}, poll=.1))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    results, uploads = [], {}
    try:
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            for case in cases:
                async with client.get("http://127.0.0.1:8188/queue") as response:
                    queue = await response.json()
                    if queue["queue_running"] or queue["queue_pending"]:
                        raise RuntimeError("ComfyUI busy; no concurrent VLM test")
                if case["image"] not in uploads:
                    data = (source / case["image"]).read_bytes()
                    (destination / case["image"]).write_bytes(data)
                    async with client.post(url + "/v1/uploads", data=data) as response:
                        assert response.status == 201
                        uploads[case["image"]] = await response.json()
                upload = uploads[case["image"]]
                body = {"image": {"ref": case["image"].replace(".png", ""), "source": {"type": "upload", "upload_id": upload["upload_id"], "sha256": upload["sha256"]},
                                  "positive_prompt": case["positive_prompt"], "negative_prompt": case["negative_prompt"], "negative_sources": case["negative_sources"]},
                        "generation_attempt_id": case["generation_job_id"] if case["actual_generation_prompt"] else None,
                        "profile": profile, "provider": {"provider_id": "local-vision", **{key: provider[key] for key in ("model", "revision", "timeout_seconds")}},
                        "expected_output": {"width": 768, "height": 1024, "media_type": "image/png", "alpha": "not_required"}}
                started = time.monotonic()
                async with client.post(url + "/v1/validations/single", json=body, headers={"Idempotency-Key": case["name"]}) as response:
                    job = await response.json()
                    assert response.status == 202, job
                print(case["name"] + ": submitted", flush=True)
                for _ in range(240):
                    async with client.get(url + "/v1/validation-jobs/" + job["job_id"]) as response:
                        job = await response.json()
                    if job["state"] in {"completed", "failed"}: break
                    await asyncio.sleep(1)
                result = {"case": case["name"], "expected": case["expected"], "actual": job.get("outcome"),
                          "correct": job.get("outcome") == case["expected"], "seconds": round(time.monotonic()-started, 2), "job": job}
                results.append(result)
                (destination / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({key: result[key] for key in ("case", "expected", "actual", "correct", "seconds")}), flush=True)
                if job.get("outcome") == "error":
                    print(json.dumps(job["error"]), flush=True)
            print(str(destination / "report.json"), flush=True)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
