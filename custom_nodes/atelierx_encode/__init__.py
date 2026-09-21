"""AtelierX Encode / Save Custom Node package for ComfyUI."""

from .nodes import AtelierXEncodeSaveExtension


async def comfy_entrypoint() -> AtelierXEncodeSaveExtension:
    """Return the extension object discovered by ComfyUI 0.35.0+."""
    return AtelierXEncodeSaveExtension()
