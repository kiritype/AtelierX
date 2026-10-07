"""Custom nodes in the generation graph (#178): model patches, node-pack sampler names, beta57, and missing nodes."""

import pytest

from atelierx.image import extensions
from atelierx.image.workflow import build_ui_workflow, build_workflow, validate_settings

OBJECT_INFO = {
    'SkimmedCFG_LinInterp_CFG_PreCFG': {
        'display_name': 'Skimmed CFG - linear interpolation',
        'python_module': 'custom_nodes.Skimmed_CFG',
        'input': {
            'required': {
                'model': ['MODEL'],
                'skimming_cfg': ['FLOAT', {'default': 5.0, 'min': 0.0, 'max': 10.0, 'step': 0.1}],
            }
        },
        'output': ['MODEL'],
    },
    'Switchy': {
        'input': {
            'required': {
                'model': ['MODEL'],
                'mode': [['soft', 'hard']],
                'enabled': ['BOOLEAN', {'default': True}],
                'steps': ['INT', {'default': 3, 'min': 1, 'max': 9}],
            },
            'optional': {'note': ['STRING', {}], 'mask': ['MASK']},
        },
        'output': ['MODEL'],
    },
    # Not patches: a second connection, or more than a model out.
    'NeedsClip': {'input': {'required': {'model': ['MODEL'], 'clip': ['CLIP']}}, 'output': ['MODEL']},
    'TwoOut': {'input': {'required': {'model': ['MODEL']}}, 'output': ['MODEL', 'CLIP']},
    'KSampler': {'input': {'required': {'model': ['MODEL']}}, 'output': ['LATENT']},
}

CATALOG = {
    'models': ['m.safetensors'],
    'text_encoders': ['qwen.safetensors'],
    'vaes': ['vae.safetensors'],
    'loras': [],
    'samplers': ['er_sde', 'euler'],
    'schedulers': ['simple', 'beta'],
    'clip_types': ['stable_diffusion'],
    'model_entries': {},
    'defaults': {},
    'upscale_models': ['2x.pth'],
    'nodes': {'upscale': True, 'detailer': True},
    'patch_nodes': extensions.patch_nodes(OBJECT_INFO),
}


def _settings(**extra):
    return validate_settings({'width': 1024, 'height': 1024, **extra}, CATALOG)


def test_model_patches_are_found_in_object_info():
    nodes = CATALOG['patch_nodes']
    assert set(nodes) == {'SkimmedCFG_LinInterp_CFG_PreCFG', 'Switchy'}
    skim = nodes['SkimmedCFG_LinInterp_CFG_PreCFG']
    assert skim['label'] == 'Skimmed CFG - linear interpolation'
    assert skim['inputs']['skimming_cfg'] == {
        'type': 'FLOAT',
        'default': 5.0,
        'min': 0.0,
        'max': 10.0,
        'step': 0.1,
    }
    switchy = nodes['Switchy']['inputs']
    assert switchy['mode'] == {'type': 'COMBO', 'options': ['soft', 'hard'], 'default': 'soft'}
    # Optional plain inputs are offered; optional connections are not.
    assert switchy['note']['optional'] is True and 'mask' not in switchy


def test_patches_go_after_shift_in_order_and_off_ones_stay_out():
    s = _settings(
        shift=3,
        patches=[
            {'node': 'SkimmedCFG_LinInterp_CFG_PreCFG', 'inputs': {'skimming_cfg': 4}},
            {'node': 'Switchy', 'inputs': {'mode': 'hard'}, 'enabled': False},
            {'node': 'Switchy', 'inputs': {'steps': 2}},
        ],
    )
    # Values are checked, and required inputs left out take the node's default.
    assert s['patches'][0] == {'node': 'SkimmedCFG_LinInterp_CFG_PreCFG', 'inputs': {'skimming_cfg': 4}}
    assert s['patches'][2]['inputs'] == {'mode': 'soft', 'enabled': True, 'steps': 2}
    graph = build_workflow(s, 'p', 'n', 7)
    by_class = {}
    for key, node in graph.items():
        by_class.setdefault(node['class_type'], []).append((key, node))
    ((shift_id, _),) = by_class['ModelSamplingAuraFlow']
    ((skim_id, skim),) = by_class['SkimmedCFG_LinInterp_CFG_PreCFG']
    ((switch_id, switch),) = by_class['Switchy']
    assert skim['inputs'] == {'skimming_cfg': 4, 'model': [shift_id, 0]}
    assert switch['inputs']['model'] == [skim_id, 0]
    ((_, sampler),) = by_class['KSampler']
    assert sampler['inputs']['model'] == [switch_id, 0]
    # The editable workflow carries the patch with its settings as widgets.
    ui = build_ui_workflow(s, 'p', 'n', 7)
    node = next(n for n in ui['nodes'] if n['type'] == 'SkimmedCFG_LinInterp_CFG_PreCFG')
    assert node['widgets_values'] == [4] and node['inputs'][0]['link'] is not None


@pytest.mark.parametrize(
    ('patch', 'error'),
    [
        ({'node': 'Switchy', 'inputs': {'steps': 12}}, 'between'),
        ({'node': 'Switchy', 'inputs': {'mode': 'other'}}, 'choices'),
        ({'node': 'Switchy', 'inputs': {'enabled': 1}}, 'true or false'),
        ({'node': 'Switchy', 'inputs': {'model': 1}}, 'unknown'),
        ({'node': ''}, 'node name'),
    ],
)
def test_bad_patch_values_are_refused(patch, error):
    with pytest.raises(ValueError, match=error):
        _settings(patches=[patch])


