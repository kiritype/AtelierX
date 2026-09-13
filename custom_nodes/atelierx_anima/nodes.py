"""A self-contained text-to-image node for Anima diffusion models.

The node deliberately owns only the ComfyUI execution chain.  It does not save
images, manage presets, contact AtelierX services, or open any database.
"""

from __future__ import annotations

import json
import math
import os

import torch

import comfy.model_management
import comfy.lora
import comfy.lora_convert
import comfy.samplers
import comfy.sd
import comfy.utils
import folder_paths
import nodes
from comfy_api.latest import ComfyExtension, io


MIN_DIMENSION = 256
MAX_DIMENSION = 1920
MAX_STEPS = 100
MAX_CFG = 20.0
ANIMA_LATENT_CHANNELS = 16
NO_LORA = "None"
LEGACY_LORA_SLOT_COUNT = 3
MIN_LORA_STRENGTH = -100.0
MAX_LORA_STRENGTH = 100.0


def _registered_filename(kind: str, name: str) -> str:
    """Resolve only names exposed by ComfyUI's registered model folders."""
    if name not in folder_paths.get_filename_list(kind):
        raise ValueError(f"{kind} model is not registered: {name!r}")
    path = folder_paths.get_full_path_or_raise(kind, name)
    if not os.path.isfile(path):
        raise ValueError(f"{kind} model is not a readable file: {name!r}")
    return path


def _validate_request(width: int, height: int, steps: int, cfg: float) -> None:
    for label, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{label} must be an integer.")
        if value < MIN_DIMENSION or value > MAX_DIMENSION or value % 16:
            raise ValueError(
                f"{label} must be a multiple of 16 between "
                f"{MIN_DIMENSION} and {MAX_DIMENSION}; got {value}."
            )
    if not isinstance(steps, int) or isinstance(steps, bool):
        raise ValueError("steps must be an integer.")
    if not 1 <= steps <= MAX_STEPS:
        raise ValueError(f"steps must be between 1 and {MAX_STEPS}; got {steps}.")
    if not isinstance(cfg, (int, float)) or isinstance(cfg, bool) or not math.isfinite(cfg):
        raise ValueError("cfg must be a finite number.")
    if not 0.0 <= cfg <= MAX_CFG:
        raise ValueError(f"cfg must be between 0 and {MAX_CFG}; got {cfg}.")


def _validate_sampling(seed: int, sampler: str, scheduler: str) -> None:
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("seed must be an unsigned 64-bit integer.")
    if not isinstance(sampler, str) or not isinstance(scheduler, str):
        raise ValueError("sampler and scheduler must be strings.")
    if sampler not in comfy.samplers.KSampler.SAMPLERS:
        raise ValueError(f"Unsupported sampler for this ComfyUI installation: {sampler!r}.")
    if scheduler not in comfy.samplers.KSampler.SCHEDULERS:
        raise ValueError(f"Unsupported scheduler for this ComfyUI installation: {scheduler!r}.")


def _validate_prompts(positive_prompt: str, negative_prompt: str) -> None:
    if not isinstance(positive_prompt, str) or not positive_prompt.strip():
        raise ValueError("positive_prompt must be a non-empty string.")
    if not isinstance(negative_prompt, str):
        raise ValueError("negative_prompt must be a string.")


def _validate_anima_model(model: object, name: str) -> None:
    base_model = getattr(model, "model", None)
    if base_model is None or type(base_model).__name__ != "Anima":
        detected = type(base_model).__name__ if base_model is not None else "unknown"
        raise ValueError(
            f"diffusion model {name!r} is not an Anima model (detected {detected})."
        )


def _validate_anima_vae(vae: object, name: str) -> None:
    if getattr(vae, "latent_channels", None) != ANIMA_LATENT_CHANNELS:
        raise ValueError(
            f"VAE {name!r} is incompatible with Anima; expected "
            f"{ANIMA_LATENT_CHANNELS} latent channels."
        )


def _validate_anima_text_encoder(clip: object, name: str) -> None:
    tokenizer = getattr(clip, "tokenizer", None)
    if tokenizer is None or type(tokenizer).__name__ != "AnimaTokenizer":
        detected = type(tokenizer).__name__ if tokenizer is not None else "unknown"
        raise ValueError(
            f"text encoder {name!r} is not an Anima text encoder (detected {detected})."
        )


