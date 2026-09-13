"""AtelierX upscale Custom Node package for ComfyUI."""

from .nodes import AtelierXUpscaleExtension


async def comfy_entrypoint() -> AtelierXUpscaleExtension:
    """Return the extension object discovered by ComfyUI 0.35.0+."""
    return AtelierXUpscaleExtension()
