"""ADR-0027 P3/P7: Generation-side consistency method registry.

Single source describing the consistency methods a job may select, mirroring
the fixed/allow-listed style of pipeline.py. This module only validates
shape, params, and live ComfyUI node/LoRA registration; it never touches
stored images or the job's own SQLite-free filesystem state (that stays in
Generation.submit/run_job, same separation pipeline.py keeps from the
Generation class).
"""
from __future__ import annotations

import math

from ..common import ApiError

ANIMA_NODE = "AtelierXAnimaGenerate"

# Fixed params (not exposed): start_percent 0, In-Context LoRA strength 1.0,
# cond_only True, fit_mode "pad", ref_timestep 0 (see custom_nodes/atelierx_anima).
METHODS = {
    "anima-incontext-character": {
        "families": ("anima",),
        "nodes": ("AnimaRefEncode", "AnimaRefLatentBatch", "AnimaInContextApply"),
        "lora": "anima-incontext-character.safetensors",
        "params": {
            "strength": {"type": "number", "default": 1.0, "min": 0.5, "max": 1.5},
            "end_percent": {"type": "number", "default": 0.5, "min": 0.3, "max": 1.0, "warn_below": 0.5},
            "suppress_reference_background": {"type": "boolean", "default": True},
        },
    },
}

REQUIRED_NODES = sorted({name for spec in METHODS.values() for name in spec["nodes"]})


def _lora_options(info):
    schema = info.get(ANIMA_NODE)
    if not isinstance(schema, dict):
        return []
    stack = schema.get("input", {}).get("optional", {}).get("lora_stack", [])
    metadata = stack[1] if len(stack) > 1 and isinstance(stack[1], dict) else {}
    return [item for item in metadata.get("atelierx_lora_stack", {}).get("options", []) if isinstance(item, str)]


def _validate_params(spec, value):
    if not isinstance(value, dict) or set(value) - set(spec["params"]):
        raise ApiError("GEN_INVALID_INPUT", "consistency.params has unknown fields")
    result = {}
    for name, field in spec["params"].items():
        item = value.get(name, field["default"])
        if field["type"] == "number":
            if type(item) not in (int, float) or isinstance(item, bool) or not math.isfinite(item):
                raise ApiError("GEN_INVALID_INPUT", f"consistency.params.{name} must be a finite number")
            if item < field["min"] or item > field["max"]:
                raise ApiError("GEN_INVALID_INPUT",
                               f"consistency.params.{name} must be between {field['min']} and {field['max']}")
            result[name] = float(item)
        elif field["type"] == "boolean":
            if type(item) is not bool:
                raise ApiError("GEN_INVALID_INPUT", f"consistency.params.{name} must be boolean")
            result[name] = item
    return result


def _validate_references(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ApiError("GEN_INVALID_INPUT", "consistency.references must contain exactly two entries (full and face)")
    roles = set()
    result = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"role", "image_id", "sha256"}:
            raise ApiError("GEN_INVALID_INPUT",
                           f"consistency.references[{index}] must contain only role, image_id, sha256")
        role, image_id, sha256 = entry["role"], entry["image_id"], entry["sha256"]
        if role not in ("full", "face") or role in roles:
            raise ApiError("GEN_INVALID_INPUT",
                           "consistency.references must include exactly one full and one face entry")
        roles.add(role)
        if not isinstance(image_id, str) or not image_id:
            raise ApiError("GEN_INVALID_INPUT", f"consistency.references[{index}].image_id must be non-empty text")
        if not isinstance(sha256, str) or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ApiError("GEN_INVALID_INPUT",
                           f"consistency.references[{index}].sha256 must be a 64-character lowercase hex string")
        result.append({"role": role, "image_id": image_id, "sha256": sha256})
    if roles != {"full", "face"}:
        raise ApiError("GEN_INVALID_INPUT", "consistency.references must include exactly one full and one face entry")
    return result


def validate_consistency(value, info, family="anima"):
    """Return a canonical {method,params,references} or None for no consistency.

    Raises GEN_INVALID_INPUT (400) for malformed shape/params/references and
    GEN_NODE_UNAVAILABLE (503) when the method's ComfyUI nodes or fixed LoRA
    are not currently registered. Reference image existence/integrity is the
    caller's job (Generation.submit/run_job), since only it can reach the
    job store.
    """
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"method", "params", "references"} \
            or "method" not in value or "references" not in value:
        raise ApiError("GEN_INVALID_INPUT", "consistency must be an object with method and references")
    method = value["method"]
    if not isinstance(method, str) or method not in METHODS:
        raise ApiError("GEN_INVALID_INPUT", f"Unknown consistency method: {method!r}")
    spec = METHODS[method]
    if family not in spec["families"]:
        raise ApiError("GEN_INVALID_INPUT", f"consistency method {method!r} is not supported for the {family} family")
    params = _validate_params(spec, value.get("params", {}))
    references = _validate_references(value["references"])
    missing = [name for name in spec["nodes"] if name not in info]
    if missing:
        raise ApiError("GEN_NODE_UNAVAILABLE", f"Required ComfyUI node is not registered: {missing[0]}", 503)
    if spec["lora"] not in _lora_options(info):
        raise ApiError("GEN_NODE_UNAVAILABLE", f"Required LoRA is not registered: {spec['lora']}", 503)
    return {"method": method, "params": params, "references": references}


def resources_entry(info, family="anima"):
    """Return the /v1/resources `consistency_methods` list for one family."""
    result = []
    for method_id, spec in METHODS.items():
        if family not in spec["families"]:
            continue
        missing = [name for name in spec["nodes"] if name not in info]
        lora_ok = spec["lora"] in _lora_options(info)
        reason = None
        if missing:
            reason = f"Required ComfyUI node is not registered: {missing[0]}"
        elif not lora_ok:
            reason = f"Required LoRA is not registered: {spec['lora']}"
        entry = {
            "id": method_id,
            "families": list(spec["families"]),
            "available": not missing and lora_ok,
            "params": {name: dict(field) for name, field in spec["params"].items()},
        }
        if reason is not None:
            entry["unavailable_reason"] = reason
        result.append(entry)
    return result


def node_prompt_fields(consistency):
    """Return the AtelierXAnimaGenerate `consistency` JSON payload (method+strength+end_percent only)."""
    if consistency is None:
        return None
    return {"method": consistency["method"], "params": {
        "strength": consistency["params"]["strength"],
        "end_percent": consistency["params"]["end_percent"],
    }}
