"""Operator-run real Anima 1024px -> default UltraSharp 1536px REST smoke.

It starts isolated Core, Generation, Validation and a contract-only local VLM
stub.  Only ComfyUI performs real inference.  The request deliberately omits
``postprocess``: Core must add its agreed default upscale and PNG/WebP encode
snapshot. The stub does not judge image quality, but Validation still fetches
and decodes both real 1536px outputs, enforcing frozen expected dimensions.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from PIL import Image

from atelierx.core import create_app as core_app
from atelierx.generation import SERVICE as GEN_SERVICE
from atelierx.generation import create_app as generation_app
from atelierx.validation import create_app as validation_app


async def start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def local_http_url(value, name):
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError(f"{name} must be an http localhost URL")
    return value.rstrip("/")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", default=None)
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--lmstudio-url", default="http://127.0.0.1:1234")
    parser.add_argument("--validation-config", default=".atelierx/validation-config.json")
    parser.add_argument("--seed", type=int, default=2026091319)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    comfy_url = local_http_url(args.comfy_url, "--comfy-url")
    lmstudio_url = local_http_url(args.lmstudio_url, "--lmstudio-url")
    root = Path(__file__).resolve().parents[1]
    destination = Path(args.run_root) if args.run_root else root / "artifacts/upscale-default-rest" / time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=False)
    token, runners = secrets.token_urlsafe(32), []
    managed_provider = json.loads((root / args.validation_config).read_text(encoding="utf-8"))["providers"]["local-vision"]
    report = {"started_at": time.time(), "seed": args.seed, "mode": "real ComfyUI image + contract-only local VLM"}

    def save():
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    provider = web.Application(client_max_size=128 * 1024 * 1024)

    async def completion(request):
        body = await request.json()
        parts = [part for message in body["messages"] if isinstance(message.get("content"), list)
                 for part in message["content"] if part.get("type") == "image_url"]
        assert len(parts) == 1
        payload = base64.b64decode(parts[0]["image_url"]["url"].split(",", 1)[1])
        image = Image.open(io.BytesIO(payload)); image.load()
        report["provider_image"] = {"sha256": hashlib.sha256(payload).hexdigest(), "size": list(image.size)}
        checks = json.loads(body["messages"][1]["content"][0]["text"].split(": ", 1)[1])
        answer = {"assessments": [{"id": check["id"], "status": "matched", "observed": "transport smoke", "location": "center"}
                                  for check in checks]}
        return web.json_response({"choices": [{"message": {"content": json.dumps(answer)}}]})

    provider.router.add_post("/v1/chat/completions", completion)
    profile = {"profile_id": "upscale-default", "revision": 1, "output_conditions": True,
               "positive_prompt": True, "negative_prompt": True, "body_parts": [], "metadata": False, "consistency": False}
    provider_config = {"provider_id": "upscale-stub", "revision": 1, "url": None,
                       "api_key": "operator-run-stub", "model": "contract-only", "timeout_seconds": 30,
                       "response_format": "json_schema", "image_format": "png"}
    try:
        runner, provider_url = await start(provider); runners.append(runner)
        provider_config["url"] = provider_url + "/v1"
        generation = generation_app(destination / "generation", comfy_url, token, .25)
        runner, generation_url = await start(generation); runners.append(runner)
        validation = validation_app(destination / "validation", token, providers={"upscale-stub": provider_config},
                                    generation_sources={"generation-local": {"url": generation_url, "token": token}},
                                    profiles={profile["profile_id"]: profile}, poll=.2)
        runner, validation_url = await start(validation); runners.append(runner)
        gpu_config = {"comfy_url": comfy_url, "lmstudio_url": lmstudio_url, "model": managed_provider["model"]}
        core = core_app(destination / "core.sqlite3", generation_url, token, poll=.25,
                        validation_config={"url": validation_url, "generation_server_id": "generation-local",
                                           "providers": {"upscale-stub": provider_config}, "profiles": {profile["profile_id"]: profile}},
                        gpu_config=gpu_config)
        runner, core_url = await start(core); runners.append(runner)
        generation[GEN_SERVICE].coordinator_url = core_url
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            async def call(method, path, body=None, expected=200, key=None):
                headers = {"Idempotency-Key": key} if key else {}
                async with client.request(method, core_url + path, json=body, headers=headers) as response:
                    value = await response.json()
                    assert response.status == expected, (method, path, response.status, value)
                    return value

            async with client.get(comfy_url + "/queue") as response:
                queue = await response.json()
            assert response.status == 200 and not queue["queue_running"] and not queue["queue_pending"], "ComfyUI busy: no interference"
            report["comfy_preflight"] = queue
            settings = await call("GET", "/v1/settings")
            settings = await call("PATCH", "/v1/settings", {"revision": settings["revision"],
                                                                 "auto_regeneration_enabled": False, "max_auto_regenerations": 0})
            assert settings["auto_regeneration_enabled"] is False and settings["max_auto_regenerations"] == 0
            report["generation_settings"] = settings
            work = await call("POST", "/v1/works", {"name": "Upscale default smoke"}, 201)
            character = await call("POST", "/v1/characters", {"name": "Safe adult", "parent_id": work["id"], "negative_prompt": ""}, 201)
            outfit = await call("POST", "/v1/outfits", {"name": "Portrait", "parent_id": character["id"], "components": {
                "appearance": "adult woman, silver hair, blue eyes", "upper": "white shirt", "lower": ""}}, 201)
            group = await call("POST", "/v1/groups", {"outfit_id": outfit["id"]}, 201)
            template = json.loads((root / "custom_nodes/atelierx_anima/examples/anima-preview.api.json").read_text(encoding="utf-8"))["prompt"]["1"]["inputs"]
            inputs = {key: value for key, value in template.items() if key not in {"positive_prompt", "negative_prompt", "lora_stack", "width", "height"}}
            inputs.update(seed=args.seed)
            # No postprocess key: this is the default-policy assertion.
            task = await call("POST", "/v1/tasks", {"group_id": group["id"], "framing": "upper_body", "expression": "calm smile",
                                                       "situation": "studio portrait", "generation_inputs": inputs,
                                                       "validation": {"profile_id": profile["profile_id"], "provider_id": "upscale-stub"}}, 202, "upscale-default")
            snapshot = task["snapshot"]
            assert snapshot["generation_inputs"]["width"] == snapshot["generation_inputs"]["height"] == 1024
            assert snapshot["postprocess"]["upscale"] == {"upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5}
            assert snapshot["postprocess"]["encode"]["webp_enabled"] is True
            report["task_accepted"] = task; save()
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                task = await call("GET", "/v1/tasks/" + task["id"])
                if task["state"] in {"generated", "failed", "cancelled"}:
                    break
                await asyncio.sleep(1)
            assert task["state"] == "generated", task
            assert {image["media_type"] for image in task["images"]} == {"image/png", "image/webp"}, task
            report["output"] = []
            for output in task["images"]:
                async with client.get(core_url + "/v1/images/" + output["id"] + "/content") as response:
                    assert response.status == 200
                    data = await response.read()
                image = Image.open(io.BytesIO(data)); image.load()
                assert image.size == (1536, 1536), image.size
                report["output"].append({"image_id": output["id"], "media_type": output["media_type"],
                                           "sha256": hashlib.sha256(data).hexdigest(), "size": list(image.size)})
            deadline = time.monotonic() + args.timeout
            runs = []
            while time.monotonic() < deadline:
                runs = []
                for output in task["images"]:
                    rows = await call("GET", "/v1/images/" + output["id"] + "/validations")
                    if rows["items"]:
                        runs.append(rows["items"][0])
                if len(runs) == len(task["images"]) and all(run["state"] in {"completed", "failed", "cancelled"} for run in runs):
                    break
                await asyncio.sleep(1)
            assert len(runs) == len(task["images"]) and all(run["state"] == "completed" and run["outcome"] == "passed" for run in runs), runs
            assert all(run["request"]["expected_output"]["width"] == run["request"]["expected_output"]["height"] == 1536 for run in runs), runs
            report["validation"] = runs
            report["finished_at"] = time.time(); save()
            print(destination / "report.json", flush=True)
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        report["finished_at"] = time.time(); save()
        raise
    finally:
        for runner in reversed(runners):
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
