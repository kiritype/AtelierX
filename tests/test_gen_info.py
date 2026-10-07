"""Generation table of an image (#169): the tool that made it, its settings, and what this PC has."""

import json

from atelierx.image.tools import gen_info

FORGE = (
    'masterpiece, best quality, 1girl, <lora:ink_style:0.6>\n'
    'Negative prompt: worst quality, artist name\n'
    'Steps: 30, Sampler: Euler a, Schedule type: SGM Uniform, CFG scale: 4, Shift: 3, Seed: 42, Size: 960x1536, '
    'Model: Sample Mix _v2.0z, Model hash: abcdef0123, Module 1: qwen_image_vae, Module 2: anima_text, '
    'Denoising strength: 0.3, Hires upscale: 1.4, Hires steps: 10, Hires upscaler: 4x-UltraSharp, Version: neo-2.28'
)
GRAPH = {
    '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'anima\\sample_v23.safetensors'}},
    '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'qwen_3_06b_base.safetensors'}},
    '3': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['1', 0], 'shift': 4}},
    '4': {'class_type': 'CFGZeroStar', 'inputs': {'model': ['3', 0]}},
    '5': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'er_sde'}},
    '6': {'class_type': 'BasicScheduler', 'inputs': {'scheduler': 'beta1_1', 'steps': 20}},
    '7': {'class_type': 'CFGGuider', 'inputs': {'cfg': 4.0}},
    '8': {
        'class_type': 'SamplerCustomAdvanced',
        'inputs': {'sampler': ['5', 0], 'sigmas': ['6', 0], 'guider': ['7', 0]},
    },
}
COMFY_TEXT = (
    'score_9, 1girl\nNegative prompt: lowres\n'
    'Steps: 20, Sampler: er_sde_beta1_1, CFG scale: 4.0, Seed: 0, Size: 1248x1824, Model: sample_v23, Version: ComfyUI, '
    'Civitai resources: [{"modelName":"Sample Mix","versionName":"v2.3","air":"urn:air:anima:checkpoint:civitai:1@111"},'
    '{"modelName":"Turbo LoRA","versionName":"v0.2","weight":0.7,"air":"urn:air:anima:lora:civitai:2@222"}]'
)
CATALOG = {
    'connected': True,
    'models': ['anima\\sample_v23.safetensors', 'checkpoint::anima\\sampleMix_20BETA11.safetensors'],
    'text_encoders': ['qwen_3_06b_base.safetensors', 'other_anima_base_txt.safetensors'],
    'loras': ['anima\\ink_style.safetensors', 'anima\\turbo-lora-v0.2.safetensors'],
    'samplers': ['er_sde', 'euler_ancestral'],
    'schedulers': ['simple', 'beta', 'sgm_uniform'],
    'upscale_models': ['4x-UltraSharp.safetensors'],
}


def test_a_webui_record_reads_into_settings_and_names_its_version():
    g = gen_info.analyze({'parameters': FORGE}, {}, None, (1344, 2176), CATALOG['samplers'])
    assert (g['generator'], g['format']) == ('webui', 'a1111')
    assert 'Forge Neo' in g['evidence'][0]
    s = g['settings']
    assert (s['sampler'], s['scheduler'], s['steps'], s['cfg'], s['shift'], s['seed']) == (
        'euler_ancestral',
        'sgm_uniform',
        30,
        4,
        3,
        42,
    )
    assert (s['width'], s['height']) == (960, 1536)
    assert s['model'] == {'name': 'Sample Mix _v2.0z', 'hash': 'abcdef0123'}
    assert s['text_encoder'] == {'name': 'anima_text'}
    assert s['loras'] == [{'name': 'ink_style', 'strength': 0.6}]
    assert s['upscale'] == {'scale': 1.4, 'steps': 10, 'denoise': 0.3, 'model': '4x-UltraSharp', 'cfg': None}
    assert g['positive'].startswith('masterpiece') and g['negative'] == 'worst quality, artist name'


def test_a_comfyui_image_reads_the_saver_text_first_and_the_graph_for_the_rest():
    text = {'parameters': COMFY_TEXT, 'prompt': json.dumps(GRAPH), 'workflow': '{}'}
    g = gen_info.analyze(text, {}, None, (1248, 1824), CATALOG['samplers'])
    assert g['generator'] == 'comfyui' and 'Version: ComfyUI' in g['evidence']
    s = g['settings']
    # "er_sde_beta1_1" is split at the longest known sampler.
    assert (s['sampler'], s['scheduler'], s['steps'], s['cfg'], s['shift']) == ('er_sde', 'beta1_1', 20, 4, 4)
    assert s['model']['version_id'] == '111' and s['loras'] == [
        {'name': 'Turbo LoRA', 'version': 'v0.2', 'version_id': '222', 'strength': 0.7}
    ]
    assert 'CFGZeroStar' in g['other_nodes']
    gen_info.enrich(g, CATALOG, {})
    assert g['notes'] == [{'kind': 'scheduler', 'name': 'beta1_1', 'nearest': 'beta'}]
    # Same file name: found. A different display name: a similar file is only offered.
    assert s['text_encoder']['found'] == 'qwen_3_06b_base.safetensors'
    assert s['model'] == {**s['model'], 'found': 'anima\\sample_v23.safetensors', 'by': 'name'}
    assert s['loras'][0]['found'] is None and s['loras'][0]['similar'] == 'anima\\turbo-lora-v0.2.safetensors'


