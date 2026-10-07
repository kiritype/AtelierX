"""My models (#161): the image server's files with their family, source and Civitai information."""

import hashlib
import json

from atelierx.image import model_info
from atelierx.image.model_info import ModelLibrary
from atelierx.image.models import ModelProfiles

CATALOG = {
    'connected': True,
    'model_entries': {
        'anima\\base.safetensors': {'loader': 'UNETLoader', 'filename': 'anima\\base.safetensors'},
        'checkpoint::sdxl\\mix.safetensors': {
            'loader': 'CheckpointLoaderSimple',
            'filename': 'sdxl\\mix.safetensors',
        },
    },
    'loras': ['ink.safetensors', 'atelierx\\W002_C001_R001-e10.safetensors', 'gone.safetensors'],
    'text_encoders': [],
    'vaes': [],
    'upscale_models': [],
}


def _setup(paths, tmp_path):
    loras, unet = tmp_path / 'comfy' / 'loras', tmp_path / 'comfy' / 'diffusion_models'
    (loras / 'atelierx').mkdir(parents=True)
    (unet / 'anima').mkdir(parents=True)
    (unet / 'anima' / 'base.safetensors').write_bytes(b'model')
    ckpt = tmp_path / 'comfy' / 'checkpoints'
    (ckpt / 'sdxl').mkdir(parents=True)
    (ckpt / 'sdxl' / 'mix.safetensors').write_bytes(b'checkpoint')
    (loras / 'ink.safetensors').write_bytes(b'ink lora')
    (loras / 'atelierx' / 'W002_C001_R001-e10.safetensors').write_bytes(b'trained')
    cm = {
        'ModelId': 7,
        'VersionId': 70,
        'ModelName': 'Ink',
        'VersionName': 'v1',
        'BaseModel': 'Anima',
        'TrainedWords': ['@ink'],
        'Hashes': {'SHA256': 'AB' * 32},
    }
    (loras / 'ink.cm-info.json').write_text(json.dumps(cm), encoding='utf-8')
    (loras / 'ink.preview.jpeg').write_bytes(b'jpeg')
    folders = {'loras': [str(loras)], 'diffusion_models': [str(unet)], 'checkpoints': [str(ckpt)]}
    profiles = ModelProfiles(paths)
    library = ModelLibrary(paths, profiles, lambda: folders)
    profiles.looked_up = library.base_model
    profiles.find = library.locate_for_family
    return library


def test_items_say_where_each_file_came_from(paths, tmp_path):
    library = _setup(paths, tmp_path)
    items = {i['name']: i for i in library.items(CATALOG)}
    ink = items['ink.safetensors']
    assert (
        ink['source'] == 'civitai'
        and ink['info']['trained_words'] == ['@ink']
        and ink['info']['from'] == 'cm-info'
    )
    assert ink['info']['url'] == 'https://civitai.com/models/7?modelVersionId=70'
    assert (
        ink['preview'] == '.preview.jpeg'
        and library.preview_file('lora', 'ink.safetensors').name == 'ink.preview.jpeg'
    )
    assert items['atelierx\\W002_C001_R001-e10.safetensors']['source'] == 'trained'
    # The family comes from the folder as before.
    assert (
        items['anima\\base.safetensors']['family'] == 'anima'
        and items['anima\\base.safetensors']['family_by'] == 'folder'
    )
    assert items['gone.safetensors']['path'] is None and items['gone.safetensors']['source'] == 'unknown'


def test_a_lookup_hashes_once_asks_civitai_and_feeds_the_family(paths, tmp_path, monkeypatch):
    library = _setup(paths, tmp_path)
    digest = hashlib.sha256(b'ink lora').hexdigest()
    asked = []

    def fake_get(url):
        asked.append(url)
        if url.endswith(f'/by-hash/{digest}'):
            return {
                'id': 71,
                'modelId': 8,
                'name': 'v2',
                'baseModel': 'Illustrious',
                'trainedWords': ['ink style'],
                'model': {'name': 'Ink style', 'nsfw': False},
            }
        if url.endswith('/models/8'):
            return {
                'name': 'Ink style',
                'allowCommercialUse': ['Image'],
                'allowDerivatives': True,
                'creator': {'username': 'someone'},
            }
        raise AssertionError(url)

    monkeypatch.setattr(library, '_get', fake_get)
    item = library.lookup('lora', 'ink.safetensors')
    # What the app looked up wins over the cm-info file, and is kept by hash.
    assert item['info']['from'] == 'lookup' and item['info']['trained_words'] == ['ink style']
    assert item['info']['license'] == {'allowCommercialUse': ['Image'], 'allowDerivatives': True}
    assert item['family'] == 'sdxl' and item['family_by'] == 'civitai' and item['hashed'] is True
    stored = json.loads((paths.data / 'image' / 'model-info.json').read_text(encoding='utf-8'))
    assert stored['info'][digest]['model_id'] == 8
    # The hash is not computed again for the same file.
    monkeypatch.setattr(
        model_info.hashlib, 'sha256', lambda: (_ for _ in ()).throw(AssertionError('hashed again'))
    )
    library.lookup('lora', 'ink.safetensors')
    assert len(asked) == 4


def test_a_file_civitai_does_not_know_is_remembered_as_unknown(paths, tmp_path, monkeypatch):
    library = _setup(paths, tmp_path)
    monkeypatch.setattr(library, '_get', lambda url: None)
    item = library.lookup('diffusion_model', 'anima\\base.safetensors')
    assert item['info']['not_found'] is True and item['source'] == 'unknown'


def test_the_models_api_lists_and_looks_up(unlocked, tmp_path, monkeypatch):
    c = unlocked
    runtime = c.app.state.app.image
    library = _setup(runtime.paths, tmp_path)
    runtime.model_library = library
    runtime.comfy.catalog = lambda: CATALOG
    listed = c.get('/api/image/models/list').json()['items']
    assert {i['name'] for i in listed} >= {
        'anima\\base.safetensors',
        'ink.safetensors',
        'atelierx\\W002_C001_R001-e10.safetensors',
        'gone.safetensors',
    }
    preview = c.get('/api/image/models/preview', params={'kind': 'lora', 'name': 'ink.safetensors'})
    assert preview.status_code == 200 and preview.content == b'jpeg'
    assert (
        c.get('/api/image/models/preview', params={'kind': 'lora', 'name': 'gone.safetensors'}).status_code
        == 404
    )
    monkeypatch.setattr(library, '_get', lambda url: None)
    found = c.post('/api/image/models/lookup', json={'kind': 'lora', 'name': 'ink.safetensors'}).json()
    assert found['info']['not_found'] is True


def test_checkpoints_are_found_without_their_catalog_prefix(paths, tmp_path):
    library = _setup(paths, tmp_path)
    item = {i['name']: i for i in library.items(CATALOG)}[r'checkpoint::sdxl\mix.safetensors']
    assert item['kind'] == 'checkpoint' and item['path'] and item['file'] == 'mix.safetensors'
    assert item['family'] == 'sdxl'
