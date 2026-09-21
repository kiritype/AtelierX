"""Validate the AtelierX Anima example workflow and ComfyUI API prompt."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = PACKAGE_ROOT / "examples"
WORKFLOW_PATH = EXAMPLES_ROOT / "anima-preview.workflow.json"
API_PATH = EXAMPLES_ROOT / "anima-preview.api.json"
LORA_WORKFLOW_PATH = EXAMPLES_ROOT / "anima-lora-preview.workflow.json"
LORA_API_PATH = EXAMPLES_ROOT / "anima-lora-preview.api.json"
NODE_ID = "AtelierXAnimaGenerate"
INPUT_ORDER = (
    "diffusion_model", "text_encoder", "vae", "positive_prompt", "negative_prompt",
    "width", "height", "seed", "steps", "cfg", "sampler", "scheduler",
)
EXAMPLE_VALUES = (
    "waiANIMA_v10Base10.safetensors", "waiANIMA_v10Base10_txt.safetensors",
    "qwen_image_vae.safetensors",
    "A fully clothed adult woman, calm expression, detailed anime illustration, studio portrait",
    "child, minor, nude, nsfw, blurry, low quality",
    768, 1024, 123456789, 24, 4.5, "euler_ancestral", "normal",
)
WORKFLOW_WIDGET_VALUES = (
    *EXAMPLE_VALUES[:8],
    "fixed",
    *EXAMPLE_VALUES[8:],
)
LORA_INPUT_ORDER = (
    *INPUT_ORDER,
    "lora_stack",
)
LORA_STACK = "[{\"name\":\"anima-base-1-masterpiece-v51.safetensors\",\"strength\":0.35},{\"name\":\"anima-highres-aesthetic-boost.safetensors\",\"strength\":0.5}]"
LORA_EXAMPLE_VALUES = (
    *EXAMPLE_VALUES[:3],
    "masterpiece, very aesthetic, A fully clothed adult woman, calm expression, detailed anime illustration, studio portrait",
    *EXAMPLE_VALUES[4:],
)
LORA_WORKFLOW_WIDGET_VALUES = (
    *LORA_EXAMPLE_VALUES[:8], "fixed", *LORA_EXAMPLE_VALUES[8:], LORA_STACK
)


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def validate_static(workflow: dict[str, Any], api_request: dict[str, Any]) -> None:
    nodes = {node["id"]: node for node in workflow["nodes"]}
    generator = nodes.get(1)
    preview = nodes.get(2)
    if generator is None or generator.get("type") != NODE_ID:
        raise ValueError("Workflow must contain AtelierXAnimaGenerate as node 1.")
    if preview is None or preview.get("type") != "PreviewImage":
        raise ValueError("Workflow must contain PreviewImage as node 2.")
    if tuple(item["name"] for item in generator["inputs"]) != INPUT_ORDER:
        raise ValueError("Workflow widget input order does not match the V3 node schema.")
    if tuple(generator.get("widgets_values", ())) != WORKFLOW_WIDGET_VALUES:
        raise ValueError("Workflow widget values do not match the verified Anima example.")
    if workflow.get("links") != [[1, 1, 0, 2, 0, "IMAGE"]]:
        raise ValueError("Workflow must connect generator IMAGE output to PreviewImage.")

    prompt = api_request.get("prompt")
    if not isinstance(prompt, dict) or set(prompt) != {"1", "2"}:
        raise ValueError("API request must contain exactly the generator and preview prompt nodes.")
    generator_prompt = prompt["1"]
    if generator_prompt.get("class_type") != NODE_ID:
        raise ValueError("API generator class_type is incorrect.")
    if tuple(generator_prompt.get("inputs", {})) != INPUT_ORDER:
        raise ValueError("API input order does not match the V3 node schema.")
    if tuple(generator_prompt["inputs"].values()) != EXAMPLE_VALUES:
        raise ValueError("API inputs do not match the verified Anima example.")
    if prompt["2"] != {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}}:
        raise ValueError("API request must route the generated IMAGE to PreviewImage.")


def validate_lora_static(workflow: dict[str, Any], api_request: dict[str, Any]) -> None:
    nodes = {node["id"]: node for node in workflow["nodes"]}
    generator = nodes.get(1)
    if generator is None or generator.get("type") != NODE_ID:
        raise ValueError("LoRA workflow must contain AtelierXAnimaGenerate as node 1.")
    if tuple(item["name"] for item in generator["inputs"]) != LORA_INPUT_ORDER:
        raise ValueError("LoRA workflow widget input order does not match the V3 node schema.")
    if tuple(generator.get("widgets_values", ())) != LORA_WORKFLOW_WIDGET_VALUES:
        raise ValueError("LoRA workflow widget values do not match the verified Anima LoRA example.")
    if workflow.get("links") != [[1, 1, 0, 2, 0, "IMAGE"]]:
        raise ValueError("LoRA workflow must connect generator IMAGE output to PreviewImage.")

    prompt = api_request.get("prompt")
    if not isinstance(prompt, dict) or set(prompt) != {"1", "2"}:
        raise ValueError("LoRA API request must contain exactly the generator and preview nodes.")
    inputs = prompt["1"].get("inputs", {})
    if prompt["1"].get("class_type") != NODE_ID or tuple(inputs) != LORA_INPUT_ORDER:
        raise ValueError("LoRA API input order does not match the V3 node schema.")
    if tuple(inputs.values()) != (*LORA_EXAMPLE_VALUES, LORA_STACK):
        raise ValueError("LoRA API inputs do not match the verified Anima LoRA example.")
    if prompt["2"] != {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}}:
        raise ValueError("LoRA API request must route the generated IMAGE to PreviewImage.")


def validate_with_comfy(comfy_root: Path) -> None:
    comfy_root = comfy_root.resolve()
    if not (comfy_root / "nodes.py").is_file():
        raise ValueError(f"Not a ComfyUI root: {comfy_root}")

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    sys.path.insert(0, str(comfy_root))
    from utils.extra_config import load_extra_path_config

    load_extra_path_config(str(comfy_root / "extra_model_paths.yaml"))
    import nodes
    import execution

    if not asyncio.run(nodes.load_custom_node(str(PACKAGE_ROOT))):
        raise ValueError("ComfyUI could not load the AtelierX Anima package.")
    node_class = nodes.NODE_CLASS_MAPPINGS.get(NODE_ID)
    if node_class is None:
        raise ValueError("AtelierXAnimaGenerate was not registered by ComfyUI.")

    required = node_class.INPUT_TYPES()["required"]
    if tuple(required) != INPUT_ORDER:
        raise ValueError("Loaded V3 node input order differs from the example.")
    optional = node_class.INPUT_TYPES()["optional"]
    if tuple(optional) != LORA_INPUT_ORDER[len(INPUT_ORDER):]:
        raise ValueError("Loaded V3 node LoRA input order differs from the example.")
    values = dict(zip(INPUT_ORDER, EXAMPLE_VALUES, strict=True))
    for model_kind, key in (("diffusion_models", "diffusion_model"), ("text_encoders", "text_encoder"), ("vae", "vae")):
        if values[key] not in required[key][1]["options"]:
            raise ValueError(f"Example {key} is not registered in ComfyUI {model_kind}: {values[key]}")
    if values["sampler"] not in required["sampler"][1]["options"]:
        raise ValueError("Example sampler is not supported by this ComfyUI installation.")
    if values["scheduler"] not in required["scheduler"][1]["options"]:
        raise ValueError("Example scheduler is not supported by this ComfyUI installation.")
    if "PreviewImage" not in nodes.NODE_CLASS_MAPPINGS:
        raise ValueError("ComfyUI PreviewImage node is unavailable.")
    lora_options = optional["lora_stack"][1]["atelierx_lora_stack"]["options"]
    for name in ("anima-base-1-masterpiece-v51.safetensors", "anima-highres-aesthetic-boost.safetensors"):
        if name not in lora_options:
            raise ValueError(f"Example LoRA is not registered in ComfyUI: {name}")
    old_prompt_valid, _, _, old_prompt_errors = asyncio.run(
        execution.validate_prompt("atelierx-anima-no-lora-compat", _load(API_PATH)["prompt"], None)
    )
    if not old_prompt_valid:
        raise ValueError(f"Original no-LoRA API prompt is no longer valid: {old_prompt_errors}")
    lora_prompt_valid, _, _, lora_prompt_errors = asyncio.run(
        execution.validate_prompt("atelierx-anima-dynamic-lora", _load(LORA_API_PATH)["prompt"], None)
    )
    if not lora_prompt_valid:
        raise ValueError(f"Dynamic LoRA API prompt is not valid: {lora_prompt_errors}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-root", type=Path)
    args = parser.parse_args()

    validate_static(_load(WORKFLOW_PATH), _load(API_PATH))
    validate_lora_static(_load(LORA_WORKFLOW_PATH), _load(LORA_API_PATH))
    if args.comfy_root is not None:
        validate_with_comfy(args.comfy_root)
    print("AtelierX Anima examples are valid.")


if __name__ == "__main__":
    main()
