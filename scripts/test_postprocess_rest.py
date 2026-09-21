"""Sequential installed-ComfyUI node smoke (separate from Generation API coverage)."""
import asyncio
import io
import json
from pathlib import Path
import time
import uuid

import aiohttp
from PIL import Image, ImageChops


async def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/postprocess-rest" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    reports = []
    async with aiohttp.ClientSession(base_url="http://127.0.0.1:8188", timeout=aiohttp.ClientTimeout(total=60)) as client:
        async with client.get("/object_info") as response:
            info = await response.json()

        async def upload(path):
            form = aiohttp.FormData()
            form.add_field("image", path.read_bytes(), filename=f"atelierx-{uuid.uuid4().hex}.png", content_type="image/png")
            async with client.post("/upload/image", data=form) as response:
                assert response.status == 200, await response.text()
                result = await response.json()
            return (result.get("subfolder", "") + "/" + result["name"]).lstrip("/")

        def workflow(prompt):
            nodes, links = [], []
            for index, (node_id, item) in enumerate(prompt.items()):
                schema = info[item["class_type"]]
                widgets, inputs, outputs = [], [], []
                for name, value in item["inputs"].items():
                    if isinstance(value, list):
                        link_id = len(links) + 1
                        source_type = info[prompt[value[0]]["class_type"]]["output"][value[1]]
                        links.append([link_id, int(value[0]), value[1], int(node_id), len(inputs), source_type])
                        inputs.append({"name": name, "type": source_type, "link": link_id})
                    else:
                        widgets.append(value)
                        if name == "seed":
                            widgets.append("fixed")
                for slot, kind in enumerate(schema.get("output", [])):
                    outputs.append({"name": schema.get("output_name", schema["output"])[slot], "type": kind, "links": []})
                nodes.append({"id": int(node_id), "type": item["class_type"], "pos": [index*340, 100],
                              "size": [310, 360], "flags": {}, "order": index, "mode": 0,
                              "inputs": inputs, "outputs": outputs, "widgets_values": widgets,
                              "properties": {"Node name for S&R": item["class_type"]}})
            by_id = {node["id"]: node for node in nodes}
            for link in links:
                by_id[link[1]]["outputs"][link[2]]["links"].append(link[0])
            return {"last_node_id": max(map(int, prompt)), "last_link_id": len(links), "nodes": nodes,
                    "links": links, "groups": [], "config": {}, "extra": {}, "version": .4}

        async def run(name, prompt, output_id):
            async with client.get("/queue") as response:
                queue = await response.json()
            if queue["queue_running"] or queue["queue_pending"]:
                raise RuntimeError("ComfyUI busy; no interference")
            for node in prompt.values():
                if node["class_type"] not in info:
                    raise RuntimeError(f'Node not installed: {node["class_type"]}')
            prompt_id = str(uuid.uuid4())
            payload = {"prompt": prompt, "prompt_id": prompt_id, "client_id": "atelierx-postprocess-test"}
            (output / f"{name}.api.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            (output / f"{name}.workflow.json").write_text(json.dumps(workflow(prompt), indent=2), encoding="utf-8")
            async with client.post("/prompt", json=payload) as response:
                result = await response.json()
                assert response.status == 200, result
            print(f"{name}: submitted {prompt_id}", flush=True)
            record = None
            for _ in range(600):
                async with client.get("/history/" + prompt_id) as response:
                    record = (await response.json()).get(prompt_id)
                if record:
                    break
                await asyncio.sleep(1)
            assert record, "Timed out waiting for ComfyUI"
            report = {"name": name, "prompt_id": prompt_id, "status": record["status"], "outputs": record.get("outputs")}
            reports.append(report)
            (output / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
            if record["status"].get("status_str") != "success":
                print(f"{name}: FAILED: {record['status']}", flush=True)
                return None
            files = record["outputs"][output_id].get("atelierx_files") or record["outputs"][output_id]["images"]
            images = []
            for item in files:
                params = {key: item[key] for key in ("filename", "subfolder", "type")}
                async with client.get("/view", params=params) as response:
                    assert response.status == 200
                    data = await response.read()
                image = Image.open(io.BytesIO(data))
                image.load()
                suffix = Path(item["filename"]).suffix
                (output / f"{name}{suffix}").write_bytes(data)
                images.append(image)
            print(f"{name}: success ({len(images)} file(s))", flush=True)
            return images

        fixture = Image.new("RGBA", (96, 96))
        for y in range(96):
            for x in range(96):
                fixture.putpixel((x, y), ((x*17)%256, (y*19)%256, (x*11+y*7)%256, 0 if x < 32 else 128 if x < 64 else 255))
        fixture_path = output / "fixture.png"
        fixture.save(fixture_path)
        filename = await upload(fixture_path)
        load = {"class_type": "LoadImage", "inputs": {"image": filename}}

        def encode(source):
            return {"class_type": "AtelierXEncodeSave", "inputs": {"image": source, "filename_prefix": "rest-test",
                                                                    "webp_enabled": True, "webp_quality": 90}}

        images = await run("encode", {"1": load, "2": encode(["1", 0])}, "2")
        assert images and len(images) == 2 and all(image.size == (96, 96) for image in images)
        alpha_graph = {"1": load, "2": {"class_type": "InvertMask", "inputs": {"mask": ["1", 1]}},
            "3": {"class_type": "AtelierXApplyCharacterAlpha", "inputs": {"image": ["1", 0], "character_mask": ["2", 0], "enabled": True}},
            "4": encode(["3", 0])}
        images = await run("alpha-mask", alpha_graph, "4")
        assert images and all(image.mode == "RGBA" for image in images)
        assert all(image.getchannel("A").tobytes() == fixture.getchannel("A").tobytes() for image in images)
        for treatment in ("mosaic", "white", "white_solid"):
            graph = {"1": load, "2": {"class_type": "AtelierXCensor", "inputs": {
                        "image": ["1", 0], "detection_mask": ["1", 1], "treatment": treatment, "intensity": 15, "enabled": True}},
                     "3": encode(["2", 0])}
            images = await run("censor-" + treatment, graph, "3")
            assert images and ImageChops.difference(images[0].convert("RGB"), fixture.convert("RGB")).getbbox()

        portrait = root / "artifacts/core-rest/20260913-034454/core-generated.png"
        portrait_name = await upload(portrait)
        portrait_load = {"class_type": "LoadImage", "inputs": {"image": portrait_name}}
        await run("alpha-detection", {"1": portrait_load,
            "2": {"class_type": "AtelierXDetectCharacterMask", "inputs": {"image": ["1", 0], "segmentation_model": "person_yolov8n-seg.pt", "confidence": .35}},
            "3": {"class_type": "AtelierXApplyCharacterAlpha", "inputs": {"image": ["1", 0], "character_mask": ["2", 0], "enabled": True}},
            "4": encode(["3", 0])}, "4")

        detail = json.loads((root / "custom_nodes/atelierx_detailer/examples/detailer-pipeline.api.json").read_text())["prompt"]
        detail["1"] = portrait_load
        detail["2"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "waiANIMA_v10Base10.safetensors", "weight_dtype": "default"}}
        detail["7"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": "waiANIMA_v10Base10_txt.safetensors", "type": "stable_diffusion", "device": "default"}}
        detail["8"] = {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}}
        detail["3"]["inputs"]["clip"] = ["7", 0]
        detail["4"]["inputs"]["clip"] = ["7", 0]
        detail["5"]["inputs"].update(clip=["7", 0], vae=["8", 0], cfg=4.5, seed=123456, denoise=.35,
                                         face_enabled=True, eye_enabled=False, mouth_enabled=False, hand_enabled=False)
        detail["6"] = encode(["5", 0])
        await run("detailer-face", detail, "6")
        print(str(output / "report.json"), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
