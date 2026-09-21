"""Real Core/Generation/ComfyUI images + Validation, mock or local LM Studio.

This checks transport and durable result orchestration, not VLM judgment quality.
Services use isolated local ports/data and ComfyUI GPU jobs run sequentially.
--real-vlm uses configured LM Studio and checks PNG/WebP plus Core restart;
an image-quality failure is a valid result, a provider error fails the test.
"""
import asyncio
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import time

import aiohttp
from aiohttp import web
from PIL import Image

from atelierx.core import create_app as core_app
from atelierx.generation import create_app as generation_app
from atelierx.validation import create_app as validation_app
from atelierx.generation import SERVICE as GEN_SERVICE
from atelierx.validation import SERVICE as VAL_SERVICE


async def start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="encode,alpha,censor,detailer,all")
    parser.add_argument("--real-vlm", action="store_true", help="Use local LM Studio; unload its idle model before starting")
    parser.add_argument("--seed", type=int, default=123456)
    parser.add_argument("--character-negative", default="")
    parser.add_argument("--automatic", action="store_true", help="Core follow-up and shared GPU coordinator")
    parser.add_argument("--manual-regeneration", action="store_true")
    parser.add_argument("--group-validation", action="store_true")
    parser.add_argument("--group-replacement", action="store_true")
    args = parser.parse_args()
    if args.group_replacement and not args.group_validation: parser.error("--group-replacement requires --group-validation")
    if args.group_validation and not args.manual_regeneration: parser.error("--group-validation requires --manual-regeneration")
    group_profile = {"profile_id": "group-default", "revision": 1, "consistency": True}
    if args.manual_regeneration and not args.automatic: parser.error("--manual-regeneration requires --automatic")
    if args.automatic and not args.real_vlm: parser.error("--automatic requires --real-vlm")
    root = Path(__file__).resolve().parents[1]
    destination = root / "artifacts/backend-pipeline-rest" / time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True)
    token, runners, reports = secrets.token_urlsafe(32), [], []
    mode, provider_calls = "pass", []
    provider = web.Application()

    async def completion(request):
        body = await request.json()
        images = [part for message in body["messages"] if isinstance(message["content"], list)
                  for part in message["content"] if part.get("type") == "image_url"]
        assert len(images) == 1
        data = base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1])
        image = Image.open(io.BytesIO(data)); image.load()
        provider_calls.append({"model": body["model"], "image_sha256": hashlib.sha256(data).hexdigest(), "size": image.size})
        checks = json.loads(body["messages"][1]["content"][0]["text"].split(": ", 1)[1])
        answer = {"assessments": [{"id": check["id"], "status": "matched", "observed": "MOCK transport test only", "location": "center"} for check in checks]}
        return web.json_response({"choices": [{"message": {"content": json.dumps(answer) if mode == "pass" else "invalid mock JSON"}}]})

    provider.router.add_post("/chat/completions", completion)
    profile = {"profile_id": "integration", "revision": 1, "output_conditions": True,
               "positive_prompt": True, "negative_prompt": True, "body_parts": [], "metadata": False, "consistency": False}
    provider_snapshot = {"provider_id": "mock", "revision": 1, "model": "mock-vision-contract-only", "timeout_seconds": 10}
    try:
        if args.real_vlm:
            config = json.loads((root / ".atelierx/validation-config.json").read_text(encoding="utf-8"))
            provider_config = config["providers"]["local-vision"]
            if args.automatic: provider_config = dict(provider_config, shared_gpu=True)
            assert provider_config["url"].rstrip("/") in {"http://localhost:1234/v1", "http://127.0.0.1:1234/v1"}
            provider_snapshot = {"provider_id": "local-vision", **{key: provider_config[key] for key in ("revision", "model", "timeout_seconds")}}
            profile = config["profiles"]["single-default"]
        else:
            runner, provider_url = await start(provider); runners.append(runner)
            provider_config = {**provider_snapshot, "url": provider_url, "api_key": "mock-only"}
        provider_id, profile_id = provider_snapshot["provider_id"], profile["profile_id"]
        gen_app = generation_app(destination / "generation", "http://127.0.0.1:8188", token, .2)
        runner, gen_url = await start(gen_app); runners.append(runner)
        val_app = validation_app(destination / "validation", token,
            providers={provider_id: provider_config},
            generation_sources={"generation-local": {"url": gen_url, "token": token}},
            profiles={profile_id: profile, "group-default": group_profile}, poll=.1)
        runner, val_url = await start(val_app); runners.append(runner)
        gpu_config = {"comfy_url": "http://127.0.0.1:8188", "lmstudio_url": "http://localhost:1234", "model": provider_snapshot["model"]} if args.automatic else None
        runner, core_url = await start(core_app(destination / "core.sqlite3", gen_url, token, poll=.2,
            validation_config={"url": val_url, "profiles": {profile_id: profile, "group-default": group_profile}, "providers": {provider_id: provider_snapshot}}, gpu_config=gpu_config)); runners.append(runner)
        if args.automatic:
            gen_app[GEN_SERVICE].coordinator_url = core_url
            val_app[VAL_SERVICE].coordinator_url = core_url
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
            async def call(method, path, body=None, expected=200, key=None):
                async with client.request(method, core_url + path, json=body, headers={"Idempotency-Key": key} if key else {}) as response:
                    value = await response.json()
                    assert response.status == expected, (response.status, value)
                    return value

            work = await call("POST", "/v1/works", {"name": "REST test"}, 201)
            character = await call("POST", "/v1/characters", {"name": "Test adult", "parent_id": work["id"], "negative_prompt": args.character_negative}, 201)
            outfit = await call("POST", "/v1/outfits", {"name": "Portrait", "parent_id": character["id"], "components": {
                "appearance": "an adult woman, silver hair, blue eyes, hairpin",
                "upper": "white high-neck shirt, blue jacket, brooch", "lower": "black trousers, boots"}}, 201)
            group = await call("POST", "/v1/groups", {"outfit_id": outfit["id"]}, 201)
            await call("PATCH", "/v1/settings", {"revision": 1, "positive_quality": "masterpiece, detailed anime illustration", "negative": "blurry, low quality"})
            template = json.loads((root / "custom_nodes/atelierx_anima/examples/anima-preview.api.json").read_text())["prompt"]["1"]["inputs"]
            inputs = {key: value for key, value in template.items() if key not in {"positive_prompt", "negative_prompt", "lora_stack"}}
            inputs.update(seed=args.seed, width=768, height=1024)
            encode = {"webp_enabled": True, "webp_quality": 90}
            censor = {"segmentation_model": "ntd11_anime_nsfw_segm_v5-variant1.pt",
                      "labels": "nipples,pussy,penis,anus,testicles,x-ray,cross-section", "treatment": "mosaic"}
            alpha = {"segmentation_model": "person_yolov8n-seg.pt"}
            detailer = {"seed": args.seed, "cfg": 4.5, "denoise": .35}
            cases = [("encode", {"encode": encode}), ("alpha", {"alpha": alpha, "encode": encode}),
                     ("censor", {"censor": censor, "encode": encode}), ("detailer", {"detailer": detailer, "encode": encode}),
                     ("all", {"detailer": detailer, "censor": censor, "alpha": alpha, "encode": encode})]
            for name, pipeline in cases:
                if name not in args.cases.split(","):
                    continue
                async with client.get("http://127.0.0.1:8188/queue") as response:
                    queue = await response.json()
                    assert not queue["queue_running"] and not queue["queue_pending"], "ComfyUI busy: no interference"
                task = await call("POST", "/v1/tasks", {"group_id": group["id"], "framing": "upper_body", "expression": "calm smile",
                    "situation": "studio portrait", "generation_inputs": inputs, "postprocess": pipeline,
                    **({"validation": {"provider_id": provider_id, "profile_id": profile_id}} if args.automatic else {})}, 202, name)
                print(f'{name}: Core accepted {task["id"]}', flush=True)
                for _ in range(600):
                    task = await call("GET", "/v1/tasks/" + task["id"])
                    if task["state"] in {"generated", "failed"}: break
                    await asyncio.sleep(1)
                reports.append({"name": name, "task": task})
                (destination / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
                assert task["state"] == "generated", task
                assert {item["media_type"] for item in task["images"]} == {"image/png", "image/webp"}
                for item in task["images"]:
                    async with client.get(core_url + "/v1/images/" + item["id"] + "/content") as response:
                        assert response.status == 200
                        data = await response.read()
                    assert hashlib.sha256(data).hexdigest() == item["sha256"]
                    image = Image.open(io.BytesIO(data)); image.load()
                    assert image.size == (768, 1024)
                    (destination / (name + "." + item["media_type"].split("/")[1])).write_bytes(data)
                print(name + ": PNG/WebP success", flush=True)

            if args.real_vlm:
                async with client.get("http://127.0.0.1:8188/queue") as response:
                    queue = await response.json()
                    assert not queue["queue_running"] and not queue["queue_pending"], "ComfyUI busy"
                if not args.automatic:
                    async with client.post("http://127.0.0.1:8188/free", json={"unload_models": True, "free_memory": True}) as response:
                        assert response.status == 200
                    await asyncio.sleep(3)
                saved_runs = []
                for item in task["images"]:
                    key = "auto:" + task["id"] + ":" + item["id"] if args.automatic else "real-" + item["media_type"]
                    selection = {"provider_id": provider_id, "profile_id": profile_id}
                    if args.automatic:
                        for _ in range(100):
                            existing = await call("GET", "/v1/images/" + item["id"] + "/validations")
                            if existing["items"]: break
                            await asyncio.sleep(.2)
                        assert existing["items"], "Core did not enqueue automatic validation"
                        run = existing["items"][0]
                    else:
                        run = await call("POST", "/v1/images/" + item["id"] + "/validations", selection, 202, key)
                    print(key + ": real VLM submitted", flush=True)
                    for _ in range(300):
                        run = await call("GET", "/v1/validation-runs/" + run["id"])
                        if run["state"] in {"completed", "failed"}: break
                        await asyncio.sleep(1)
                    reports.append({"name": key, "run": run})
                    (destination / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
                    assert run["state"] == "completed" and run["outcome"] in {"passed", "failed"}, run
                    payload = run["request"]
                    assert payload["image"]["source"]["sha256"] == item["sha256"]
                    for field in ("positive_prompt", "negative_prompt"):
                        assert payload["image"][field] == task["snapshot"]["generation_inputs"][field]
                    image_record = await call("GET", "/v1/images/" + item["id"])
                    assert image_record["validation"]["outcome"] == run["outcome"]
                    duplicate = await call("POST", "/v1/images/" + item["id"] + "/validations", selection, 200, key)
                    assert duplicate["id"] == run["id"]
                    saved_runs.append((item, key, run))
                    print(key + ": " + run["outcome"] + "; image hash, prompt, Core result verified", flush=True)
                if args.manual_regeneration:
                    original_id = task["id"]
                    child = await call("POST", "/v1/tasks/" + original_id + "/regenerations", {}, 202, "live-manual")
                    for _ in range(900):
                        child = await call("GET", "/v1/tasks/" + child["id"])
                        cycle = await call("GET", "/v1/regeneration-cycles/" + child["regeneration"]["cycle_id"])
                        if cycle["state"] != "active": break
                        await asyncio.sleep(1)
                    assert cycle["state"] == "passed", cycle
                    assert child["state"] == "generated" and cycle["used"] == 0, child
                    assert child["regeneration"]["parent_task_id"] == original_id
                    assert child["id"] != original_id and child["regeneration"]["cycle_id"] != task["regeneration"]["cycle_id"]
                    for item in child["images"]:
                        child_runs = (await call("GET", "/v1/images/" + item["id"] + "/validations"))["items"]
                        assert len(child_runs) == 1 and child_runs[0]["outcome"] == "passed", child_runs
                        saved_runs.append((item, "auto:" + child["id"] + ":" + item["id"], child_runs[0]))
                    reports.append({"manual_regeneration": child, "cycle": cycle})
                    print("manual regeneration: new task/image IDs, zero automatic usage, PNG/WebP validation passed", flush=True)
                if args.group_validation:
                    reference_image = next(i for i in task["images"] if i["media_type"] == "image/png")
                    target_image = next(i for i in child["images"] if i["media_type"] == "image/png")
                    group = await call("PUT", "/v1/groups/" + task["group_id"] + "/reference", {
                        "revision": 0, "representative_id": reference_image["id"], "auxiliary_ids": []})
                    group_run = await call("POST", "/v1/groups/" + group["id"] + "/validations", {
                        "reference_revision": 1, "target_ids": [target_image["id"]],
                        "validation": {"profile_id": "group-default", "provider_id": provider_id}}, 202, "live-group")
                    for _ in range(600):
                        group_run = await call("GET", "/v1/group-validation-runs/" + group_run["id"])
                        if group_run["state"] in {"completed", "failed", "cancelled"}: break
                        await asyncio.sleep(1)
                    reports.append({"group_validation": group_run})
                    (destination / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
                    assert group_run["state"] == "completed", group_run
                    assert all(item["status"] != "error" for item in group_run["result"]["items"]), group_run
                    print("group validation: " + group_run["outcome"] + "; frozen reference and evidence verified", flush=True)
                if args.group_replacement:
                    candidate = await call("GET", "/v1/groups/" + group["id"] + "/reference-candidate")
                    replacement_body = {"reference_revision": 1, "target_image_id": target_image["id"],
                        "regeneration": {"generation_inputs": {"seed": 2026091312}, "validation": {"profile_id": profile_id, "provider_id": provider_id}},
                        "group_validation": {"profile_id": "group-default", "provider_id": provider_id}}
                    replacement = await call("POST", "/v1/groups/" + group["id"] + "/replacements", replacement_body, 202, "live-group-replacement")
                    for _ in range(900):
                        replacements = await call("GET", "/v1/groups/" + group["id"] + "/replacements")
                        replacement = next(row for row in replacements["items"] if row["id"] == replacement["id"])
                        if replacement["state"] in {"completed", "error", "failed", "cancelled", "stale_reference"}: break
                        await asyncio.sleep(1)
                    reports.append({"group_replacement": replacement, "reference_candidate": candidate})
                    (destination / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
                    assert replacement["state"] == "completed", replacement
                    replacement_run = await call("GET", "/v1/group-validation-runs/" + replacement["group_run_id"])
                    assert [item["ref"] for item in replacement_run["request"]["targets"]] == [replacement["replacement_image_id"]]
                    assert replacement["replacement_image_id"] != target_image["id"]
                    duplicate = await call("POST", "/v1/groups/" + group["id"] + "/replacements", replacement_body, 200, "live-group-replacement")
                    assert duplicate["id"] == replacement["id"]
                    consistency = await call("GET", "/v1/groups/" + group["id"] + "/consistency")
                    assert target_image["id"] not in consistency["target_ids"]
                    reports.append({"replacement_group_run": replacement_run, "consistency": consistency})
                    print("selected replacement: new image only, single validation then group comparison, no duplicate request", flush=True)
                await runners.pop().cleanup()
                runner, core_url = await start(core_app(destination / "core.sqlite3", gen_url, token, poll=.2,
                    validation_config={"url": val_url, "profiles": {profile_id: profile, "group-default": group_profile}, "providers": {provider_id: provider_snapshot}}, gpu_config=gpu_config))
                runners.append(runner)
                if args.automatic:
                    gen_app[GEN_SERVICE].coordinator_url = core_url
                    val_app[VAL_SERVICE].coordinator_url = core_url
                for item, key, run in saved_runs:
                    restored = await call("GET", "/v1/validation-runs/" + run["id"])
                    assert restored == run
                    duplicate = await call("POST", "/v1/images/" + item["id"] + "/validations", selection, 200, key)
                    assert duplicate["id"] == run["id"]
                if args.group_replacement:
                    restored_replacements = await call("GET", "/v1/groups/" + group["id"] + "/replacements")
                    assert next(row for row in restored_replacements["items"] if row["id"] == replacement["id"]) == replacement
                if args.group_validation:
                    restored_group = await call("GET", "/v1/group-validation-runs/" + group_run["id"])
                    assert restored_group == group_run
                task = await call("GET", "/v1/tasks/" + task["id"])
                assert task["state"] == "generated" and task["automatic_attempts_used"] == 0
                reports.append({"vision_provider": provider_snapshot, "restart_verified": True, "automatic_attempts_used": 0})
                if args.automatic:
                    for _ in range(100):
                        gpu_state = await call("GET", "/v1/gpu")
                        queue_state = await call("GET", "/v1/queue?limit=200")
                        if not gpu_state["owner"] and not gpu_state["waiting"] and all(row["state"] in {"generated", "completed", "failed", "cancelled"} for row in queue_state["items"]): break
                        await asyncio.sleep(.2)
                    assert gpu_state["owner"] is None and gpu_state["waiting"] == [], gpu_state
                    validation_rows = [row for row in queue_state["items"] if row["kind"] == "validation"]
                    assert all(row["state"] == "completed" for row in validation_rows), queue_state
                    reports.append({"automatic": True, "gpu_after": gpu_state, "queue_after": queue_state})
                (destination / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
                print(str(destination / "report.json"), flush=True)
                return

            item = next(item for item in task["images"] if item["media_type"] == "image/png")
            for mode_name in ("pass", "parse-error"):
                mode = mode_name
                run = await call("POST", "/v1/images/" + item["id"] + "/validations",
                                 {"provider_id": "mock", "profile_id": "integration"}, 202, mode_name)
                for _ in range(100):
                    run = await call("GET", "/v1/validation-runs/" + run["id"])
                    if run["state"] in {"completed", "failed"}: break
                    await asyncio.sleep(.2)
                assert run["outcome"] == ("passed" if mode_name == "pass" else "error"), run
                if mode_name == "parse-error": assert run["error"]["code"] == "VAL_PROVIDER_RESPONSE_INVALID"
                reports.append({"name": "MOCK-validation-" + mode_name, "run": run})
            task = await call("GET", "/v1/tasks/" + task["id"])
            assert task["state"] == "generated" and task["automatic_attempts_used"] == 0
            assert len(provider_calls) == 2
            reports.append({"vision_provider": "MOCK, no quality evaluation", "calls": provider_calls})
            (destination / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
            print(str(destination / "report.json"), flush=True)
    finally:
        for runner in reversed(runners): await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
