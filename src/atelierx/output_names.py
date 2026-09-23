"""ComfyUI output-relative file names shared by Core and Generation (ADR-0026)."""
from __future__ import annotations

import re
import unicodedata

SEGMENT_MAX = 80
NAME_MAX = 240
SEGMENTS_MAX = 6
_FORBIDDEN = set('<>:"/\\|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}


def _reserved(stem: str) -> bool:
    return stem.rstrip(" ").upper() in _RESERVED


def sanitize_segment(text) -> str:
    if not isinstance(text, str):
        raise ValueError("name segment must be text")
    value = "".join("_" if ch in _FORBIDDEN or unicodedata.category(ch) == "Cc" else ch for ch in text)
    value = re.sub(r"\s+", " ", value).strip(" ")
    value = value[:SEGMENT_MAX].rstrip(". ")
    stem, dot, rest = value.partition(".")
    if _reserved(stem):
        value = (stem.rstrip(" ") + "_" + dot + rest)[:SEGMENT_MAX].rstrip(". ")
    return value or "_"


def validate_output_name(value) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("output_name must be non-empty text")
    if len(value) > NAME_MAX:
        raise ValueError(f"output_name must be at most {NAME_MAX} characters")
    segments = value.split("/")
    if len(segments) > SEGMENTS_MAX:
        raise ValueError(f"output_name must have at most {SEGMENTS_MAX} segments")
    for segment in segments:
        if segment in ("", ".", "..") or sanitize_segment(segment) != segment:
            raise ValueError("output_name must be a relative path of sanitized segments")
    return value


def build_output_name(*segments) -> str:
    parts = [sanitize_segment(segment if isinstance(segment, str) else str(segment)) for segment in segments]
    # Long work/character/outfit names must not make generation fail: trim the longest middle segment first.
    while len("/".join(parts)) > NAME_MAX and len(parts) > 2:
        index = max(range(1, len(parts) - 1), key=lambda i: len(parts[i]))
        excess = len("/".join(parts)) - NAME_MAX
        if len(parts[index]) <= 8:
            break
        parts[index] = parts[index][:max(8, len(parts[index]) - excess)].rstrip(". ") or "_"
    return validate_output_name("/".join(parts))
