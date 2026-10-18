"""External image generation records are read from file bytes without a workspace."""

import json
from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from atelierx.image.tools.inspect import MAX_IMAGE_BYTES, inspect_image


def picture(fmt='PNG', *, text=None, exif=None):
    output = BytesIO()
    image = Image.new('RGB', (48, 32), '#345678')
    options = {}
    if text:
        chunks = PngImagePlugin.PngInfo()
        for key, value in text.items():
            chunks.add_text(key, value)
        options['pnginfo'] = chunks
    if exif:
        tags = Image.Exif()
        for key, value in exif.items():
            tags[key] = value
        options['exif'] = tags
    image.save(output, format=fmt, **options)
    return output.getvalue()


def test_novelai_png_shows_recorded_prompts_and_raw_comment():
    comment = {
        'prompt': 'blue coat',
        'uc': 'blur',
        'seed': 123,
        'steps': 28,
        'scale': 6.5,
        'sampler': 'k_euler',
        'noise_schedule': 'karras',
    }
    raw = picture(
        text={
            'Software': 'NovelAI',
            'Source': 'nai-diffusion-4',
            'Description': 'blue coat',
            'Comment': json.dumps(comment),
        }
    )
    result = inspect_image(raw)
    assert result['status'] == 'parsed'
    assert result['generation']['generator'] == 'novelai'
    assert result['generation']['positive'] == 'blue coat'
    assert result['generation']['negative'] == 'blur'
    assert result['generation']['settings']['seed'] == 123
    assert result['raw']['text']['Comment'] == json.dumps(comment)


def test_comfy_png_reports_nodes_and_recorded_settings():
    graph = {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'base.safetensors'}},
        '2': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'red dress'}},
        '3': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'low quality'}},
        '4': {
            'class_type': 'LoraLoader',
            'inputs': {'lora_name': 'detail.safetensors', 'strength_model': 0.8},
        },
        '5': {
            'class_type': 'KSampler',
            'inputs': {
                'positive': ['2', 0],
                'negative': ['3', 0],
                'seed': 99,
                'steps': 24,
                'cfg': 5,
                'sampler_name': 'euler',
                'scheduler': 'normal',
            },
        },
        '6': {'class_type': 'UnknownCustomNode', 'inputs': {'thing': 'unparsed'}},
    }
    result = inspect_image(picture(text={'prompt': json.dumps(graph)}))
    generation = result['generation']
    assert result['status'] == 'parsed'
    assert generation['positive'] == 'red dress'
    assert generation['negative'] == 'low quality'
    assert generation['settings']['loras'][0]['name'] == 'detail.safetensors'
    assert generation['settings']['seed'] == 99
    assert generation['other_nodes'] == ['UnknownCustomNode']
    assert 'UnknownCustomNode' in result['raw']['text']['prompt']


def test_webp_comfy_exif_and_jpeg_exif_are_read():
    graph = {'1': {'class_type': 'KSampler', 'inputs': {'seed': 77, 'steps': 20}}}
    webp = inspect_image(picture('WEBP', exif={0x0110: 'prompt:' + json.dumps(graph)}))
    assert webp['generation']['generator'] == 'comfyui'
    assert webp['generation']['settings']['seed'] == 77
    assert webp['raw']['exif']['Model'].startswith('prompt:')
    jpeg = inspect_image(picture('JPEG', exif={0x9286: 'sunset\nNegative prompt: rain\nSteps: 21, Seed: 8'}))
    assert jpeg['generation']['positive'] == 'sunset'
    assert jpeg['raw']['exif']['UserComment'].startswith('sunset')


def test_missing_partial_and_damaged_inputs():
    assert inspect_image(picture())['status'] == 'none'
    partial = inspect_image(picture(text={'prompt': '{broken'}))
    assert partial['status'] == 'partial'
    assert partial['generation']['positive'] == ''
    malformed_nai = inspect_image(picture(text={'Software': 'NovelAI', 'Comment': '[]'}))
    assert malformed_nai['status'] == 'partial'
    assert malformed_nai['raw']['text']['Comment'] == '[]'
    for bad_record in (
        {'atelierx': '[]'},
        {'prompt': json.dumps({'1': ['invalid node']})},
        {'prompt': json.dumps({'1': {'class_type': 'KSampler', 'inputs': 'invalid'}})},
    ):
        result = inspect_image(picture(text=bad_record))
        assert result['status'] == 'partial'
        assert result['generation']['positive'] == ''
        assert result['raw']['text'] == bad_record
    complete = picture()
    for raw in (b'', b'broken', complete[: len(complete) // 2], b'x' * (MAX_IMAGE_BYTES + 1)):
        with pytest.raises(ValueError):
            inspect_image(raw)
