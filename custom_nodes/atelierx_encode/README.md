# AtelierX Encode / Save

`AtelierXEncodeSave` is a ComfyUI output node. It accepts a batched RGB or RGBA
`IMAGE`, always writes PNG files, and can also write a WebP copy for every image.
The node is deliberately an output node: its standard `ui.images` records point
at the PNG files so ComfyUI history and the UI can display them. Its
`ui.atelierx_files` records every durable output, with `format: png` or
`format: webp`, so service consumers can discover optional WebP artifacts.

## Inputs and output

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `image` | `IMAGE` | required | Non-empty RGB or RGBA image batch. RGBA alpha is retained. |
| `filename_prefix` | `STRING` | `image` | Filename stem: ASCII letters, digits, `.`, `_`, `-`, up to 120 characters. Paths are rejected. |
| `webp_enabled` | `BOOLEAN` | `false` | Adds a WebP copy beside each PNG. |
| `webp_quality` | `INT` | `90` | WebP quality from 1 through 100. |

The output is the original `IMAGE`. A MASK is intentionally not accepted: native
RGBA alpha is authoritative at this final stage. Use the Alpha node or another
upstream operation to apply a ComfyUI MASK before saving.

## Files and failure behavior

Files are written only below `<ComfyUI output>/AtelierX`. Each batch item receives
a UUID-based stem and an atomic no-clobber publish, so this node does not overwrite an existing output. PNG and
WebP use the same stem. The PNG write is atomic. If optional WebP encoding fails,
the completed PNG remains for recovery, but the node raises an error and returns
no successful ComfyUI result descriptors.

PNG is the history-preview artifact. The optional WebP is an additional delivery
file; its lossy RGB data is not required to be pixel-identical to PNG. Pillow
preserves an RGBA alpha channel in both formats.

Run `scripts/Install-AtelierXEncode.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI`
to create a guarded junction. It refuses to replace an existing non-junction or a
junction that points at another source. Import `examples/encode-save.workflow.json`,
choose a file in `LoadImage`, then queue it. The saved files appear under
`output/AtelierX`.
