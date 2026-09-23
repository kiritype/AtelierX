"""Core-local copy of the shared output name contract (ADR-0026)."""
import re

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
LIMIT = 80


def sanitize_segment(text):
    value = _FORBIDDEN.sub("_", str(text))
    value = re.sub(r"\s+", " ", value).strip(" ").rstrip(". ")
    if not value:
        return "_"
    if value.upper() in _RESERVED:
        value += "_"
    return value[:LIMIT].rstrip(". ") or "_"


def build_output_name(*segments):
    return "/".join(sanitize_segment(segment) for segment in segments)
