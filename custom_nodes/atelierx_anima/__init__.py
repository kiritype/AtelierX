"""AtelierX Anima Custom Node package for ComfyUI."""

from .nodes import AtelierXAnimaExtension


WEB_DIRECTORY = "./web"


async def comfy_entrypoint() -> AtelierXAnimaExtension:
    """Return the extension object discovered by ComfyUI 0.35.0+."""
    return AtelierXAnimaExtension()
