"""Validate the manual-mask and local-detection alpha example artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
WORKFLOW = EXAMPLES / "apply-character-alpha.workflow.json"
API = EXAMPLES / "apply-character-alpha.api.json"
DETECT_WORKFLOW = EXAMPLES / "detect-character-alpha.workflow.json"
DETECT_API = EXAMPLES / "detect-character-alpha.api.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(workflow: dict[str, Any], api: dict[str, Any]) -> None:
    nodes = {node["id"]: node for node in workflow["nodes"]}
    if tuple(nodes) != (1, 2, 3, 4):
        raise ValueError("Workflow must contain LoadImage, InvertMask, alpha node, and PreviewImage.")
    if [nodes[key]["type"] for key in (1, 2, 3, 4)] != [
        "LoadImage", "InvertMask", "AtelierXApplyCharacterAlpha", "PreviewImage"
    ]:
        raise ValueError("Workflow node types do not match the alpha-mask example.")
    expected_links = [[1, 1, 0, 3, 0, "IMAGE"], [2, 1, 1, 2, 0, "MASK"], [3, 2, 0, 3, 1, "MASK"], [4, 3, 0, 4, 0, "IMAGE"]]
    if workflow["links"] != expected_links:
        raise ValueError("Workflow must invert LoadImage's alpha-derived mask before alpha application.")
    prompt = api.get("prompt", {})
    if set(prompt) != {"1", "2", "3", "4"}:
        raise ValueError("API template must have four connected prompt nodes.")
    if prompt["3"] != {"class_type": "AtelierXApplyCharacterAlpha", "inputs": {"image": ["1", 0], "character_mask": ["2", 0], "enabled": True}}:
        raise ValueError("API template must supply a foreground character mask to the alpha node.")


def validate_detection(workflow: dict[str, Any], api: dict[str, Any]) -> None:
    nodes = {node["id"]: node for node in workflow["nodes"]}
    if tuple(nodes) != (1, 2, 3, 4):
        raise ValueError("Detection workflow must contain four connected nodes.")
    if [nodes[key]["type"] for key in (1, 2, 3, 4)] != [
        "LoadImage", "AtelierXDetectCharacterMask", "AtelierXApplyCharacterAlpha", "PreviewImage"
    ]:
        raise ValueError("Detection workflow node types do not match the local detector path.")
    expected_links = [[1, 1, 0, 2, 0, "IMAGE"], [2, 1, 0, 3, 0, "IMAGE"], [3, 2, 0, 3, 1, "MASK"], [4, 3, 0, 4, 0, "IMAGE"]]
    if workflow["links"] != expected_links:
        raise ValueError("Detection workflow must connect its foreground mask to alpha application.")
    prompt = api.get("prompt", {})
    if set(prompt) != {"1", "2", "3", "4"}:
        raise ValueError("Detection API template must have four connected prompt nodes.")
    if prompt["2"]["class_type"] != "AtelierXDetectCharacterMask":
        raise ValueError("Detection API template must invoke the detector node.")
    if prompt["3"] != {"class_type": "AtelierXApplyCharacterAlpha", "inputs": {"image": ["1", 0], "character_mask": ["2", 0], "enabled": True}}:
        raise ValueError("Detection API template must apply its detector foreground mask.")


if __name__ == "__main__":
    validate(load(WORKFLOW), load(API))
    validate_detection(load(DETECT_WORKFLOW), load(DETECT_API))
    print("AtelierX alpha example artifacts are valid.")
