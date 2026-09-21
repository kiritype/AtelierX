"""Validate the static AtelierX Encode / Save example artifacts."""

from __future__ import annotations

import json
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def main() -> None:
    workflow, api = _load("encode-save.workflow.json"), _load("encode-save.api.json")
    nodes = {node["id"]: node for node in workflow["nodes"]}
    assert [nodes[key]["type"] for key in (1, 2)] == ["LoadImage", "AtelierXEncodeSave"]
    assert [item["name"] for item in nodes[2]["inputs"]] == [
        "image", "filename_prefix", "webp_enabled", "webp_quality"
    ]
    assert workflow["links"] == [[1, 1, 0, 2, 0, "IMAGE"]]
    assert api["prompt"]["2"] == {
        "class_type": "AtelierXEncodeSave",
        "inputs": {"image": ["1", 0], "filename_prefix": "image", "webp_enabled": True, "webp_quality": 90},
    }
    print("AtelierX Encode / Save examples are valid templates.")


if __name__ == "__main__":
    main()
