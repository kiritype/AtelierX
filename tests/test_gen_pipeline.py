"""Generation pipeline (#168): shift, LoRAs on and off, upscale and redraw, detailer parts, as one graph."""

import pytest

from atelierx.image.generation import GenerationMixin
from atelierx.image.tools.postprocess import detail_graph
from atelierx.image.workflow import build_ui_workflow, build_workflow, pipeline_stages, validate_settings

CATALOG = {
    'models': ['m.safetensors'],
    'text_encoders': ['qwen.safetensors'],
    'vaes': ['vae.safetensors'],
    'loras': ['a.safetensors', 'b.safetensors'],
    'samplers': ['er_sde'],
    'schedulers': ['simple'],
    'clip_types': ['stable_diffusion'],
    'model_entries': {},
    'defaults': {},
    'upscale_models': ['2x-AnimeSharpV4.pth', '4x-UltraSharp.pth'],
    'nodes': {'upscale': True, 'detailer': True},
}


def _settings(**extra):
    return validate_settings({'width': 1024, 'height': 1536, **extra}, CATALOG)


def _classes(graph):
    return [
        n['class_type']
        for k, n in sorted(
            graph.items(), key=lambda kv: (kv[0] == 'output', int(kv[0]) if kv[0].isdigit() else 0)
        )
    ]


def test_without_the_new_steps_the_graph_is_as_before():
    plain = _settings()
    assert plain['shift'] is None and plain['upscale'] is None and plain['detailer'] is None
    assert pipeline_stages(plain) == ['generate']
    assert _classes(build_workflow(plain, 'p', 'n', 1)) == [
        'UNETLoader', 'CLIPLoader', 'VAELoader', 'CLIPTextEncode', 'CLIPTextEncode', 'EmptyLatentImage',
        'KSampler', 'VAEDecode', 'PreviewImage',
    ]  # fmt: skip


def test_settings_are_checked_and_filled():
    s = _settings(
        shift=4,
        loras=[
            {'name': 'a.safetensors'},
            {'name': 'b.safetensors', 'strength_model': -0.25, 'enabled': False},
        ],
        upscale={'denoise': 0.25},
        detailer={'stages': {'face': 0.35, 'hand': 0.4}},
    )
    assert s['shift'] == 4
    assert 'enabled' not in s['loras'][0] and s['loras'][1]['enabled'] is False
    assert s['upscale'] == {'model': '2x-AnimeSharpV4.pth', 'scale': 1.5, 'steps': 12, 'denoise': 0.25}
    assert s['detailer'] == {'stages': {'face': 0.35, 'hand': 0.4}, 'steps': 20}
    # Nothing chosen is off; SDXL has no shift.
    assert _settings(detailer={'stages': {}})['detailer'] is None
    for bad in ({'shift': 50}, {'upscale': {'scale': 9}}, {'upscale': {'model': 'none.pth'}},
                {'detailer': {'stages': {'face': 2}}}):  # fmt: skip
        with pytest.raises(ValueError):
            _settings(**bad)
    missing = {**CATALOG, 'nodes': {'upscale': False, 'detailer': False}}
    with pytest.raises(ValueError) as raised:
        validate_settings({'upscale': {}}, missing)
    assert raised.value.args[0].key == 'server.workflow.upscale_nodes'


def test_the_graph_runs_loras_shift_generation_upscale_and_detailer_in_order():
    s = _settings(
        shift=4,
        loras=[{'name': 'a.safetensors'}, {'name': 'b.safetensors', 'enabled': False}],
        upscale={'scale': 1.5, 'steps': 12, 'denoise': 0.3, 'cfg': 4},
        detailer={'stages': {'hand': 0.4, 'face': 0.35}, 'steps': 18},
    )
    graph = build_workflow(s, 'p', 'n', 7)
    nodes = {k: n for k, n in graph.items()}
    loras = [n for n in nodes.values() if n['class_type'] == 'LoraLoader']
    assert [n['inputs']['lora_name'] for n in loras] == ['a.safetensors']
    shift = next(k for k, n in nodes.items() if n['class_type'] == 'ModelSamplingAuraFlow')
    samplers = [n for n in nodes.values() if n['class_type'] == 'KSampler']
    assert all(n['inputs']['model'] == [shift, 0] for n in samplers)
    first, redraw = samplers
    assert first['inputs']['denoise'] == 1.0 and redraw['inputs']['denoise'] == 0.3
    assert redraw['inputs']['cfg'] == 4 and redraw['inputs']['steps'] == 12 and redraw['inputs']['seed'] == 7

    # Follow the image back from the output: hand ← face ← redraw decode ← encode ← upscale ← first decode.
    chain, ref = [], graph['output']['inputs']['images']
    while ref:
        node = nodes[ref[0]]
        chain.append(node['class_type'])
        inputs = node['inputs']
        ref = (
            inputs.get('image') or inputs.get('samples') or inputs.get('pixels') or inputs.get('latent_image')
        )
        if node['class_type'] == 'EmptyLatentImage':
            break
    assert chain[:6] == [
        'AtelierXImpactDetailerPipeline', 'AtelierXImpactDetailerPipeline', 'VAEDecode', 'KSampler', 'VAEEncode',
        'AtelierXUpscale',
    ]  # fmt: skip
    details = [nodes[k] for k in sorted(nodes, key=lambda k: int(k) if k.isdigit() else 1e9)
               if nodes[k]['class_type'] == 'AtelierXImpactDetailerPipeline']  # fmt: skip
    assert [
        (d['inputs']['face_enabled'], d['inputs']['hand_enabled'], d['inputs']['denoise']) for d in details
    ] == [
        (True, False, 0.35),
        (False, True, 0.4),
    ]
    # The editable ComfyUI workflow can be made from it too.
    assert build_ui_workflow(s, 'p', 'n', 7)['nodes']
    assert pipeline_stages(s) == ['generate', 'upscale', 'detailer']
    assert (
        GenerationMixin._generating({'snapshot': {'settings': s}}).key
        == 'server.worker.generating_upscale_detailer'
    )


def test_tools_redraw_on_the_first_pass_of_a_record_made_with_the_new_steps():
    s = _settings(upscale={}, detailer={'stages': {'face': 0.3}})
    source = {'settings': s, 'positive': 'p', 'negative': 'n', 'seed': 3}
    options = {'face': True, 'eye': False, 'mouth': False, 'hand': True, 'steps': 20, 'denoise': 0.4}
    graph = detail_graph('img.png', options, source, 'AtelierX')
    kinds = [n['class_type'] for n in graph.values()]
    assert kinds.count('AtelierXImpactDetailerPipeline') == 1 and 'AtelierXUpscale' not in kinds
    assert graph['detail']['inputs']['hand_enabled'] is True
