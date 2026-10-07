"""Build and validate the ComfyUI graph for one image (anima or SDXL family)."""

from __future__ import annotations

import math
from pathlib import PureWindowsPath
from typing import Any

from ..core.i18n import Msg
from . import extensions

DEFAULTS: dict[str, Any] = {
    'model': 'anima_aestheticV11.safetensors',
    'text_encoder': 'qwen_3_06b_base.safetensors',
    'vae': 'qwen_image_vae.safetensors',
    'clip_type': 'stable_diffusion',
    'text_encoder_device': 'default',
    'steps': 32,
    'cfg': 5.0,
    'sampler': 'er_sde',
    'scheduler': 'simple',
    'width': 1536,
    'height': 1536,
    'seed': -1,
    'loras': [],
}

# The app's ComfyUI node pack (comfy_nodes/atelierx_nodes) and the detailer's detectors, shared with the image tools.
NODE_PREFIX = 'AtelierX'
DETAIL_STAGES = ('face', 'eye', 'mouth', 'hand')
DETECTORS = {
    'face': 'bbox/face_yolov8m.pt',
    'eye': 'segm/PitEyeDetailer-v2-seg.pt',
    'mouth': 'bbox/face_yolov8m.pt',
    'hand': 'bbox/hand_yolov8s.pt',
}
SAM_MODEL = 'sam_vit_b_01ec64.pth'

_CATALOG_KEYS = {
    'model': 'models',
    'text_encoder': 'text_encoders',
    'vae': 'vaes',
    'clip_type': 'clip_types',
    'sampler': 'samplers',
    'scheduler': 'schedulers',
}


