"""Sequential live ComfyUI test using a saved Generation image and Core GPU broker."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import time
import aiohttp
from aiohttp import web
from atelierx.core import create_app as core_app
from atelierx.generation import create_app as generation_app, SERVICE

async def start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path, help="Prior integration artifact containing generation/jobs and images")
    parser.add_argument("--all-stages", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = root / "artifacts/independent-postprocess-rest" / time.strftime("%Y%m%d-%H%M%S")
    generation_dir = destination / "generation"
    (generation_dir / "jobs").mkdir(parents=True)
    (generation_dir / "images").mkdir()
    source = next(job for p in sorted((args.source / "generation/jobs").glob("*.json")) if (job := json.loads(p.read_text(encoding="utf-8")))["state"] == "completed")
    source["gpu_requested"] = False
    (generation_dir / "jobs" / (source["job_id"] + ".json")).write_text(json.dumps(source), encoding="utf-8")
    for image in source["images"]:
        filename = image["image_id"] + "." + image["media_type"].split("/")[-1]
        shutil.copy2(args.source / "generation/images" / filename, generation_dir / "images" / filename)
    token, runners, reports = secrets.token_urlsafe(32), [], []
    try:
        app = generation_app(generation_dir, "http://127.0.0.1:8188", token, .2)
        runner, gen_url = await start(app); runners.append(runner)
        runner, core_url = await start(core_app(destination / "core.sqlite3", gen_url, token, poll=.2,
            gpu_config={"comfy_url": "http://127.0.0.1:8188", "lmstudio_url": "http://localhost:1234", "model": "qwen3-vl-8b-instruct-abliterated"}))
        runners.append(runner)
        app[SERVICE].coordinator_url = core_url
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            for image in source["images"]:
                pipeline = {"encode": {"webp_enabled": True}}
                if args.all_stages:
                    pipeline.update(detailer={"seed": 2026091322, "cfg": 4.5, "denoise": .35},
                        censor={"segmentation_model": "ntd11_anime_nsfw_segm_v5-variant1.pt", "labels": "nipples,pussy,penis,anus,testicles,x-ray,cross-section", "treatment": "mosaic"},
                        alpha={"segmentation_model": "person_yolov8n-seg.pt"})
                async with client.post(gen_url + "/v1/images/" + image["image_id"] + "/postprocess-jobs", json={"postprocess": pipeline}, headers={"Idempotency-Key": image["image_id"]}) as response:
                    job = await response.json()
                    assert response.status == 202, job
                for _ in range(600):
                    async with client.get(gen_url + "/v1/jobs/" + job["job_id"]) as response: job = await response.json()
                    if job["state"] in {"completed", "failed", "cancelled"}: break
                    await asyncio.sleep(1)
                reports.append(job)
                (destination / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
                assert job["state"] == "completed", job
                assert job["source_sha256"] == image["sha256"] and job["inputs"] == source["inputs"]
                for output in job["images"]:
                    async with client.get(gen_url + output["url"]) as response: data = await response.read()
                    assert hashlib.sha256(data).hexdigest() == output["sha256"]
                print(image["media_type"] + ": independent " + ("all stages" if args.all_stages else "encode") + " passed", flush=True)
            for _ in range(100):
                async with client.get(core_url + "/v1/gpu") as response: gpu = await response.json()
                if gpu["owner"] is None and not gpu["waiting"]: break
                await asyncio.sleep(.2)
            assert gpu["owner"] is None and not gpu["waiting"], gpu
            reports.append({"gpu_after": gpu})
            (destination / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
            print(str(destination / "report.json"), flush=True)
    finally:
        for runner in reversed(runners): await runner.cleanup()

if __name__ == "__main__": asyncio.run(main())
