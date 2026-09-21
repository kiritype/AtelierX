"""Pure image encoding and safe output-file helpers for AtelierX."""

from __future__ import annotations

import os
from pathlib import Path
import re
from uuid import uuid4

from PIL import Image


OUTPUT_SUBFOLDER = "AtelierX"
_SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


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


def save_images(images, output_directory: str | Path, filename_prefix: str, webp_enabled: bool, webp_quality: int) -> dict[str, list[dict[str, object]]]:
    """Write PNGs and optional WebPs, returning preview and all-file descriptors.

    PNGs are committed atomically before optional WebP encoding. If a later WebP
    write fails the PNG remains available for recovery, while the caller receives
    the error and must not report a successful node result.
    """
    prefix = validate_filename_prefix(filename_prefix)
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
