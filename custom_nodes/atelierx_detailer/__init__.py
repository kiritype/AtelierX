"""AtelierX masked diffusion Detailer package for ComfyUI."""

from .nodes import AtelierXDetailerExtension


async def comfy_entrypoint() -> AtelierXDetailerExtension:
    """Return the extension discovered by ComfyUI 0.35.0+."""
    return AtelierXDetailerExtension()