def _lora_options() -> list[str]:
    """Return the LoRA names registered in this ComfyUI installation."""
    return folder_paths.get_filename_list("loras")


def _validate_lora_selection(name: str, strength: float, slot: int) -> str | None:
    if not isinstance(name, str):
        raise ValueError(f"LoRA slot {slot} name must be a string.")
    if not isinstance(strength, (int, float)) or isinstance(strength, bool) or not math.isfinite(strength):
        raise ValueError(f"LoRA slot {slot} model strength must be a finite number.")
    if not MIN_LORA_STRENGTH <= strength <= MAX_LORA_STRENGTH:
        raise ValueError(
            f"LoRA slot {slot} model strength must be between "
            f"{MIN_LORA_STRENGTH} and {MAX_LORA_STRENGTH}; got {strength}."
        )
    if name == NO_LORA:
        return None
    _registered_filename("loras", name)
    return name


def _apply_anima_lora(model: object, name: str, strength: float, slot: int) -> object:
    """Apply one model-only LoRA and reject an adapter with no Anima patches."""
    if strength == 0:
        return model

    lora_path = _registered_filename("loras", name)
    try:
        lora, metadata = comfy.utils.load_torch_file(
            lora_path, safe_load=True, return_metadata=True
        )
        key_map = comfy.lora.model_lora_keys_unet(model.model, {})
        patches = comfy.lora.load_lora(
            comfy.lora_convert.convert_lora(lora), key_map, log_missing=False
        )
        patched_model = model.clone()
        applied = patched_model.add_patches(patches, strength)
    except Exception as error:
        raise ValueError(f"Could not load LoRA slot {slot} {name!r}: {error}") from error

    if not applied:
        raise ValueError(
            f"LoRA slot {slot} {name!r} has no patches compatible with the selected Anima model."
        )
    if metadata:
        patched_model.set_attachments("lora_metadata", metadata)
    return patched_model


