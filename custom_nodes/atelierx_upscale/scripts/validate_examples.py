"""Validate the non-model-specific AtelierX Upscale example artifacts."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples"

def load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def main() -> None:
    workflow, api = load("upscale-preview.workflow.json"), load("upscale-preview.api.json")
    nodes = {node["id"]: node for node in workflow["nodes"]}
    assert nodes[2]["type"] == "AtelierXUpscale"
    assert [item["name"] for item in nodes[2]["inputs"]] == ["image", "upscale_model", "scale"]
    assert nodes[2]["widgets_values"] == ["4x-UltraSharp.safetensors", 1.5]
    assert workflow["links"] == [[1, 1, 0, 2, 0, "IMAGE"], [2, 2, 0, 3, 0, "IMAGE"]]
    prompt = api["prompt"]
    assert prompt["2"] == {"class_type": "AtelierXUpscale", "inputs": {"image": ["1", 0], "upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5}}
    print("AtelierX Upscale examples are valid templates.")

if __name__ == "__main__":
    main()