def test_a_graph_kept_as_json_under_parameters_and_node_pack_settings():
    graph = {
        '10': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'SampleMixV40.safetensors'}},
        '20': {
            'class_type': 'KSampler Config (rgthree)',
            'inputs': {'steps_total': 30, 'cfg': 5.0, 'sampler_name': 'er_sde', 'scheduler': 'simple'},
        },
        '30': {'class_type': 'Seed (rgthree)', 'inputs': {'seed': 7}},
        '40': {
            'class_type': 'Power Lora Loader (Aca)',
            'inputs': {
                'lora_1': {'on': True, 'lora': 'ink_style.safetensors', 'strength': 0.5},
                'lora_2': {'on': False, 'lora': 'off.safetensors', 'strength': 1},
            },
        },
        '50': {
            'class_type': 'PromptStudio',
            'inputs': {
                'advanced_fields': json.dumps(
                    [
                        {'pane': 'positive', 'text': 'masterpiece, year 2025', 'enabled': True},
                        {'pane': 'positive', 'text': '(@ink artist:0.5)', 'enabled': True},
                        {'pane': 'positive', 'text': 'unused', 'enabled': False},
                        {'pane': 'negative', 'text': 'lowres', 'enabled': True},
                    ]
                )
            },
        },
    }
    text = {'parameters': json.dumps({'prompt': json.dumps(graph), 'workflow': {'nodes': []}})}
    g = gen_info.analyze(text, {}, None, (1280, 1920))
    assert g['generator'] == 'comfyui' and any('JSON' in e for e in g['evidence'])
    assert g['positive'] == 'masterpiece, year 2025, (@ink artist:0.5)' and g['negative'] == 'lowres'
    s = g['settings']
    assert (s['sampler'], s['scheduler'], s['steps'], s['cfg'], s['seed']) == ('er_sde', 'simple', 30, 5.0, 7)
    assert s['loras'] == [{'name': 'ink_style.safetensors', 'strength': 0.5}]
    assert (s['width'], s['height']) == (1280, 1920)


def test_novelai_and_unknown_images():
    comment = {
        'prompt': 'artist:ink, 1girl',
        'uc': 'lowres',
        'steps': 28,
        'scale': 5,
        'seed': 9,
        'sampler': 'k_euler_ancestral',
        'noise_schedule': 'karras',
        'width': 832,
        'height': 1216,
    }
    g = gen_info.analyze(
        {'Software': 'NovelAI', 'Source': 'NovelAI Diffusion V4.5', 'Comment': json.dumps(comment)},
        {},
        None,
        (832, 1216),
    )
    assert g['generator'] == 'novelai' and g['positive'] == 'artist:ink, 1girl' and g['negative'] == 'lowres'
    assert g['settings']['sampler'] == 'k_euler_ancestral' and g['settings']['model'] == {
        'name': 'NovelAI Diffusion V4.5'
    }
    # NovelAI names are not checked against the local image server.
    assert gen_info.enrich(g, CATALOG, {})['notes'] == []
    blank = gen_info.analyze({}, {}, None, (1024, 768))
    assert blank['generator'] == 'unknown' and blank['settings'] == {'width': 1024, 'height': 768}


def test_names_match_by_file_name_hash_or_version_and_similar_names_are_only_offered():
    index = [
        {
            'name': 'anima\\sampleMix_20BETA11.safetensors',
            'sha256': 'abcdef0123' + '0' * 54,
            'version_id': '5',
        }
    ]
    by_hash = gen_info.match(
        {'name': 'Sample Mix display name', 'hash': 'abcdef0123'}, CATALOG['models'], index
    )
    assert by_hash == {
        'found': 'checkpoint::anima\\sampleMix_20BETA11.safetensors',
        'by': 'hash',
        'similar': None,
    }
    by_version = gen_info.match({'name': 'x', 'version_id': '5'}, CATALOG['models'], index)
    assert by_version['by'] == 'version'
    # Case changes and digits split words; common words like "anima" or "txt" do not count.
    guess = gen_info.match({'name': 'SampleMix 2.0B BETA 1.0z'}, CATALOG['models'])
    assert guess == {
        'found': None,
        'by': None,
        'similar': 'checkpoint::anima\\sampleMix_20BETA11.safetensors',
    }
    assert gen_info.match({'name': 'anima_base_txt'}, CATALOG['text_encoders'])['similar'] is None
