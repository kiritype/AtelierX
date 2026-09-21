from __future__ import annotations
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1] / "examples"
api = json.loads((root / "detail-region.api.json").read_text())
workflow = json.loads((root / "detail-region.workflow.json").read_text())
assert api["prompt"]["4"]["class_type"] == "AtelierXDetailer"
assert api["prompt"]["4"]["inputs"]["target"] in ("eyes", "mouth", "hands", "face")
assert {node["type"] for node in workflow["nodes"]} >= {"AtelierXDetailer", "LoadImageMask", "CheckpointLoaderSimple"}
pipeline = json.loads((root / "detailer-pipeline.api.json").read_text())
inputs = pipeline["prompt"]["5"]["inputs"]
assert pipeline["prompt"]["5"]["class_type"] == "AtelierXImpactDetailerPipeline"
assert [name for name in inputs if name.endswith("_enabled")] == ["face_enabled", "eye_enabled", "mouth_enabled", "hand_enabled"]
print("AtelierX Detailer examples are valid templates.")
