"""Pure image encoding and safe output-file helpers for AtelierX."""

from __future__ import annotations

import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from PIL import Image


OUTPUT_SUBFOLDER = "AtelierX"
_SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
# Mirrors src/atelierx/output_names.py; ComfyUI cannot import the AtelierX package.
_FORBIDDEN = set('<>:"/\\|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}


def sanitize_segment(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("name segment must be text")
    value = "".join("_" if ch in _FORBIDDEN or unicodedata.category(ch) == "Cc" else ch for ch in text)
    value = re.sub(r"\s+", " ", value).strip(" ")
    value = value[:80].rstrip(". ")
    stem, dot, rest = value.partition(".")
    if stem.rstrip(" ").upper() in _RESERVED:
        value = (stem.rstrip(" ") + "_" + dot + rest)[:80].rstrip(". ")
    return value or "_"


def validate_output_name(output_name: str) -> str:
    """Allow a relative '/'-separated name of 1-6 already sanitized segments."""
    if not isinstance(output_name, str) or not output_name or len(output_name) > 240:
        raise ValueError("output_name must be 1-240 characters of text.")
    segments = output_name.split("/")
    if len(segments) > 6 or any(s in ("", ".", "..") or sanitize_segment(s) != s for s in segments):
        raise ValueError("output_name must be a relative path of at most 6 sanitized segments.")
    return output_name


def validate_filename_prefix(filename_prefix: str) -> str:
    """Allow a short filename stem, never a relative or absolute path."""
    if not isinstance(filename_prefix, str) or not _SAFE_PREFIX.fullmatch(filename_prefix):
        raise ValueError(
            "filename_prefix must be 1-120 ASCII letters, numbers, dots, underscores, or hyphens; "
            "it cannot contain a path separator."
        )
    return filename_prefix


def validate_webp_quality(webp_quality: int) -> int:
    if isinstance(webp_quality, bool) or not isinstance(webp_quality, int) or not 1 <= webp_quality <= 100:
        raise ValueError("webp_quality must be an integer from 1 through 100.")
    return webp_quality


def image_tensor_to_pil(image) -> Image.Image:
    """Convert one ComfyUI HWC float IMAGE item to RGB or RGBA Pillow image."""
    if not hasattr(image, "shape") or len(image.shape) != 3:
        raise ValueError("image items must be HWC tensors.")
    height, width, channels = image.shape
    if height < 1 or width < 1 or channels not in (3, 4):
        raise ValueError("image items must have positive dimensions and 3 (RGB) or 4 (RGBA) channels.")
    if not getattr(image, "is_floating_point", lambda: False)():
        raise ValueError("image items must use a floating-point tensor.")
    if not bool(image.isfinite().all().item()):
        raise ValueError("image items must contain only finite values.")
    pixels = (image.detach().cpu().clamp(0, 1).numpy() * 255.0).round().astype("uint8")
    return Image.fromarray(pixels, "RGBA" if channels == 4 else "RGB")


def _atomic_save(image: Image.Image, destination: Path, image_format: str, **options) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        image.save(temporary, format=image_format, **options)
        # Linking a fully written temporary file is an atomic, no-clobber publish
        # on the same filesystem. os.replace would violate the no-overwrite rule.
        os.link(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _destination(output_directory: Path, filename: str) -> Path:
    base = output_directory.resolve()
    destination_directory = (base / OUTPUT_SUBFOLDER).resolve()
    if destination_directory.parent != base:
        raise RuntimeError("AtelierX output directory escaped the configured ComfyUI output directory.")
    destination_directory.mkdir(parents=True, exist_ok=True)
    return destination_directory / filename


def _inside(base: Path, path: Path) -> Path:
    resolved = path.resolve()
    if resolved == base or not resolved.is_relative_to(base):
        raise RuntimeError("AtelierX output path escaped the configured ComfyUI output directory.")
    return resolved


def _save_named(image: Image.Image, output_root: Path, output_name: str, webp_enabled: bool, quality: int) -> list[dict[str, object]]:
    """Save `<output_name>.png` (+ .webp), adding ` (n)` until neither extension exists."""
    base = output_root.resolve()
    parent, _, stem = output_name.rpartition("/")
    directory = _inside(base, base / parent) if parent else base
    directory.mkdir(parents=True, exist_ok=True)
    directory = _inside(base, directory) if parent else base
    subfolder = directory.relative_to(base).as_posix() if parent else ""
    number = 1
    while True:
        candidate = stem if number == 1 else f"{stem} ({number})"
        number += 1
        png_path = _inside(base, directory / f"{candidate}.png")
        webp_path = _inside(base, directory / f"{candidate}.webp")
        if png_path.exists() or webp_path.exists():
            continue
        try:
            _atomic_save(image, png_path, "PNG", compress_level=4)
        except FileExistsError:
            continue
        files = [{"filename": png_path.name, "subfolder": subfolder, "type": "output", "format": "png"}]
        if webp_enabled:
            _atomic_save(image, webp_path, "WEBP", quality=quality, method=6)
            files.append({"filename": webp_path.name, "subfolder": subfolder, "type": "output", "format": "webp"})
        return files


def save_images(images, output_directory: str | Path, filename_prefix: str, webp_enabled: bool, webp_quality: int,
                output_name: str = "") -> dict[str, list[dict[str, object]]]:
    """Write PNGs and optional WebPs, returning preview and all-file descriptors.

    PNGs are committed atomically before optional WebP encoding. If a later WebP
    write fails the PNG remains available for recovery, while the caller receives
    the error and must not report a successful node result.
    """
    named = validate_output_name(output_name) if output_name else ""
    prefix = filename_prefix if named else validate_filename_prefix(filename_prefix)
    quality = validate_webp_quality(webp_quality)
    if not isinstance(webp_enabled, bool):
        raise ValueError("webp_enabled must be a boolean.")
    if not hasattr(images, "shape") or len(images.shape) != 4 or images.shape[0] < 1:
        raise ValueError("image must be a non-empty batched IMAGE tensor.")

    output_root = Path(output_directory)
    if not output_root.is_dir():
        raise ValueError("ComfyUI output directory does not exist.")

    previews: list[dict[str, object]] = []
    files: list[dict[str, object]] = []
    for batch_number, tensor in enumerate(images):
        image = image_tensor_to_pil(tensor)
        if named:
            saved = _save_named(image, output_root, named, webp_enabled, quality)
            previews.append({key: value for key, value in saved[0].items() if key != "format"})
            files.extend(saved)
            continue
        stem = f"{prefix}_{batch_number:05}_{uuid4().hex}"
        png_path = _destination(output_root, f"{stem}.png")
        _atomic_save(image, png_path, "PNG", compress_level=4)
        png_descriptor = {"filename": png_path.name, "subfolder": OUTPUT_SUBFOLDER, "type": "output", "format": "png"}
        previews.append({key: value for key, value in png_descriptor.items() if key != "format"})
        files.append(png_descriptor)
        if webp_enabled:
            webp_path = _destination(output_root, f"{stem}.webp")
            _atomic_save(image, webp_path, "WEBP", quality=quality, method=6)
            files.append({"filename": webp_path.name, "subfolder": OUTPUT_SUBFOLDER, "type": "output", "format": "webp"})
    return {"images": previews, "files": files}