def test_beta57_is_drawn_with_built_in_nodes_when_the_pack_is_absent():
    s = _settings(
        scheduler='beta57', upscale={'steps': 10, 'denoise': 0.5}, detailer={'stages': {'face': 0.3}}
    )
    assert s['sigmas'] == {'kind': 'beta', 'alpha': 0.5, 'beta': 0.7}
    graph = build_workflow(s, 'p', 'n', 9)
    classes = [n['class_type'] for n in graph.values()]
    assert 'KSampler' not in classes and classes.count('SamplerCustomAdvanced') == 2
    schedules = [n for n in graph.values() if n['class_type'] == 'BetaSamplingScheduler']
    assert [(n['inputs']['steps'], n['inputs']['alpha'], n['inputs']['beta']) for n in schedules] == [
        (32, 0.5, 0.7),
        (20, 0.5, 0.7),
    ]
    # The redraw runs the last 10 of 20 steps, like KSampler's denoise 0.5.
    (split,) = [n for n in graph.values() if n['class_type'] == 'SplitSigmas']
    assert split['inputs']['step'] == 10
    detailer = next(n for n in graph.values() if n['class_type'] == 'AtelierXImpactDetailerPipeline')
    assert detailer['inputs']['scheduler'] == 'beta'
    ui = build_ui_workflow(s, 'p', 'n', 9)
    assert {'SamplerCustomAdvanced', 'BetaSamplingScheduler', 'CFGGuider', 'RandomNoise'} <= {
        n['type'] for n in ui['nodes']
    }
    # With the pack, ComfyUI lists it and KSampler takes it as it is.
    listed = validate_settings({'scheduler': 'beta57'}, {**CATALOG, 'schedulers': ['simple', 'beta57']})
    assert 'sigmas' not in listed
    assert next(n for n in build_workflow(listed, 'p', 'n', 1).values() if n['class_type'] == 'KSampler')


def test_missing_nodes_stop_the_request_or_are_left_out():
    wanted = {
        'sampler': 'res_3m',
        'scheduler': 'bong_tangent',
        'fallback': {'sampler': 'euler', 'scheduler': 'beta'},
        'patches': [
            {'node': 'DCWModelPatch', 'inputs': {'lambda_l': 0.1}},
            {'node': 'Switchy', 'inputs': {}},
        ],
    }
    with pytest.raises(extensions.MissingNodes) as raised:
        _settings(**wanted)
    assert raised.value.missing == [
        {'kind': 'sampler', 'name': 'res_3m'},
        {'kind': 'scheduler', 'name': 'bong_tangent'},
        {'kind': 'patch', 'name': 'DCWModelPatch'},
    ]
    assert raised.value.args[0].key == 'server.workflow.missing_nodes'
    s = _settings(**wanted, missing='skip')
    assert (s['sampler'], s['scheduler']) == ('euler', 'beta')
    assert [p['node'] for p in s['patches']] == ['Switchy']
    assert s['skipped'] == ['res_3m', 'bong_tangent', 'DCWModelPatch']
    # Without a fallback the defaults are used.
    s = _settings(sampler='res_3m', missing='skip')
    assert s['sampler'] == 'er_sde'
    with pytest.raises(ValueError, match='fallback.sampler'):
        _settings(fallback={'sampler': 'res_3m'})


def test_known_packs_say_where_a_name_comes_from():
    packs = extensions.known_packs(
        {
            'nodes': [{'id': 'skim', 'repo': 'r', 'license': 'Apache-2.0', 'provides': ['Skim']}],
            'known': [{'id': 'res4lyf', 'license': 'own', 'provides': ['res_3m']}],
        }
    )
    assert packs['Skim']['installable'] is True and packs['res_3m'] == {
        'id': 'res4lyf',
        'repo': None,
        'license': 'own',
        'installable': False,
        'note': None,
    }


def test_queued_work_leaves_out_what_comfyui_no_longer_has():
    from atelierx.image.services import ComfyService

    class Comfy:
        def catalog(self):
            return {**CATALOG, 'connected': True}

    class Runtime:
        comfy = Comfy()

    settings = _settings(patches=[{'node': 'Switchy', 'inputs': {}}], fallback={'sampler': 'euler'})
    settings['patches'].append({'node': 'Gone', 'inputs': {}})
    job = {'seed': 3, 'snapshot': {'settings': settings, 'positive': 'p', 'negative': 'n'}}
    graph = ComfyService(Runtime()).graph(job)
    classes = {n['class_type'] for n in graph.values()}
    assert 'Switchy' in classes and 'Gone' not in classes
    assert job['snapshot']['settings']['skipped'] == ['Gone']


def test_the_generate_screen_can_ask_what_is_missing(unlocked):
    client = unlocked
    client.app.state.app.image.comfy.catalog = lambda: {**CATALOG, 'connected': True}
    body = {'settings': {'sampler': 'res_3m', 'patches': [{'node': 'Switchy', 'inputs': {}}]}}
    response = client.post('/api/image/generate/check-nodes', json=body)
    assert response.status_code == 200
    (item,) = response.json()['missing']
    assert (
        item['name'] == 'res_3m' and item['pack']['id'] == 'res4lyf' and item['pack']['installable'] is False
    )
    body['settings']['sampler'] = 'euler'
    assert client.post('/api/image/generate/check-nodes', json=body).json() == {'missing': []}
