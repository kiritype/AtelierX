"""Opt-in real GPU smoke for Core's group-independent direct/natural jobs."""
import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import time

import aiohttp
from aiohttp import web
from PIL import Image

from atelierx.core import CORE, create_app as core_app
from atelierx.generation import create_app as generation_app


async def main(args):
    if not args.confirm_exclusive_gpu:
        raise RuntimeError("Confirm that this GPU is available before running the smoke test")
    root = Path(args.run_root)
    root.mkdir(parents=True, exist_ok=False)
    gpu = json.loads(Path(args.gpu_config).read_text(encoding="utf-8"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if config["llm"]["model"] != gpu["model"]:
        raise RuntimeError("Planner and configured GPU model differ")
    os.environ.setdefault(config["llm"]["api_key_env"], gpu.get("api_key", "lm-studio"))
    token = secrets.token_urlsafe(32)
    runners = []
    report = {"started_at": time.time(), "scope": "real Core/Generation/ComfyUI/local LLM, no Discord or Validation", "jobs": []}

    async def start(app):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup(); runners.append(runner)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        return "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get(gpu["comfy_url"].rstrip("/") + "/queue") as response:
            queue = await response.json()
        if queue["queue_running"] or queue["queue_pending"]:
            raise RuntimeError("ComfyUI has existing work; not starting smoke")
        async with session.get(gpu["lmstudio_url"].rstrip("/") + "/api/v1/models",
                               headers={"Authorization": "Bearer " + gpu.get("api_key", "lm-studio")}) as response:
            models = await response.json()
        if any(model.get("loaded_instances") for model in models["models"]):
            raise RuntimeError("A model is already loaded; check user activity before running smoke")
        try:
            generation = generation_app(root / "generation", gpu["comfy_url"], token, poll=.1)
            generation_url = await start(generation)
            core = core_app(root / "core.sqlite3", generation_url, token, gpu_config=gpu,
                            standalone_config=config, poll=.1)
            core_url = await start(core)
            # Set the coordinator before the first job can be submitted.
            from atelierx.generation import SERVICE
            generation[SERVICE].coordinator_url = core_url
            headers = {"Authorization": "Bearer " + token}
            for mode, prompt in [("direct", "A small blue bird perched on a flowering branch, watercolor illustration, white background"),
                                 ("natural", "흰 배경에 꽃이 핀 가지 위에 앉아 있는 작은 파란 새를 수채화 느낌으로 그려줘.")]:
                before = time.monotonic()
                async with session.post(core_url + "/v1/standalone-jobs", headers={**headers, "Idempotency-Key": "smoke-" + mode},
                                        json={"prompt": prompt, "mode": mode}) as response:
                    if response.status != 202:
                        raise RuntimeError("Core standalone request failed: HTTP " + str(response.status))
                    job = await response.json()
                while job["state"] not in {"completed", "failed"} and time.monotonic() - before < args.timeout:
                    await asyncio.sleep(.5)
                    async with session.get(core_url + "/v1/standalone-jobs/" + job["id"], headers=headers) as response:
                        job = await response.json()
                entry = {"mode": mode, "job": job, "seconds": round(time.monotonic() - before, 3)}
                report["jobs"].append(entry)
                if job["state"] != "completed":
                    raise RuntimeError("Standalone " + mode + " did not complete")
                for descriptor in job["images"]:
                    async with session.get(core_url + descriptor["content_url"], headers=headers) as response:
                        if response.status != 200:
                            raise RuntimeError("Image content unavailable")
                        data = await response.read()
                    assert len(data) == descriptor["bytes"] and hashlib.sha256(data).hexdigest() == descriptor["sha256"]
                    with Image.open(io.BytesIO(data)) as image:
                        image.load(); assert image.size == (1536, 1536)
                    suffix = "png" if descriptor["media_type"] == "image/png" else "webp"
                    (root / (mode + "." + suffix)).write_bytes(data)
                for _ in range(40):
                    report["gpu"] = core[CORE].gpu.state()
                    if report["gpu"]["owner"] is None and not report["gpu"]["waiting"]:
                        break
                    await asyncio.sleep(.25)
                assert report["gpu"]["owner"] is None and not report["gpu"]["waiting"]
            report["groups"] = core[CORE].store.db.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
            assert report["groups"] == 0
            report["success"] = True
        finally:
            report["finished_at"] = time.time()
            (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            for runner in reversed(runners):
                await runner.cleanup()
    print(json.dumps({"success": report.get("success", False), "modes": [j["mode"] for j in report["jobs"]],
                      "report": str(root / "report.json")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="examples/standalone-generation.example.json")
    parser.add_argument("--gpu-config", default=".atelierx/gpu-config.json")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--confirm-exclusive-gpu", action="store_true")
    asyncio.run(main(parser.parse_args()))
