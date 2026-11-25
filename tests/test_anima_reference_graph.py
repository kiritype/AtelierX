"""Anima reference generation graphs and ComfyUI readiness checks (#336)."""

import pytest

from atelierx.image.comfy import REFERENCE_NODE, REFERENCE_WEIGHT, Comfy
from atelierx.image.workflow import DEFAULTS, build_ui_workflow, build_workflow


def test_reference_runs_after_loras_and_shift_on_the_first_pass_only():
    settings = {
        **DEFAULTS,
        'family': 'anima',
        'shift': 3.5,
        'loras': [
            {'name': 'style.safetensors', 'strength_model': 0.75},
            {'name': 'disabled.safetensors', 'enabled': False},
        ],
        'upscale': {'model': '2x.pth', 'scale': 1.5, 'steps': 12, 'denoise': 0.25},
        'detailer': {'stages': {'face': 0.35}, 'steps': 18},
    }
    args = (settings, 'positive', 'negative', 42)
    baseline = build_workflow(*args)
    assert all(node['class_type'] not in ('LoadImage', REFERENCE_NODE) for node in baseline.values())

    image_name = 'atelierx/reference.png'
    graph = build_workflow(*args, reference={'image': image_name, 'guidance': 4.5})
    (lora,) = [key for key, node in graph.items() if node['class_type'] == 'LoraLoader']
    shift = next(key for key, node in graph.items() if node['class_type'] == 'ModelSamplingAuraFlow')
    image = next(key for key, node in graph.items() if node['class_type'] == 'LoadImage')
    adapter = next(key for key, node in graph.items() if node['class_type'] == REFERENCE_NODE)
    first, redraw = [node['inputs'] for node in graph.values() if node['class_type'] == 'KSampler']
    detailer = next(
        node['inputs'] for node in graph.values() if node['class_type'] == 'AtelierXImpactDetailerPipeline'
    )

    assert graph[lora]['inputs']['strength_model'] == 0.75
    assert graph[shift]['inputs'] == {'model': [lora, 0], 'shift': 3.5}
    assert graph[image]['inputs'] == {'image': image_name}
    assert graph[adapter]['inputs'] == {
        'model': [shift, 0],
        'vae': ['3', 0],
        'image': [image, 0],
        'lora_name': REFERENCE_WEIGHT,
        'ref_guidance': 4.5,
        'correction': 'apg',
        'strength': 1.0,
        'ref_end': 1.0,
        'ref_megapixels': 1.0,
    }
    assert first['model'] == [adapter, 0]
    assert redraw['model'] == detailer['model'] == [shift, 0]
    assert first['seed'] == redraw['seed'] == detailer['seed'] == 42


def test_editor_exports_the_executed_reference_graph():
    settings = {**DEFAULTS, 'family': 'anima', 'width': 832, 'height': 1216}
    graph = build_workflow(
        settings, 'sent positive', 'negative', 86, reference={'image': 'ref/source.png', 'guidance': 1}
    )
    # Rebuilding from the other arguments would lose the reference and use different widgets.
    exported = build_ui_workflow(DEFAULTS, 'other positive', 'other negative', 21, graph=graph)
    nodes = {node['type']: node for node in exported['nodes'] if node['type'] != 'CLIPTextEncode'}
    assert nodes['LoadImage']['widgets_values'] == ['ref/source.png', 'image']
    assert nodes[REFERENCE_NODE]['widgets_values'] == [REFERENCE_WEIGHT, 1.0, 'apg', 1.0, 1.0, 1.0]
    assert nodes['KSampler']['widgets_values'][:2] == [86, 'fixed']
    assert nodes['EmptyLatentImage']['widgets_values'] == [832, 1216, 1]

    links = {link[0]: link for link in exported['links']}
    image_link = nodes[REFERENCE_NODE]['inputs'][2]['link']
    model_link = nodes['KSampler']['inputs'][0]['link']
    assert links[image_link] == [
        image_link,
        nodes['LoadImage']['id'],
        0,
        nodes[REFERENCE_NODE]['id'],
        2,
        'IMAGE',
    ]
    assert links[model_link] == [
        model_link,
        nodes[REFERENCE_NODE]['id'],
        0,
        nodes['KSampler']['id'],
        0,
        'MODEL',
    ]
    assert nodes['LoadImage']['outputs'][0]['links'] == [image_link]
    assert nodes[REFERENCE_NODE]['outputs'][0]['links'] == [model_link]


@pytest.mark.parametrize(
    ('patch', 'reference'),
    [
        ({'family': 'moss'}, {'image': 'ref.png', 'guidance': 4.5}),
        ({}, {'image': '', 'guidance': 4.5}),
        ({}, {'image': 'ref.png', 'guidance': float('nan')}),
        ({}, {'image': 'ref.png', 'guidance': 20.1}),
    ],
)
def test_rejects_invalid_reference_inputs(patch, reference):
    with pytest.raises(ValueError):
        build_workflow({**DEFAULTS, **patch}, 'positive', 'negative', 1, reference=reference)


@pytest.mark.parametrize(
    ('node_available', 'weights', 'expected'),
    [
        (True, [REFERENCE_WEIGHT], (True, True, True)),
        (True, [f'extras/{REFERENCE_WEIGHT}'], (False, True, False)),
        (True, [], (False, True, False)),
        (False, [REFERENCE_WEIGHT], (False, False, True)),
    ],
)
def test_readiness_uses_installed_weights_not_the_nodes_combo(monkeypatch, node_available, weights, expected):
    comfy = Comfy('http://example.invalid')
    node_spec = {'input': {'required': {'lora_name': [[REFERENCE_WEIGHT]]}}}
    responses = {
        f'/object_info/{REFERENCE_NODE}': {REFERENCE_NODE: node_spec} if node_available else {},
        '/models/loras': weights,
    }
    monkeypatch.setattr(comfy, 'request', responses.__getitem__)
    assert comfy.reference_status() == dict(
        zip(('ready', 'node_ready', 'weights_ready'), expected, strict=True)
    )
