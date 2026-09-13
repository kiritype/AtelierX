"""Build UI workflows from the successfully executed local REST fixtures."""
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "Encode - PNG and WebP": "20260913-035648/encode",
    "Alpha - Detect Character": "20260913-035648/alpha-detection",
    "Censor - Automatic Detection": "20260913-035844/censor-detect-mosaic",
    "Detailer - Anima All Parts": "20260913-040004/detailer-all",
}


def build(prompt, info):
    nodes, links = [], []
    for order, (key, entry) in enumerate(prompt.items()):
        schema = info[entry["class_type"]]
        inputs, widgets = [], []
        for group in ("required", "optional"):
            for name, spec in schema["input"].get(group, {}).items():
                kind = spec[0]
                options = spec[1] if len(spec) > 1 else {}
                value = entry["inputs"].get(name, options.get("default"))
                widget = isinstance(kind, list) or kind in ("STRING", "INT", "FLOAT", "BOOLEAN", "COMBO")
                if isinstance(value, list):
                    source_type = info[prompt[value[0]]["class_type"]]["output"][value[1]]
                    link_id = len(links) + 1
                    links.append([link_id, int(value[0]), value[1], int(key), len(inputs), source_type])
                    inputs.append({"name": name, "type": source_type, "link": link_id})
                elif widget and not options.get("forceInput"):
                    if value is None and isinstance(kind, list):
                        value = kind[0]
                    widgets.append(value)
                    if options.get("control_after_generate") or name in ("seed", "noise_seed"):
                        widgets.append("fixed")
                else:
                    inputs.append({"name": name, "type": kind, "link": None})
        nodes.append({"id": int(key), "type": entry["class_type"],
                      "pos": [(order % 3) * 440, (order // 3) * 680], "size": [400, 580],
                      "flags": {}, "order": order, "mode": 0,
                      "inputs": inputs, "outputs": [
                          {"name": schema.get("output_name", schema["output"])[i], "type": kind, "links": []}
                          for i, kind in enumerate(schema.get("output", []))],
                      "widgets_values": widgets, "properties": {"Node name for S&R": entry["class_type"]}})
    by_id = {node["id"]: node for node in nodes}
    for link in links:
        by_id[link[1]]["outputs"][link[2]]["links"].append(link[0])
    return {"version": 0.4, "last_node_id": max(by_id), "last_link_id": len(links),
            "nodes": nodes, "links": links, "groups": [], "config": {}, "extra": {}}


if __name__ == "__main__":
    with urlopen("http://127.0.0.1:8188/object_info") as response:
        info = json.load(response)
    destination = ROOT / "artifacts/postprocess-workflows"
    destination.mkdir(exist_ok=True)
    for name, source in SOURCES.items():
        prompt = json.loads((ROOT / "artifacts/postprocess-rest" / (source + ".api.json")).read_text())["prompt"]
        path = destination / (name + " - 20260913.json")
        path.write_text(json.dumps(build(prompt, info), ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)