def _parse_lora_stack(lora_stack: str | None, legacy_inputs: dict[str, object]) -> list[tuple[str, float]]:
    """Decode the ordered frontend/API LoRA stack or a legacy three-slot prompt."""
    legacy_names = {
        f"lora_{slot}_{field}"
        for slot in range(1, LEGACY_LORA_SLOT_COUNT + 1)
        for field in ("name", "strength")
    }
    unknown_inputs = set(legacy_inputs) - legacy_names
    if unknown_inputs:
        raise ValueError(f"Unsupported input(s): {', '.join(sorted(unknown_inputs))}.")

    if lora_stack is None:
        return [
            (
                legacy_inputs.get(f"lora_{slot}_name", NO_LORA),
                legacy_inputs.get(f"lora_{slot}_strength", 1.0),
            )
            for slot in range(1, LEGACY_LORA_SLOT_COUNT + 1)
        ]
    if legacy_inputs:
        raise ValueError("Use either lora_stack or legacy LoRA slots, not both.")
    if not isinstance(lora_stack, str):
        raise ValueError("lora_stack must be a JSON string.")
    try:
        entries = json.loads(lora_stack)
    except json.JSONDecodeError as error:
        raise ValueError(f"lora_stack must be valid JSON: {error.msg}.") from error
    if not isinstance(entries, list):
        raise ValueError("lora_stack must be a JSON array.")

    selections: list[tuple[str, float]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or set(entry) != {"name", "strength"}:
            raise ValueError(f"LoRA stack entry {index} must contain only name and strength.")
        if not isinstance(entry["name"], str):
            raise ValueError(f"LoRA stack entry {index} name must be a string.")
        if not isinstance(entry["strength"], (int, float)) or isinstance(entry["strength"], bool) or not math.isfinite(entry["strength"]):
            raise ValueError(f"LoRA stack entry {index} strength must be a finite number.")
        selections.append((entry["name"], entry["strength"]))
    return selections


def _apply_anima_loras(
    model: object, selections: list[tuple[str, float]]
) -> object:
    for slot, (name, strength) in enumerate(selections, start=1):
        name = _validate_lora_selection(name, strength, slot)
        if name is not None:
            model = _apply_anima_lora(model, name, strength, slot)
    return model


def _empty_anima_latent(width: int, height: int) -> dict[str, torch.Tensor]:
    """Build the one-frame, 16-channel Wan21 latent Anima expects."""
    latent = torch.zeros(
        [1, ANIMA_LATENT_CHANNELS, 1, height // 8, width // 8],
        device=comfy.model_management.intermediate_device(),
        dtype=comfy.model_management.intermediate_dtype(),
    )
    return {"samples": latent}


class AtelierXAnimaGenerate(io.ComfyNode):
    """Generate one image with an installed Anima diffusion model."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AtelierXAnimaGenerate",
            display_name="AtelierX Anima Generate",
            category="AtelierX/generation",
            description="Text-to-image generation for Anima diffusion models. Returns IMAGE only.",
            inputs=[
                io.Combo.Input("diffusion_model", options=folder_paths.get_filename_list("diffusion_models")),
                io.Combo.Input("text_encoder", options=folder_paths.get_filename_list("text_encoders")),
                io.Combo.Input("vae", options=folder_paths.get_filename_list("vae")),
                io.String.Input("positive_prompt", multiline=True),
                io.String.Input("negative_prompt", multiline=True, default=""),
                io.Int.Input("width", default=1024, min=MIN_DIMENSION, max=MAX_DIMENSION, step=16),
                io.Int.Input("height", default=1024, min=MIN_DIMENSION, max=MAX_DIMENSION, step=16),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF),
                io.Int.Input("steps", default=24, min=1, max=MAX_STEPS),
                io.Float.Input("cfg", default=4.5, min=0.0, max=MAX_CFG, step=0.1, round=0.1),
                io.Combo.Input("sampler", options=comfy.samplers.KSampler.SAMPLERS, default="euler_ancestral"),
                io.Combo.Input("scheduler", options=comfy.samplers.KSampler.SCHEDULERS, default="normal"),
                io.String.Input("lora_stack", default="[]", optional=True, extra_dict={"atelierx_lora_stack": {"options": _lora_options()}}, tooltip="Ordered Anima LoRA stack controlled by the AtelierX LoRA widget."),
            ],
            outputs=[io.Image.Output(display_name="image")],
            accept_all_inputs=True,
        )

    @classmethod
    def execute(
        cls,
        diffusion_model: str,
        text_encoder: str,
        vae: str,
        positive_prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        seed: int,
        steps: int,
        cfg: float,
        sampler: str,
        scheduler: str,
        lora_stack: str | None = None,
        **legacy_inputs: object,
    ) -> io.NodeOutput:
        _validate_request(width, height, steps, cfg)
        _validate_sampling(seed, sampler, scheduler)
        _validate_prompts(positive_prompt, negative_prompt)

        model_path = _registered_filename("diffusion_models", diffusion_model)
        text_encoder_path = _registered_filename("text_encoders", text_encoder)
        _registered_filename("vae", vae)

        model = comfy.sd.load_diffusion_model(model_path)
        _validate_anima_model(model, diffusion_model)
        model = _apply_anima_loras(
            model,
            _parse_lora_stack(lora_stack, legacy_inputs),
        )

        clip = comfy.sd.load_clip(
            ckpt_paths=[text_encoder_path],
            embedding_directory=folder_paths.get_folder_paths("embeddings"),
        )
        _validate_anima_text_encoder(clip, text_encoder)
        vae_model = nodes.VAELoader().load_vae(vae)[0]
        _validate_anima_vae(vae_model, vae)

        positive = clip.encode_from_tokens_scheduled(clip.tokenize(positive_prompt))
        negative = clip.encode_from_tokens_scheduled(clip.tokenize(negative_prompt))
        sampled = nodes.common_ksampler(
            model,
            seed,
            steps,
            cfg,
            sampler,
            scheduler,
            positive,
            negative,
            _empty_anima_latent(width, height),
            denoise=1.0,
        )[0]
        images = vae_model.decode(sampled["samples"])
        if len(images.shape) == 5:
            images = images.reshape(-1, images.shape[-3], images.shape[-2], images.shape[-1])
        return io.NodeOutput(images)


class AtelierXAnimaExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AtelierXAnimaGenerate]
