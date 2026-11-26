"""The pinned Anima adapters and two-person composition through ComfyUI."""

from ..core.i18n import Msg
from .comfy import REFERENCE_NODE, REFERENCE_WEIGHT

ANIMA_V2 = 'anima_v2'
SNAPREF = 'snapref'
ADAPTERS = {ANIMA_V2: REFERENCE_WEIGHT, SNAPREF: 'snapref_v2a.safetensors'}
SHA256 = {
    ANIMA_V2: '71dda6079e18d354e16e3347bc49a9b710afd9495c378efbb833d30cac9cb81b',
    SNAPREF: '8a22fc28d060447544eda283b36efe2dcdbad7422cbc0b8d42828d55a8a61ab4',
}
NODE_COMMIT = 'f02d54dd34593b4d4ce27b38de2a996049aeac58'
DEFAULT_GUIDANCE = 4.5
STITCH = 'ImageStitch'
STITCH_SETTINGS = {
    'direction': 'right',
    'match_image_size': True,
    'spacing_width': 0,
    'spacing_color': 'white',
}


def is_entry(entry):
    return isinstance(entry, dict) and entry.get('engine') in (ANIMA_V2, SNAPREF)


def provenance(engine):
    return {
        'node': REFERENCE_NODE,
        'expected_node_commit': NODE_COMMIT,
        'weights': ADAPTERS[engine],
        'expected_weights_sha256': SHA256[engine],
    }


def _object_info(comfy, node):
    try:
        info = comfy.request(f'/object_info/{node}')
        schema = info.get(node)
        return schema if isinstance(schema, dict) else None
    except (RuntimeError, AttributeError, ValueError):
        return None


def status(comfy):
    schema = _object_info(comfy, REFERENCE_NODE)
    try:
        loras = comfy.request('/models/loras')
    except (RuntimeError, ValueError):
        loras = []
    optional = (schema or {}).get('input', {}).get('optional', {})
    snap_ready = isinstance(optional, dict) and all(
        key in optional for key in ('clip', 'snapref_mode', 'ref_caption', 'snapref_guidance', 'ref_weight')
    )
    adapters = {}
    for engine, weights in ADAPTERS.items():
        node_ready = schema is not None and (engine == ANIMA_V2 or snap_ready)
        weights_ready = isinstance(loras, list) and weights in loras
        adapters[engine] = {
            'ready': node_ready and weights_ready,
            'node_ready': node_ready,
            'weights_ready': weights_ready,
        }
    return {
        **adapters[ANIMA_V2],
        'adapters': adapters,
        'stitch_ready': _object_info(comfy, STITCH) is not None,
    }


def require_ready(comfy, entry):
    info = status(comfy)
    adapter = info['adapters'][entry['engine']]
    if not adapter['node_ready']:
        if entry['engine'] == SNAPREF:
            raise ValueError(
                Msg(
                    'server.reference.snapref_node',
                    'Install an Anima Ref Adapter with SnapRef support and restart ComfyUI.',
                )
            )
        raise ValueError(
            Msg(
                'server.reference.missing_node',
                'Install Anima Ref Adapter in Settings → Install, then restart ComfyUI.',
            )
        )
    if not adapter['weights_ready']:
        if entry['engine'] == SNAPREF:
            raise ValueError(
                Msg(
                    'server.reference.snapref_weights',
                    'Install the SnapRef v2a weights in Settings → Install.',
                )
            )
        raise ValueError(
            Msg(
                'server.reference.missing_weights',
                'Install the Anima reference weights in Settings → Install.',
            )
        )
    if len(entry['subjects']) == 2 and not info['stitch_ready']:
        raise ValueError(
            Msg('server.reference.stitch_node', 'Update ComfyUI to use the Image Stitch node for two people.')
        )


def scene_with_subjects(scene, subjects):
    if len(subjects) == 1:
        return scene
    sentences = [
        scene.rstrip(' ,'),
        'Two people',
        *(
            f'The person on the {subject["position"]} is {subject["description"]}'
            for subject in sorted(subjects, key=lambda item: item['position'])
            if subject['description']
        ),
    ]
    return ' '.join(text if text.endswith(('.', '!', '?')) else text + '.' for text in sentences)
