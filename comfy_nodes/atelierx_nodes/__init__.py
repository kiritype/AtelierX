"""AtelierX post-processing nodes for ComfyUI (background alpha, censor, upscale, detailer).

Copied into ComfyUI's ``custom_nodes`` by tools/install_comfy_nodes.py. The detailer calls
ComfyUI-Impact-Pack at run time; that pack is installed separately and keeps its own license.
"""

from comfy_api.latest import ComfyExtension, io

from .alpha.nodes import AtelierXAlphaExtension
from .censor.nodes import AtelierXCensorExtension
from .detailer.nodes import AtelierXDetailerExtension
from .upscale.nodes import AtelierXUpscaleExtension

PARTS = (
    AtelierXAlphaExtension,
    AtelierXCensorExtension,
    AtelierXUpscaleExtension,
    AtelierXDetailerExtension,
)


class AtelierXExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        nodes = []
        for part in PARTS:
            nodes += await part().get_node_list()
        return nodes


async def comfy_entrypoint() -> AtelierXExtension:
    return AtelierXExtension()
