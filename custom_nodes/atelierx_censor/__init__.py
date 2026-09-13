"""AtelierX supplied-mask censor package for ComfyUI."""

from .nodes import AtelierXCensorExtension


async def comfy_entrypoint() -> AtelierXCensorExtension:
    return AtelierXCensorExtension()
