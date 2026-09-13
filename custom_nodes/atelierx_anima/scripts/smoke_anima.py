"""Run one offline GPU smoke generation through the AtelierX Anima extension."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# The smoke prompt is literal. Set these before ComfyUI imports any transformers
# components so an accidental remote model lookup fails rather than downloads.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-root", type=Path, required=True)
    parser.add_argument("--model", default="waiANIMA_v10Base10.safetensors")
    parser.add_argument("--text-encoder", default="waiANIMA_v10Base10_txt.safetensors")
    parser.add_argument("--vae", default="qwen_image_vae.safetensors")
    parser.add_argument("--seed", type=int, default=123456789)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--cfg", type=float, default=4.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    comfy_root = args.comfy_root.resolve()
    if not (comfy_root / "folder_paths.py").is_file():
        raise SystemExit(f"Not a ComfyUI root: {comfy_root}")

    package_root = Path(__file__).resolve().parents[1]
    repo_root = package_root.parents[1]
    sys.path[:0] = [str(comfy_root), str(package_root.parent)]

    from utils.extra_config import load_extra_path_config

    load_extra_path_config(str(comfy_root / "extra_model_paths.yaml"))

    import nodes
    import torch

    if not asyncio.run(nodes.load_custom_node(str(package_root))):
        raise RuntimeError("ComfyUI did not load the AtelierX Anima custom node.")
    node_class = nodes.NODE_CLASS_MAPPINGS.get("AtelierXAnimaGenerate")
    if node_class is None:
        raise RuntimeError("AtelierXAnimaGenerate was not added to ComfyUI's node registry.")

    # Calling the registered class directly keeps the smoke prompt literal;
    # ComfyUI's workflow dynamic-prompt expansion is not involved.
    with torch.inference_mode():
        output = node_class.execute(
            diffusion_model=args.model,
            text_encoder=args.text_encoder,
            vae=args.vae,
            positive_prompt="A fully clothed adult woman, calm expression, detailed anime illustration, studio portrait",
            negative_prompt="child, minor, nude, nsfw, blurry, low quality",
            width=args.width,
            height=args.height,
            seed=args.seed,
            steps=args.steps,
            cfg=args.cfg,
            sampler="euler_ancestral",
            scheduler="normal",
        )
    image_batch = output[0]
    expected_shape = (1, args.height, args.width)
    if image_batch.ndim != 4 or tuple(image_batch.shape[:3]) != expected_shape or image_batch.shape[-1] not in (3, 4):
        raise RuntimeError(f"Unexpected generated IMAGE shape: {tuple(image_batch.shape)}")
    if not bool(torch.isfinite(image_batch).all().item()):
        raise RuntimeError("Generated IMAGE contains NaN or infinite values; no artifact was saved.")
    image = image_batch[0].detach().cpu().clamp(0, 1).mul(255).byte().numpy()

    from PIL import Image

    artifact_dir = repo_root / "artifacts" / "anima-smoke"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    image_path = artifact_dir / f"anima-{stamp}.png"
    Image.fromarray(image).save(image_path)
    (artifact_dir / f"anima-{stamp}.json").write_text(
        json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "comfy_root": str(comfy_root),
            "model": args.model,
            "text_encoder": args.text_encoder,
            "vae": args.vae,
            "seed": args.seed,
            "width": args.width,
            "height": args.height,
            "steps": args.steps,
            "cfg": args.cfg,
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "positive_prompt": "A fully clothed adult woman, calm expression, detailed anime illustration, studio portrait",
            "negative_prompt": "child, minor, nude, nsfw, blurry, low quality",
            "image": image_path.name,
        }, indent=2),
        encoding="utf-8",
    )
    print(image_path)


if __name__ == "__main__":
    main()
