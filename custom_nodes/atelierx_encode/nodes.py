"""ComfyUI output node that saves AtelierX PNG and optional WebP files."""

from __future__ import annotations

import folder_paths
from comfy_api.latest import ComfyExtension, io

from .encode import save_images


class AtelierXEncodeSave(io.ComfyNode):
    """Save RGB/RGBA IMAGE batches as durable PNG plus optional WebP copies."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AtelierXEncodeSave",
            display_name="AtelierX Encode / Save",
            category="AtelierX/output",
            description=(
                "Always saves PNG under output/AtelierX. Optionally writes a WebP "
                "copy at the selected quality. RGB and existing RGBA alpha are preserved."
            ),
            inputs=[
                io.Image.Input("image"),
                io.String.Input("filename_prefix", default="image"),
                io.Boolean.Input("webp_enabled", default=False),
                io.Int.Input("webp_quality", default=90, min=1, max=100),
            ],
            outputs=[io.Image.Output(display_name="image")],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, image, filename_prefix: str = "image", webp_enabled: bool = False, webp_quality: int = 90) -> io.NodeOutput:
        saved = save_images(
            image,
            folder_paths.get_output_directory(),
            filename_prefix,
            webp_enabled,
            webp_quality,
        )
        # `images` remains the standard PNG preview collection. `atelierx_files`
        # carries every durable artifact, including optional WebPs, for history
        # consumers such as the Generation service.
        return io.NodeOutput(image, ui={"images": saved["images"], "atelierx_files": saved["files"]})


class AtelierXEncodeSaveExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AtelierXEncodeSave]