def defaults(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return defaults, preferring known choices that are actually installed."""
    result = {**DEFAULTS, 'loras': []}
    if not isinstance(catalog, dict):
        return result
    supplied = catalog.get('defaults')
    if isinstance(supplied, dict):
        result.update(supplied)
    for key, catalog_key in _CATALOG_KEYS.items():
        choices = _choice_names(catalog.get(catalog_key))
        if choices and result[key] not in choices:
            result[key] = choices[0]
    return result


def _resolve(value: Any, choices: list[str]) -> Any:
    """``value`` as listed by ComfyUI. Files moved into a sub-folder (``anima\\x``) after a
    record was written are found by file name when exactly one entry matches."""
    if not isinstance(value, str) or value in choices:
        return value
    prefix, _, name = value.rpartition('::')

    def split(entry: str) -> tuple[str, str]:
        head, _, tail = entry.rpartition('::')
        return head, PureWindowsPath(tail).name

    wanted = (prefix, PureWindowsPath(name).name)
    found = [entry for entry in choices if split(entry) == wanted]
    return found[0] if len(found) == 1 else value


def _choice_names(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    names: list[str] = []
    for value in values:
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, dict):
            name = value.get('name', value.get('value', value.get('title')))
            if isinstance(name, str):
                names.append(name)
    return names


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a finite number')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label} must be a finite number') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label} must be a finite number')
    return number


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f'{label} must be an integer')
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label} must be an integer') from exc
    if isinstance(value, float) and number != value:
        raise ValueError(f'{label} must be an integer')
    if isinstance(value, str) and str(number) != value.strip():
        raise ValueError(f'{label} must be an integer')
    return number


FAMILIES = ('anima', 'sdxl')
# SDXL checkpoints carry their own text encoder and VAE.
SDXL_UNUSED = ('text_encoder', 'clip_type', 'text_encoder_device')


def validate_settings(settings: dict[str, Any] | None, catalog: dict[str, Any]) -> dict[str, Any]:
    """Validate user selections against ComfyUI catalog choices and normalize values.

    ``family`` picks the graph: ``anima`` (diffusion model + text encoder + VAE) or
    ``sdxl`` (one checkpoint; optional VAE override and CLIP skip).
    """
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object')
    if not isinstance(catalog, dict):
        raise ValueError('catalog must be an object')
    family = settings.get('family') or 'anima'
    if family not in FAMILIES:
        raise ValueError('family must be anima or sdxl')
    result = defaults(catalog)
    if family == 'sdxl':
        for key in SDXL_UNUSED:
            result.pop(key, None)
        result['vae'] = ''  # Built-in VAE unless the request names one.
    result.update(settings)
    result['family'] = family

    for key, catalog_key in _CATALOG_KEYS.items():
        if family == 'sdxl' and key in SDXL_UNUSED:
            result.pop(key, None)
            continue
        if family == 'sdxl' and key == 'vae' and not result.get('vae'):
            continue
        choices = _choice_names(catalog.get(catalog_key))
        value = result[key] = _resolve(result.get(key), choices)
        if not choices:
            raise ValueError(f'catalog.{catalog_key} must contain available choices')
        if key in ('sampler', 'scheduler'):
            # Node-pack names are checked with the patches (#178).
            if not isinstance(value, str) or not value:
                raise ValueError(f'{key} must be one of the available {catalog_key}')
            continue
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f'{key} must be one of the available {catalog_key}')

    device = result.get('text_encoder_device', 'default')
    entry = catalog.get('model_entries', {}).get(result['model'])
    # Resolve from the server catalog, never trust client-supplied loader/path overrides.
    result['model_loader'] = entry['loader'] if entry else 'UNETLoader'
    result['model_filename'] = entry['filename'] if entry else result['model']
    if family == 'sdxl':
        if result['model_loader'] != 'CheckpointLoaderSimple':
            raise ValueError(
                Msg(
                    'server.workflow.sdxl_needs_a_checkpoint_model',
                    'SDXL needs a checkpoint model.',
                )
            )
        result['clip_skip'] = _integer(result.get('clip_skip', 2), 'clip_skip')
        if not 1 <= result['clip_skip'] <= 12:
            raise ValueError('clip_skip must be between 1 and 12')
    else:
        if device not in ('default', 'cpu'):
            raise ValueError("text_encoder_device must be 'default' or 'cpu'")
        result['text_encoder_device'] = device

    result['steps'] = _integer(result.get('steps'), 'steps')
    if not 1 <= result['steps'] <= 100:
        raise ValueError('steps must be between 1 and 100')
    result['cfg'] = _finite_number(result.get('cfg'), 'cfg')
    if not 0 <= result['cfg'] <= 30:
        raise ValueError('cfg must be between 0 and 30')
    for key in ('width', 'height'):
        result[key] = _integer(result.get(key), key)
        if not 256 <= result[key] <= 3072 or result[key] % 16:
            raise ValueError(f'{key} must be a multiple of 16 between 256 and 3072')
    result['seed'] = _integer(result.get('seed'), 'seed')
    if not -1 <= result['seed'] <= 2**53 - 1:
        raise ValueError('seed must be between -1 and 2**53 - 1')

    loras = result.get('loras', [])
    if not isinstance(loras, list):
        raise ValueError('loras must be a list')
    lora_choices = _choice_names(catalog.get('loras'))
    normalized_loras = []
    for index, item in enumerate(loras):
        if index >= 16:
            raise ValueError('loras cannot contain more than 16 entries')
        if isinstance(item, str):
            item = {'name': item}
        if not isinstance(item, dict):
            raise ValueError(f'loras[{index}] must be an object')
        name = _resolve(item.get('name'), lora_choices)
        if not isinstance(name, str) or name not in lora_choices:
            raise ValueError(f'loras[{index}].name must be an available LoRA')
        strength_model = _finite_number(item.get('strength_model', 1.0), f'loras[{index}].strength_model')
        strength_clip = _finite_number(item.get('strength_clip', 1.0), f'loras[{index}].strength_clip')
        if not -10 <= strength_model <= 10 or not -10 <= strength_clip <= 10:
            raise ValueError(f'loras[{index}] strengths must be between -10 and 10')
        entry = {'name': name, 'strength_model': strength_model, 'strength_clip': strength_clip}
        # Off: kept in the list, left out of the graph (#168). Only written when off, so older records read the same.
        if item.get('enabled') is False:
            entry['enabled'] = False
        normalized_loras.append(entry)
    result['loras'] = normalized_loras

    # Model sampling shift (#168), for Anima's flow models; SDXL has none.
    shift = result.get('shift')
    if shift in (None, '') or family == 'sdxl':
        result['shift'] = None
    else:
        result['shift'] = _finite_number(shift, 'shift')
        if not 0.5 <= result['shift'] <= 20:
            raise ValueError('shift must be between 0.5 and 20')
    result['upscale'] = _upscale_settings(result.get('upscale'), catalog)
    result['detailer'] = _detailer_settings(result.get('detailer'), catalog)
    # Custom nodes (#178): model patches, node-pack sampler names, and what to do when they are missing.
    extensions.apply(result, catalog, lambda key: _choice_names(catalog.get(key)), defaults(catalog))
    return result


def _missing_nodes(catalog, part):
    # A catalog that does not say (tests, older callers) is taken as having the nodes.
    return (catalog.get('nodes') or {}).get(part) is False


def _upscale_settings(value, catalog):
    """After the first pass: enlarge with an upscale model to ``scale``, then redraw lightly (#168). None: off."""
    # None or false: off. An object (even empty) is on, with defaults for what it leaves out.
    if value is None or value is False:
        return None
    if not isinstance(value, dict):
        raise ValueError('upscale must be an object')
    if _missing_nodes(catalog, 'upscale'):
        raise ValueError(
            Msg(
                'server.workflow.upscale_nodes',
                'The upscale node is not in ComfyUI. Install the nodes in Settings → Install, then restart ComfyUI.',
            )
        )
    models = _choice_names(catalog.get('upscale_models'))
    model = _resolve(value.get('model') or (models[0] if models else ''), models)
    if not isinstance(model, str) or not model or (models and model not in models):
        raise ValueError(Msg('server.workflow.upscale_model', 'Choose an installed upscale model.'))
    out = {'model': model}
    for key, low, high, default, kind in (
        ('scale', 1, 4, 1.5, float),
        ('steps', 1, 100, 12, int),
        ('denoise', 0.05, 1, 0.3, float),
    ):
        raw = value.get(key, default)
        number = _integer(raw, f'upscale.{key}') if kind is int else _finite_number(raw, f'upscale.{key}')
        if not low <= number <= high:
            raise ValueError(f'upscale.{key} must be between {low} and {high}')
        out[key] = number
    # Left out: the first pass's CFG.
    if value.get('cfg') not in (None, ''):
        out['cfg'] = _finite_number(value['cfg'], 'upscale.cfg')
        if not 0 <= out['cfg'] <= 30:
            raise ValueError('upscale.cfg must be between 0 and 30')
    return out


def _detailer_settings(value, catalog):
    """Redraw the chosen parts, each with its own denoise, in face → eye → mouth → hand order. None: off."""
    if not value:
        return None
    if not isinstance(value, dict):
        raise ValueError('detailer must be an object')
    stages = value.get('stages') or {}
    if not isinstance(stages, dict):
        raise ValueError('detailer.stages must be an object')
    chosen = {}
    for stage in DETAIL_STAGES:
        if stages.get(stage) is None:
            continue
        denoise = _finite_number(stages[stage], f'detailer.stages.{stage}')
        if not 0.05 <= denoise <= 1:
            raise ValueError(f'detailer.stages.{stage} must be between 0.05 and 1')
        chosen[stage] = denoise
    if not chosen:
        return None
    if _missing_nodes(catalog, 'detailer'):
        raise ValueError(
            Msg(
                'server.workflow.detailer_nodes',
                'The detailer nodes are not in ComfyUI. Install them in Settings → Install, then restart ComfyUI.',
            )
        )
    steps = _integer(value.get('steps', 20), 'detailer.steps')
    if not 1 <= steps <= 60:
        raise ValueError('detailer.steps must be between 1 and 60')
    return {'stages': chosen, 'steps': steps}


def upscale_node(image, model, scale, prefix=NODE_PREFIX):
    """The node pack's upscaler: an upscale model, then a resize to ``scale`` of the input."""
    return {
        'class_type': f'{prefix}Upscale',
        'inputs': {'image': image, 'upscale_model': model, 'scale': scale},
    }


def detailer_node(image, refs, enabled, *, seed, steps, cfg, sampler, scheduler, denoise, prefix=NODE_PREFIX):
    """The Impact detailer pipeline over ``image`` with the given parts on. ``refs``: model, clip, vae, positive,
    negative of the graph that made the image."""
    return {
        'class_type': f'{prefix}ImpactDetailerPipeline',
        'inputs': {
            'image': image,
            **refs,
            **{f'{stage}_enabled': bool(enabled.get(stage)) for stage in DETAIL_STAGES},
            **{f'{stage}_detector_model': DETECTORS[stage] for stage in DETAIL_STAGES},
            'sam_model': SAM_MODEL,
            'seed': seed,
            'steps': steps,
            'cfg': cfg,
            'sampler_name': sampler,
            'scheduler': scheduler,
            'denoise': denoise,
        },
    }


def build_workflow(settings: dict[str, Any], positive: str, negative: str, seed: int) -> dict[str, Any]:
    """Build a deterministic, plain ComfyUI API prompt graph."""
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object')
    if not isinstance(positive, str) or not isinstance(negative, str):
        raise ValueError('positive and negative prompts must be strings')
    actual_seed = _integer(seed, 'seed')
    if actual_seed < 0 or actual_seed > 2**53 - 1:
        raise ValueError('seed must be between 0 and 2**53 - 1 when building a workflow')
    loras = settings.get('loras', [])
    if not isinstance(loras, list):
        raise ValueError('loras must be a list')

    model_ref: list[Any] = ['1', 0]
    clip_ref: list[Any] = ['2', 0]
    vae_ref: list[Any] = ['3', 0]
    if settings.get('family') == 'sdxl':
        # One checkpoint: its CLIP (cut at clip_skip) and, unless overridden, its VAE.
        graph = {
            '1': {
                'class_type': 'CheckpointLoaderSimple',
                'inputs': {'ckpt_name': settings['model_filename']},
            },
            '2': {
                'class_type': 'CLIPSetLastLayer',
                'inputs': {
                    'clip': ['1', 1],
                    'stop_at_clip_layer': -int(settings.get('clip_skip', 2)),
                },
            },
        }
        vae_ref = ['1', 2]
        if settings.get('vae'):
            graph['3'] = {'class_type': 'VAELoader', 'inputs': {'vae_name': settings['vae']}}
            vae_ref = ['3', 0]
    else:
        graph: dict[str, Any] = {
            '1': {
                'class_type': 'UNETLoader',
                'inputs': {'unet_name': settings['model'], 'weight_dtype': 'default'},
            },
            '2': {
                'class_type': 'CLIPLoader',
                'inputs': {
                    'clip_name': settings['text_encoder'],
                    'type': settings.get('clip_type', 'stable_diffusion'),
                    'device': settings.get('text_encoder_device', 'default'),
                },
            },
            '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': settings['vae']}},
        }
        if settings.get('model_loader') == 'CheckpointLoaderSimple':
            graph['1'] = {
                'class_type': 'CheckpointLoaderSimple',
                'inputs': {'ckpt_name': settings['model_filename']},
            }
    next_id = 4
    for lora in loras:
        if isinstance(lora, str):
            lora = {'name': lora}
        if not isinstance(lora, dict) or not isinstance(lora.get('name'), str):
            raise ValueError('each LoRA must include a name')
        if lora.get('enabled') is False:
            continue
        node_id = str(next_id)
        graph[node_id] = {
            'class_type': 'LoraLoader',
            'inputs': {
                'model': model_ref,
                'clip': clip_ref,
                'lora_name': lora['name'],
                'strength_model': lora.get('strength_model', 1.0),
                'strength_clip': lora.get('strength_clip', 1.0),
            },
        }
        model_ref, clip_ref = [node_id, 0], [node_id, 1]
        next_id += 1
    if settings.get('shift') is not None and settings.get('family') != 'sdxl':
        graph[str(next_id)] = {
            'class_type': 'ModelSamplingAuraFlow',
            'inputs': {'model': model_ref, 'shift': settings['shift']},
        }
        model_ref = [str(next_id), 0]
        next_id += 1
    for patch in settings.get('patches') or []:
        if patch.get('enabled') is False:
            continue
        graph[str(next_id)] = {'class_type': patch['node'], 'inputs': {**patch['inputs'], 'model': model_ref}}
        model_ref = [str(next_id), 0]
        next_id += 1
    positive_id, negative_id, latent_id, sampler_id, decode_id, _preview_id = (
        str(next_id + n) for n in range(6)
    )
    graph[positive_id] = {
        'class_type': 'CLIPTextEncode',
        'inputs': {'text': positive, 'clip': clip_ref},
    }
    graph[negative_id] = {
        'class_type': 'CLIPTextEncode',
        'inputs': {'text': negative, 'clip': clip_ref},
    }
    graph[latent_id] = {
        'class_type': 'EmptyLatentImage',
        'inputs': {'width': settings['width'], 'height': settings['height'], 'batch_size': 1},
    }
    free = next_id + 6

    def add(node):
        nonlocal free
        graph[str(free)] = node
        free += 1
        return [str(free - 1), 0]

    def sample(node_id, latent, steps, cfg, denoise):
        """KSampler, or for a scheduler served by a built-in alias (beta57) the custom sampler with its sigmas."""
        sigmas = settings.get('sigmas')
        if not sigmas:
            node = {
                'class_type': 'KSampler',
                'inputs': {
                    'model': model_ref,
                    'positive': [positive_id, 0],
                    'negative': [negative_id, 0],
                    'latent_image': latent,
                    'seed': actual_seed,
                    'steps': steps,
                    'cfg': cfg,
                    'sampler_name': settings['sampler'],
                    'scheduler': settings['scheduler'],
                    'denoise': denoise,
                },
            }
        else:
            # Like KSampler's denoise: the schedule for steps / denoise, of which the last ``steps`` are run.
            total = steps if denoise >= 1 else int(steps / denoise)
            schedule = add(
                {
                    'class_type': 'BetaSamplingScheduler',
                    'inputs': {
                        'model': model_ref,
                        'steps': total,
                        'alpha': sigmas['alpha'],
                        'beta': sigmas['beta'],
                    },
                }
            )
            if total > steps:
                split = add(
                    {'class_type': 'SplitSigmas', 'inputs': {'sigmas': schedule, 'step': total - steps}}
                )
                schedule = [split[0], 1]
            node = {
                'class_type': 'SamplerCustomAdvanced',
                'inputs': {
                    'noise': add({'class_type': 'RandomNoise', 'inputs': {'noise_seed': actual_seed}}),
                    'guider': add(
                        {
                            'class_type': 'CFGGuider',
                            'inputs': {
                                'model': model_ref,
                                'positive': [positive_id, 0],
                                'negative': [negative_id, 0],
                                'cfg': cfg,
                            },
                        }
                    ),
                    'sampler': add(
                        {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': settings['sampler']}}
                    ),
                    'sigmas': schedule,
                    'latent_image': latent,
                },
            }
        if node_id is None:
            return add(node)
        graph[node_id] = node
        return [node_id, 0]

    sample(sampler_id, [latent_id, 0], settings['steps'], settings['cfg'], 1.0)
    graph[decode_id] = {
        'class_type': 'VAEDecode',
        'inputs': {'samples': [sampler_id, 0], 'vae': vae_ref},
    }
    image_ref = [decode_id, 0]

    upscale = settings.get('upscale')
    if upscale:
        # Enlarge, then redraw lightly at the new size with the same model, prompts and seed (#168).
        enlarged = add(upscale_node(image_ref, upscale['model'], upscale['scale']))
        latent = add({'class_type': 'VAEEncode', 'inputs': {'pixels': enlarged, 'vae': vae_ref}})
        redrawn = sample(
            None, latent, upscale['steps'], upscale.get('cfg', settings['cfg']), upscale['denoise']
        )
        image_ref = add({'class_type': 'VAEDecode', 'inputs': {'samples': redrawn, 'vae': vae_ref}})
    detailer = settings.get('detailer')
    if detailer:
        refs = {
            'model': model_ref,
            'clip': clip_ref,
            'vae': vae_ref,
            'positive': [positive_id, 0],
            'negative': [negative_id, 0],
        }
        # One pass per part so each keeps its own denoise; the order is the pipeline's own.
        for stage in DETAIL_STAGES:
            if stage in detailer['stages']:
                image_ref = add(
                    detailer_node(
                        image_ref,
                        refs,
                        {stage: True},
                        seed=actual_seed,
                        steps=detailer['steps'],
                        cfg=settings['cfg'],
                        sampler=settings['sampler'],
                        # The detailer has its own scheduler list; an aliased one is drawn with its built-in kin.
                        scheduler=(
                            settings['sigmas']['kind'] if settings.get('sigmas') else settings['scheduler']
                        ),
                        denoise=detailer['stages'][stage],
                    )
                )
    graph['output'] = {'class_type': 'PreviewImage', 'inputs': {'images': image_ref}}
    return graph


def pipeline_stages(settings):
    """The steps one generation goes through, for the job panel: generate, then upscale and detailer if on."""
    stages = ['generate']
    if (settings or {}).get('upscale'):
        stages.append('upscale')
    if (settings or {}).get('detailer'):
        stages.append('detailer')
    return stages


def build_ui_workflow(settings: dict[str, Any], positive: str, negative: str, seed: int) -> dict[str, Any]:
    """Build a standard ComfyUI workflow-editor export for the same generation graph."""
    prompt = build_workflow(settings, positive, negative, seed)
    numeric_ids = [int(key) for key in prompt if key.isdigit()]
    output_id = max(numeric_ids, default=0) + 1
    api_to_ui = {key: (output_id if key == 'output' else int(key)) for key in prompt}
    nodes: list[dict[str, Any]] = []
    links: list[list[Any]] = []
    link_id = 1

    # Socket definitions and widget order follow the built-in ComfyUI node schemas.
    specs: dict[str, tuple[list[tuple[str, str]], list[tuple[str, str]], list[Any]]] = {
        'CheckpointLoaderSimple': (
            [],
            [('MODEL', 'MODEL'), ('CLIP', 'CLIP'), ('VAE', 'VAE')],
            [settings.get('model_filename', settings['model'])],
        ),
        'UNETLoader': ([], [('MODEL', 'MODEL')], [settings['model'], 'default']),
        'CLIPLoader': (
            [],
            [('CLIP', 'CLIP')],
            [
                settings.get('text_encoder', ''),
                settings.get('clip_type', 'stable_diffusion'),
                settings.get('text_encoder_device', 'default'),
            ],
        ),
        'VAELoader': ([], [('VAE', 'VAE')], [settings.get('vae', '')]),
        'CLIPSetLastLayer': (
            [('clip', 'CLIP')],
            [('CLIP', 'CLIP')],
            [-int(settings.get('clip_skip', 2))],
        ),
        'LoraLoader': (
            [('model', 'MODEL'), ('clip', 'CLIP')],
            [('MODEL', 'MODEL'), ('CLIP', 'CLIP')],
            [],
        ),
        'CLIPTextEncode': ([('clip', 'CLIP')], [('CONDITIONING', 'CONDITIONING')], []),
        'EmptyLatentImage': (
            [],
            [('LATENT', 'LATENT')],
            [settings['width'], settings['height'], 1],
        ),
        'KSampler': (
            [
                ('model', 'MODEL'),
                ('positive', 'CONDITIONING'),
                ('negative', 'CONDITIONING'),
                ('latent_image', 'LATENT'),
            ],
            [('LATENT', 'LATENT')],
            [
                seed,
                'fixed',
                settings['steps'],
                settings['cfg'],
                settings['sampler'],
                settings['scheduler'],
                1.0,
            ],
        ),
        'VAEDecode': ([('samples', 'LATENT'), ('vae', 'VAE')], [('IMAGE', 'IMAGE')], []),
        'PreviewImage': ([('images', 'IMAGE')], [], []),
        # The steps after generation (#168).
        'ModelSamplingAuraFlow': ([('model', 'MODEL')], [('MODEL', 'MODEL')], []),
        'AtelierXUpscale': ([('image', 'IMAGE')], [('IMAGE', 'IMAGE')], []),
        'VAEEncode': ([('pixels', 'IMAGE'), ('vae', 'VAE')], [('LATENT', 'LATENT')], []),
        'AtelierXImpactDetailerPipeline': (
            [
                ('image', 'IMAGE'),
                ('model', 'MODEL'),
                ('clip', 'CLIP'),
                ('vae', 'VAE'),
                ('positive', 'CONDITIONING'),
                ('negative', 'CONDITIONING'),
            ],
            [('IMAGE', 'IMAGE')],
            [],
        ),
        # The custom sampler for an aliased scheduler (#178).
        'BetaSamplingScheduler': ([('model', 'MODEL')], [('SIGMAS', 'SIGMAS')], []),
        'SplitSigmas': ([('sigmas', 'SIGMAS')], [('high_sigmas', 'SIGMAS'), ('low_sigmas', 'SIGMAS')], []),
        'RandomNoise': ([], [('NOISE', 'NOISE')], []),
        'CFGGuider': (
            [('model', 'MODEL'), ('positive', 'CONDITIONING'), ('negative', 'CONDITIONING')],
            [('GUIDER', 'GUIDER')],
            [],
        ),
        'KSamplerSelect': ([], [('SAMPLER', 'SAMPLER')], []),
        'SamplerCustomAdvanced': (
            [
                ('noise', 'NOISE'),
                ('guider', 'GUIDER'),
                ('sampler', 'SAMPLER'),
                ('sigmas', 'SIGMAS'),
                ('latent_image', 'LATENT'),
            ],
            [('output', 'LATENT'), ('denoised_output', 'LATENT')],
            [],
        ),
    }
    # Model patches (#178): a model in, a model out, their settings as widgets.
    patch_spec = ([('model', 'MODEL')], [('MODEL', 'MODEL')], [])
    positions = {
        'CheckpointLoaderSimple': (40, 100),
        'UNETLoader': (40, 100),
        'CLIPLoader': (40, 300),
        'CLIPSetLastLayer': (40, 300),
        'VAELoader': (40, 500),
        'LoraLoader': (340, 200),
        'EmptyLatentImage': (650, 760),
        'KSampler': (1040, 370),
        'VAEDecode': (1390, 370),
        'PreviewImage': (1650, 370),
    }
    prompt_node_positions = [(650, 80), (650, 410)]
    prompt_node_index = 0
    # Nodes after the first pass go to the right of it, in order, and the preview after them.
    seen: set[str] = set()
    extra = 0

    for key, api_node in prompt.items():
        node_id = api_to_ui[key]
        node_type = api_node['class_type']
        input_defs, output_defs, widget_values = specs.get(node_type, patch_spec)
        values = api_node['inputs']
        if node_type == 'CLIPTextEncode':
            widget_values = [values['text']]
        elif node_type == 'KSampler':
            widget_values = [
                values['seed'],
                'fixed',
                values['steps'],
                values['cfg'],
                values['sampler_name'],
                values['scheduler'],
                values['denoise'],
            ]
        elif node_type == 'ModelSamplingAuraFlow':
            widget_values = [values['shift']]
        elif node_type == 'RandomNoise':
            widget_values = [values['noise_seed'], 'fixed']
        elif node_type not in specs or node_type in (
            'AtelierXUpscale',
            'AtelierXImpactDetailerPipeline',
            'BetaSamplingScheduler',
            'SplitSigmas',
            'CFGGuider',
            'KSamplerSelect',
        ):
            # Widget values in the order the node lists its settings.
            widget_values = [v for v in values.values() if not (isinstance(v, list) and len(v) == 2)]
        elif node_type == 'LoraLoader':
            values = api_node['inputs']
            widget_values = [values['lora_name'], values['strength_model'], values['strength_clip']]
        if node_type == 'CLIPTextEncode':
            x, y = prompt_node_positions[prompt_node_index]
            prompt_node_index += 1
        elif node_type == 'ModelSamplingAuraFlow':
            x, y = 340, 40
        elif node_type == 'PreviewImage' and extra:
            x, y = 1650 + 300 * extra, 370
        elif node_type not in positions or (node_type in ('KSampler', 'VAEDecode') and node_type in seen):
            x, y = 1650 + 300 * extra, 370
            extra += 1
        else:
            x, y = positions[node_type]
        seen.add(node_type)
        if node_type == 'LoraLoader':
            # Stack LoRAs vertically while keeping all other node IDs and positions fixed.
            lora_ordinal = sum(
                1
                for prior in prompt
                if prior != key
                and prior.isdigit()
                and int(prior) < int(key)
                and prompt[prior]['class_type'] == 'LoraLoader'
            )
            y += lora_ordinal * 180
        node = {
            'id': node_id,
            'type': node_type,
            'pos': [x, y],
            'size': {
                'CLIPTextEncode': [340, 280],
                'KSampler': [280, 280],
                'PreviewImage': [420, 420],
            }.get(node_type, [280, 100]),
            'flags': {},
            'order': len(nodes),
            'mode': 0,
            'inputs': [],
            'outputs': [],
            'properties': {'Node name for S&R': node_type},
            'widgets_values': widget_values,
        }
        for slot, (name, socket_type) in enumerate(input_defs):
            api_value = api_node['inputs'].get(name)
            input_link = None
            if isinstance(api_value, list) and len(api_value) == 2 and isinstance(api_value[0], str):
                origin_id = api_to_ui[api_value[0]]
                link = [link_id, origin_id, api_value[1], node_id, slot, socket_type]
                links.append(link)
                input_link = link_id
                # Output link bookkeeping is applied after all node objects exist.
                link_id += 1
            node['inputs'].append({'name': name, 'type': socket_type, 'link': input_link})
        for slot, (name, socket_type) in enumerate(output_defs):
            node['outputs'].append({'name': name, 'type': socket_type, 'links': [], 'slot_index': slot})
        nodes.append(node)

    nodes_by_id = {node['id']: node for node in nodes}
    for edge in links:
        _, origin_id, origin_slot, _, _, _ = edge
        nodes_by_id[origin_id]['outputs'][origin_slot]['links'].append(edge[0])
    return {
        'last_node_id': max(api_to_ui.values(), default=0),
        'last_link_id': link_id - 1,
        'nodes': nodes,
        'links': links,
        'groups': [],
        'config': {},
        'extra': {'ds': {'scale': 0.72, 'offset': [0, 0]}},
        'version': 0.4,
    }
