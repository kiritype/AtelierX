"""AtelierX foreground-mask alpha Custom Node package for ComfyUI."""

from .nodes import AtelierXAlphaExtension


async def comfy_entrypoint() -> AtelierXAlphaExtension:
    """Return the extension object discovered by ComfyUI 0.35.0+."""
    return AtelierXAlphaExtension()
