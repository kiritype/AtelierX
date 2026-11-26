"""Compatibility with the official MossRef v2 single-reference workflow."""

from pathlib import PureWindowsPath

from ..core.i18n import Msg
from . import comfy_locate

ENGINE = 'mossref'
NODE = 'MossRefApply'
EDIT_NODE = 'TextEncodeMOSSImageEdit'
EDIT_IMAGE = 'images.image_0'
WEIGHT = 'anime_textref_v2_bf16.safetensors'
FOUNDATION = 'Moss-Image-Edit'
FOUNDATION_FILES = ('adapter_config.json', 'adapter_model.safetensors')
PROVENANCE = {
    'node': NODE,
    'expected_node_commit': 'ee5847bb0dcce36d2d004df0e94dd6c84c3a24e1',
    'weights': WEIGHT,
    'expected_weights_sha256': 'cecbcd929c6a3365ef8ca07955aa370fe3baba82348501e6223334e31f26a071',
    'foundation': 'chinoll/Moss-Image-Edit',
    'foundation_revision': '3be9c40037e1b89b17aa85ff6f8ee805872aa558',
    'expected_foundation_weights_sha256': '17a48b8c605dcffdedb92a2b887d18cf316505be90802717669fb6556098dcdf',
    'edit_node': EDIT_NODE,
}
PARAMETERS = {
    'role': 'auto',
    'cfg_reference': 'positive',
    'ref_edge': 768,
    'ref_attn_bias': 0.35,
    'target_strength': 0.85,
    'edit_format': 'ai-toolkit',
    'image_strength': 0.05,
}
DEFAULTS = {
    'cfg': 3.5,
    'steps': 35,
    'sampler': 'euler',
    'scheduler': 'sgm_uniform',
    'shift': None,
    'moss_slg': False,
}
CHOICES = {
    'models': {
        'moss_image_sft_bf16.safetensors',
        'moss_image_sft_int8_convrot.safetensors',
        'moss-image-sft-dit-int8-convrot.safetensors',
    },
    'text_encoders': {
        'qwen3.5_9b_bf16.safetensors',
        'qwen3.5_9b_int8_convrot.safetensors',
        'moss-image-sft-qwen35-int8-convrot.safetensors',
    },
    'vaes': {'flux2-vae.safetensors', 'moss-image-sft-vae.safetensors'},
}
SETTING_GROUPS = {'model': 'models', 'text_encoder': 'text_encoders', 'vae': 'vaes'}


def components(catalog):
    """Return exact catalog IDs of the known SFT and its vision encoder and VAE."""
    result = {
        kind: [name for name in catalog.get(kind, []) if PureWindowsPath(name).name in filenames]
        for kind, filenames in CHOICES.items()
    }
    entries = catalog.get('model_entries', {})
    result['models'] = [
        name for name in result['models'] if entries.get(name, {}).get('loader', 'UNETLoader') == 'UNETLoader'
    ]
    return result


def _schema(comfy, node_name):
    try:
        info = comfy.request(f'/object_info/{node_name}', timeout=3)
        schema = info[node_name]
        return schema['input']['required'], schema['input'].get('optional', {}), schema.get('output', [])
    except (RuntimeError, ValueError, AttributeError, KeyError, TypeError):
        return {}, {}, []


def _options(spec):
    # ComfyUI's legacy list combo and V3 COMBO both occur in /object_info.
    return spec[0] if isinstance(spec[0], list) else spec[-1].get('options', [])


def _adapter_ready(comfy):
    required, optional, outputs = _schema(comfy, NODE)
    try:
        return (
            required['model'][0] == 'MODEL'
            and required['vae'][0] == 'VAE'
            and required['reference_image'][0] == 'IMAGE'
            and WEIGHT in _options(required['adapter'])
            and 'auto' in _options(required['role'])
            and 'positive' in _options(required['cfg_reference'])
            and required['ref_edge'][0] == 'INT'
            and optional['positive'][0] == 'CONDITIONING'
            and 'auto' in _options(optional['role_2'])
            and 'auto' in _options(optional['role_3'])
            and optional['foundation_dir'][0] == 'STRING'
            and optional['custom_adapter_path'][0] == 'STRING'
            and optional['ref_attn_bias'][0] == 'FLOAT'
            and optional['target_strength'][0] == 'FLOAT'
            and outputs[:1] == ['MODEL']
        )
    except (AttributeError, IndexError, KeyError, TypeError):
        return False


def _encoder_ready(comfy):
    required, _, outputs = _schema(comfy, EDIT_NODE)
    try:
        images = required['images']
        template = images[1]['template']
        return (
            required['clip'][0] == 'CLIP'
            and required['prompt'][0] == 'STRING'
            and 'ai-toolkit' in _options(required['edit_format'])
            and images[0] == 'COMFY_AUTOGROW_V3'
            and template['prefix'] == 'image_'
            and template['input']['required']['image'][0] == 'IMAGE'
            and required['image_strength'][0] == 'FLOAT'
            and outputs[:1] == ['CONDITIONING']
        )
    except (AttributeError, IndexError, KeyError, TypeError):
        return False


def status(comfy, catalog):
    choices = components(catalog)
    node = _adapter_ready(comfy)
    encoder = _encoder_ready(comfy)
    model_root = comfy_locate.running_models_root(comfy.url)
    weights = foundation = None
    if model_root is not None:
        root = model_root / 'moss_ref'
        weights = (root / WEIGHT).is_file()
        foundation = all((root / FOUNDATION / file).is_file() for file in FOUNDATION_FILES)
    return {
        'ready': bool(
            node
            and encoder
            and catalog.get('nodes', {}).get('moss')
            and all(choices.values())
            and weights is not False
            and foundation is not False
        ),
        'node_ready': node,
        'edit_node_ready': encoder,
        'weights_ready': weights,
        'foundation_ready': foundation,
        **choices,
    }


def require_ready(readiness):
    if not readiness['node_ready']:
        raise ValueError(Msg('server.reference.moss_node', 'Install MossRef v2.0.0 and restart ComfyUI.'))
    if not readiness['edit_node_ready']:
        raise ValueError(
            Msg('server.reference.moss_encoder', 'Update ComfyUI to use Text Encode MOSS-Image Edit.')
        )
    if readiness['weights_ready'] is False:
        raise ValueError(
            Msg('server.reference.moss_weights', 'Place the MossRef v2 weights in ComfyUI/models/moss_ref.')
        )
    if readiness['foundation_ready'] is False:
        raise ValueError(
            Msg(
                'server.reference.moss_foundation',
                'Place both Moss-Image-Edit foundation files in ComfyUI/models/moss_ref/Moss-Image-Edit.',
            )
        )
    if not readiness['ready']:
        raise ValueError(
            Msg(
                'server.reference.moss_components',
                'Choose a supported MOSS-Image-SFT model, Qwen3.5-9B encoder, and Flux2 VAE.',
            )
        )


def validate_settings(settings, choices):
    if settings.get('family') != 'moss' or any(
        settings.get(key) not in choices[group] for key, group in SETTING_GROUPS.items()
    ):
        raise ValueError(
            Msg(
                'server.reference.moss_components',
                'Choose a supported MOSS-Image-SFT model, Qwen3.5-9B encoder, and Flux2 VAE.',
            )
        )
    if settings.get('moss_slg') or any(item.get('enabled', True) for item in settings.get('loras', [])):
        raise ValueError(
            Msg('server.reference.moss_options', 'Turn off LoRA and Skip Layer Guidance for MossRef.')
        )
