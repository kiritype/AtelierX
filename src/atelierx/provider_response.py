"""Safe, durable diagnostics from an OpenAI-compatible completion envelope."""
from __future__ import annotations


USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens")


def diagnostics(payload):
    """Return only finite response metadata; never retain message content or credentials."""
    result = {}
    try:
        choice = payload["choices"][0]
    except (KeyError, IndexError, TypeError):
        choice = None
    if isinstance(choice, dict) and isinstance(choice.get("finish_reason"), str):
        result["finish_reason"] = choice["finish_reason"]
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict):
        safe_usage = {field: usage[field] for field in USAGE_FIELDS if type(usage.get(field)) is int and usage[field] >= 0}
        if safe_usage:
            result["usage"] = safe_usage
    return result


def was_truncated(payload):
    return diagnostics(payload).get("finish_reason") == "length"
