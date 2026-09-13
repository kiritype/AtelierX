"""Continue reference detector integration using the saved postprocess fixture."""
import asyncio
import io
import json
from pathlib import Path
import time
import uuid
import sys

import aiohttp
from PIL import Image


async def main():
    root = Path(__file__).resolve().parents[1]
    previous = root / "artifacts/postprocess-rest/20260913-035648"
    output = root / "artifacts/postprocess-rest" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    detailer = json.loads((previous / "detailer-face.api.json").read_text())["prompt"]
    source = json.loads((root / "artifacts/core-rest/20260913-034454/report.json").read_text())["task"]["snapshot"]["generation_inputs"]
    detailer["3"]["inputs"]["text"] = source["positive_prompt"]
    detailer["4"]["inputs"]["text"] = source["negative_prompt"]
    for stage in ("face", "eye", "mouth", "hand"):
        detailer["5"]["inputs"][stage + "_enabled"] = True
    graphs = []
    for treatment in ("mosaic", "white", "white_solid"):
        graphs.append(("censor-detect-" + treatment, {
            "1": detailer["1"],
            "2": {"class_type": "AtelierXDetectNsfwMask", "inputs": {"image": ["1", 0],
                   "segmentation_model": "ntd11_anime_nsfw_segm_v5-variant1.pt",
                   "labels": "nipples,pussy,penis,anus,testicles,x-ray,cross-section", "confidence": .35}},
            "3": {"class_type": "AtelierXCensor", "inputs": {"image": ["1", 0], "detection_mask": ["2", 0],
                   "treatment": treatment, "intensity": 15, "enabled": True}},
            "4": {"class_type": "AtelierXEncodeSave", "inputs": {"image": ["3", 0],
                   "filename_prefix": "censor-reference", "webp_enabled": True, "webp_quality": 90}},
            "5": {"class_type": "MaskToImage", "inputs": {"mask": ["2", 0]}},
            "6": {"class_type": "PreviewImage", "inputs": {"images": ["5", 0]}}
        }, "4"))
    graphs.append(("detailer-all", detailer, "6"))
    if "--detailer-only" in sys.argv:
        graphs = [entry for entry in graphs if entry[0] == "detailer-all"]
    reports = []
    async with aiohttp.ClientSession(base_url="http://127.0.0.1:8188") as client:
        for name, graph, output_id in graphs:
            async with client.get("/queue") as response:
                queue = await response.json()
                assert not queue["queue_running"] and not queue["queue_pending"], "ComfyUI busy"
            prompt_id = str(uuid.uuid4())
            payload = {"prompt": graph, "prompt_id": prompt_id, "client_id": "atelierx-reference-detector-test"}
            (output / f"{name}.api.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            async with client.post("/prompt", json=payload) as response:
                result = await response.json()
                assert response.status == 200, result
            print(name + ": submitted " + prompt_id, flush=True)
            record = None
            for _ in range(600):
                async with client.get("/history/" + prompt_id) as response:
                    record = (await response.json()).get(prompt_id)
                if record:
                    break
                await asyncio.sleep(1)
            assert record
            report = {"name": name, "prompt_id": prompt_id, "status": record["status"], "outputs": record.get("outputs", {})}
            reports.append(report)
            (output / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
            if record["status"].get("status_str") != "success":
                print(name + ": FAILED " + str(record["status"]), flush=True)
                continue
            for descriptor in record["outputs"][output_id]["atelierx_files"]:
                async with client.get("/view", params={k: descriptor[k] for k in ("filename", "subfolder", "type")}) as response:
                    assert response.status == 200
                    data = await response.read()
                image = Image.open(io.BytesIO(data))
                image.load()
                assert image.size == (768, 1024)
                (output / (name + Path(descriptor["filename"]).suffix)).write_bytes(data)
            if name.startswith("censor"):
                descriptor = record["outputs"]["6"]["images"][0]
                async with client.get("/view", params=descriptor) as response:
                    mask = Image.open(io.BytesIO(await response.read())).convert("L")
                report["mask_nonzero_pixels"] = sum(count for value, count in enumerate(mask.histogram()) if value > 0)
                print(name + f': success; mask pixels={report["mask_nonzero_pixels"]}', flush=True)
            else:
                print(name + ": success", flush=True)
            (output / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(str(output / "report.json"), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
