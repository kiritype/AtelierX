# AtelierX Apply Character Alpha

This ComfyUI 0.35.0 package provides two nodes for ADR-0002 N-10:

- `AtelierX Detect Character Mask` uses an explicitly selected, locally
  registered Ultralytics **segmentation** model. It combines all model results
  in COCO's `person` class into a foreground mask. The node opens only that
  local model path and does not download a model or install a Python package.
- `AtelierX Apply Character Alpha` accepts an `IMAGE` and
a **foreground character** `MASK`: `1` retains the character and `0` makes the
corresponding background alpha transparent. It returns an RGBA `IMAGE` plus a
`background_mask` in ComfyUI's convention (`1` means transparent). The
returned mask is exactly `1 - output_alpha`, including any alpha that already
existed on the IMAGE.

`enabled=false` preserves the input RGB and any existing alpha. When enabled,
existing image alpha is preserved and multiplied by the supplied character
foreground mask. The node rejects mismatched batch or pixel dimensions rather
than resizing or broadcasting a mask.

The detector is an actual detector/segmentation path when its explicitly
selected backend is installed, but it is not a universal anime-character
segmenter. It selects the model's COCO `person` class and combines all matched
instances; it does not choose one character, prompt SAM, refine hair edges, or
resize a non-pixel-aligned result. A model with no person result fails and
leaves Alpha unchanged, so this workflow cannot silently make the whole image
transparent. These behaviour choices are an initial implementation, not a
replacement for the still-open N-10 model and boundary-policy decision.

At the recorded local installation, the shared `BackgroundRemoval` and `Sams`
folders are empty and `Ultralytics` has only empty `bbox` and `segm`
directories. The ComfyUI Python environment has no `ultralytics` runtime.
The detection workflow is therefore prepared but cannot run there yet. Its
failure names the absent runtime or unregistered local model; it never tries to
fetch either one. The supplied-mask node remains available independently.

The checked-in [manual-mask workflow](examples/apply-character-alpha.workflow.json) uses
`LoadImage` and `InvertMask` only to demonstrate the wiring: select a source
PNG whose alpha already identifies the background, then the inverted
`LoadImage` mask becomes this node's foreground character mask. It is a manual
mask-source example, not a detector example. The accompanying
[API template](examples/apply-character-alpha.api.json) requires a real input
file name in the ComfyUI input directory before `POST /prompt`.

The [detection workflow](examples/detect-character-alpha.workflow.json) and
[API template](examples/detect-character-alpha.api.json) connect `LoadImage →
AtelierX Detect Character Mask → AtelierX Apply Character Alpha → PreviewImage`.
Before running it, install a compatible Ultralytics runtime and place a chosen
local segmentation weight in a ComfyUI-registered `ultralytics_segm` folder;
then select it in the node (and replace both placeholder filenames). This
package does not prescribe or obtain those resources.

Run the tensor-level tests without GPU inference:

```powershell
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B -m unittest discover -s custom_nodes\atelierx_alpha\tests -v
```

After the current ComfyUI work is idle and restart coordination is complete,
the following helper can create only a safe junction at
`custom_nodes\\atelierx_alpha`; it refuses to replace an existing directory or
a junction targeting elsewhere:

```powershell
powershell -ExecutionPolicy Bypass -File .\custom_nodes\atelierx_alpha\scripts\Install-AtelierXAlpha.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI
```

The next integration step needs a model and boundary-policy decision. The
implemented local Ultralytics path makes its present person-class/all-instance
rule explicit; detector-prompted SAM and background-removal models such as
BiRefNet/rembg remain unevaluated. Their output semantics, single vs. multiple
character behavior, and edge refinement are not selected here.
