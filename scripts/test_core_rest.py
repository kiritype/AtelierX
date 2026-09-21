"""Real Core → Generation → ComfyUI → Core SQLite/image API smoke.

Uses isolated artifact data, never modifies user categories or restarts ComfyUI.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import struct
import time
import uuid

import aiohttp
from aiohttp import web

from atelierx.core import create_app as core_app
from atelierx.generation import create_app as generation_app


async def start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


async def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "artifacts/core-rest" / time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True)
    token = secrets.token_urlsafe(32)
    gen_runner, gen_url = await start(generation_app(directory / "generation", "http://127.0.0.1:8188", token, .5))
    core_runner, core_url = await start(core_app(directory / "core.sqlite3", gen_url, token, poll=.5))
    try:
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            async def call(method, path, body=None, status=200, key=None):
                async with client.request(method, core_url + path, json=body,
                        headers={"Idempotency-Key": key} if key else {}) as response:
                    result = await response.json()
                    assert response.status == status, (response.status, result)
                    return result

            async with client.get("http://127.0.0.1:8188/queue") as response:
                queue = await response.json()
                if queue["queue_running"] or queue["queue_pending"]:
                    raise RuntimeError("ComfyUI busy; no generation submitted")
            work = await call("POST", "/v1/works", {"name": "AtelierX Core REST test"}, 201)
            character = await call("POST", "/v1/characters", {"name": "Test character", "parent_id": work["id"]}, 201)
            outfit = await call("POST", "/v1/outfits", {"name": "Portrait outfit", "parent_id": character["id"],
                        "components": {"appearance": "an adult woman, silver hair, blue eyes, hairpin",
                                       "upper": "white high-neck shirt, blue jacket, brooch",
                                       "lower": "black trousers, black boots, waist chain"}}, 201)
            await call("PATCH", "/v1/settings", {"revision": 1,
                "positive_quality": "masterpiece, very aesthetic, detailed anime illustration",
                "negative": "blurry, low quality"})
            group = await call("POST", "/v1/groups", {"outfit_id": outfit["id"]}, 201)
            source = json.loads((root / "custom_nodes/atelierx_anima/examples/anima-preview.api.json").read_text())
            inputs = source["prompt"]["1"]["inputs"]
            for name in ("positive_prompt", "negative_prompt", "lora_stack"):
                inputs.pop(name, None)
            inputs.update(seed=secrets.randbelow(2**32), width=768, height=1024)
            body = dict(group_id=group["id"], framing="upper_body", expression="calm smile",
                        situation="studio portrait", generation_inputs=inputs)
            preview = await call("POST", "/v1/prompts/preview", body)
            prompt = preview["snapshot"]["generation_inputs"]["positive_prompt"]
            assert "boots" not in prompt and "waist chain" not in prompt and work["name"] not in prompt
            body["preview_hash"] = preview["preview_hash"]
            key = str(uuid.uuid4())
            task = await call("POST", "/v1/tasks", body, 202, key)
            print(f'Core accepted {task["id"]}; lower/footwear excluded', flush=True)
            duplicate = await call("POST", "/v1/tasks", body, 200, key)
            assert duplicate["id"] == task["id"]
            for _ in range(600):
                task = await call("GET", "/v1/tasks/" + task["id"])
                if task["state"] in ("generated", "failed"):
                    break
                await asyncio.sleep(1)
            assert task["state"] == "generated", task
            assert task["validation"] == {"state": "not_requested", "outcome": None}
            item = task["images"][0]
            async with client.get(core_url + "/v1/images/" + item["id"] + "/content") as response:
                assert response.status == 200, await response.text() if response.status != 200 else ""
                data = await response.read()
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
            assert struct.unpack(">II", data[16:24]) == (768, 1024)
            (directory / "core-generated.png").write_bytes(data)
            # Restart Core against the same SQLite database, preserving its endpoint snapshot.
            await core_runner.cleanup()
            core_runner, core_url = await start(core_app(directory / "core.sqlite3", gen_url, token, poll=.5))
            persisted = await call("GET", "/v1/tasks/" + task["id"])
            assert persisted == task
            assert (await call("POST", "/v1/tasks", body, 200, key))["id"] == task["id"]
            report = {"task": task, "preview": preview, "checks": ["category CRUD", "prompt composition",
                    "lower/footwear exclusion", "real generation", "image hash/dimensions", "SQLite restart",
                    "idempotent submission", "validation not misreported"]}
            (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f'Core generated and persisted; restart verified: {directory / "report.json"}', flush=True)
    finally:
        await core_runner.cleanup()
        await gen_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
