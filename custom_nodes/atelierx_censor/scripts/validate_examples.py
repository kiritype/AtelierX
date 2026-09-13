from __future__ import annotations
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1] / "examples"
api = json.loads((root / "censor-mask.api.json").read_text())
workflow = json.loads((root / "censor-mask.workflow.json").read_text())
assert api["prompt"]["3"]["class_type"] == "AtelierXCensor"
assert api["prompt"]["3"]["inputs"]["treatment"] in ("mosaic", "white", "white_solid")
assert api["prompt"]["3"]["inputs"]["intensity"] == 15
assert {node["type"] for node in workflow["nodes"]} >= {"AtelierXCensor", "LoadImageMask"}
print("AtelierX Censor examples are valid templates.")
