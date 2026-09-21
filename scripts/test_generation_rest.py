"""Sequential real Anima REST smoke. Starts only the Generation HTTP app.

Requires a running, idle ComfyUI with Anima and the example models/LoRAs.
Never interrupts/restarts ComfyUI. This is a developer test, not the product CLI.
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

from atelierx.generation import create_app


async def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "artifacts/generation-rest" / time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True)
    token = secrets.token_urlsafe(32)
    app = create_app(directory / "state", "http://127.0.0.1:8188", token, .5)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{runner.addresses[0][1]}"
    report = {"generation_url": base, "tests": []}
    try:
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            async with client.get("http://127.0.0.1:8188/queue") as response:
                queue = await response.json()
                if queue["queue_running"] or queue["queue_pending"]:
                    raise RuntimeError("ComfyUI busy; no test jobs submitted")
            async with client.get(base + "/v1/nodes") as response:
                assert response.status == 200, await response.text()
            template = json.loads((root / "custom_nodes/atelierx_anima/examples/anima-lora-preview.api.json").read_text())
            inputs = template["prompt"]["1"]["inputs"]
            loras = json.loads(inputs.pop("lora_stack"))
            # Seeds differ from prior tests to exercise inference, not cached output.
            for name, adapters in (("anima-base", []), ("anima-multi-lora", loras)):
                value = dict(inputs, loras=adapters, seed=secrets.randbelow(2**32))
                key = str(uuid.uuid4())
                async with client.post(base + "/v1/nodes/anima/jobs", json={"inputs": value},
                                       headers={"Idempotency-Key": key}) as response:
                    job = await response.json()
                    assert response.status == 202, job
                print(f'{name}: accepted {job["job_id"]}', flush=True)
                async with client.post(base + "/v1/nodes/anima/jobs", json={"inputs": value},
                                       headers={"Idempotency-Key": key}) as response:
                    duplicate = await response.json()
                    assert response.status == 200 and duplicate["job_id"] == job["job_id"]
                async with client.post(base + "/v1/nodes/anima/jobs", json={"inputs": dict(value, seed=value["seed"]+1)},
                                       headers={"Idempotency-Key": key}) as response:
                    assert response.status == 409
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline:
                    async with client.get(base + "/v1/jobs/" + job["job_id"]) as response:
                        job = await response.json()
                    if job["state"] in ("completed", "failed"):
                        break
                    await asyncio.sleep(1)
                assert job["state"] == "completed", job
                item = job["images"][0]
                async with client.get(base + item["url"]) as response:
                    assert response.status == 200
                    data = await response.read()
                assert data[:8] == b"\x89PNG\r\n\x1a\n"
                assert struct.unpack(">II", data[16:24]) == (value["width"], value["height"])
                assert hashlib.sha256(data).hexdigest() == item["sha256"]
                (directory / f"{name}.png").write_bytes(data)
                report["tests"].append({"name": name, "job": job, "duplicate": "same job", "conflict": 409,
                                        "png_dimensions_and_hash": "passed"})
                (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(f'{name}: completed; PNG {value["width"]}x{value["height"]}, SHA-256 verified', flush=True)
        print(str(directory / "report.json"), flush=True)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
