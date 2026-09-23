"""Initial bounded proposal contract; no automatic prompt/model rewriting."""
import math
from .common import ApiError


def validate_changes(changes, evidence, original):
    def invalid(reason):
        raise ApiError("VAL_REGENERATION_PROPOSAL_INVALID", "Invalid regeneration proposal: " + reason, 422)
    if not isinstance(changes, list): invalid("changes must be an array")
    failed = {item["id"] for item in evidence if item.get("status") in {"mismatch", "not_visible"}}
    seen = set()
    for item in changes:
        if not isinstance(item, dict) or set(item) != {"field", "value", "reason", "evidence_ids"}: invalid("change fields are malformed")
        field, value = item["field"], item["value"]
        if not isinstance(field, str) or field not in {"seed", "steps", "cfg"} or field in seen: invalid("field is unsupported or duplicated")
        seen.add(field)
        if not isinstance(item["reason"], str) or not item["reason"].strip(): invalid("reason is required")
        ids = item["evidence_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in failed for i in ids): invalid("evidence_ids must reference failed evidence")
        if type(value) not in (int, float) or not math.isfinite(value): invalid("value must be a finite number")
        if field in {"seed", "steps"} and type(value) is not int: invalid(field + " must be an integer")
        low, high = {"seed": (0, 2**64-1), "steps": (1, 100), "cfg": (0, 20)}[field]
        if not low <= value <= high: invalid(field + " is out of range")
        if field not in original or original[field] == value: invalid(field + " does not change a supplied setting")
    return changes


def proposal_schema():
    return {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["field", "value", "reason", "evidence_ids"], "properties": {
        "field": {"type": "string", "enum": ["seed", "steps", "cfg"]},
        "value": {"type": "number"}, "reason": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}}}}}
