"""Style presets shared as a ZIP (#169): presets and previews out, a look before anything comes in, a choice per preset."""

import io
import json
import zipfile

from PIL import Image


def _preset(c, ident, **extra):
    body = {
        'name': ident,
        'service': 'comfyui',
        'family': 'anima',
        'settings': {
            'model': 'anima\\m.safetensors',
            'loras': [{'name': 'anima\\ink.safetensors', 'strength_model': 0.5}],
        },
        'artist': {'positive': f'@{ident}', 'negative': ''},
        **extra,
    }
    assert c.put(f'/api/image/presets/{ident}', json=body).status_code == 200


def _with_preview(paths, ident):
    folder = paths.data / 'image' / 'presets'
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (10, 20, 30)).save(buffer, format='WEBP')
    (folder / f'{ident}.webp').write_bytes(buffer.getvalue())
    doc = json.loads((folder / f'{ident}.json').read_text(encoding='utf-8'))
    doc['preview'] = {'seed': 1234567, 'hash': 'abc', 'created_at': 'now'}
    (folder / f'{ident}.json').write_text(json.dumps(doc), encoding='utf-8')


def test_export_packs_the_chosen_presets_their_previews_and_what_they_need(unlocked, paths):
    c = unlocked
    _preset(c, 'ink')
    _preset(c, 'water', service='novelai', settings={'model': 'nai-diffusion-4-5-full'})
    _with_preview(paths, 'ink')
    response = c.get('/api/image/presets/export', params={'ids': 'ink'})
    assert response.status_code == 200 and 'attachment' in response.headers['content-disposition']
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == ['atelierx-presets.json', 'presets/ink.json', 'presets/ink.webp']
    manifest = json.loads(archive.read('atelierx-presets.json'))
    assert manifest['kind'] == 'atelierx-style-presets'
    (entry,) = manifest['presets']
    assert entry['preview'] is True
    assert [(r['kind'], r['name']) for r in entry['resources']] == [
        ('model', 'anima\\m.safetensors'),
        ('lora', 'anima\\ink.safetensors'),
    ]
    # No ids: everything.
    every = zipfile.ZipFile(io.BytesIO(c.get('/api/image/presets/export').content))
    assert 'presets/water.json' in every.namelist()


def test_import_shows_each_preset_first_then_applies_the_choices(unlocked, paths):
    c = unlocked
    _preset(c, 'ink')
    _preset(c, 'water')
    _with_preview(paths, 'ink')
    package = c.get('/api/image/presets/export').content
    # Change what is here, then bring the package back.
    _preset(c, 'ink', name='changed here')
    c.delete('/api/image/presets/water')
    c.app.state.app.image.comfy.catalog = lambda: {
        'connected': True,
        'models': ['anima\\m.safetensors'],
        'loras': [],
    }
    seen = c.post('/api/image/presets/import/preview', content=package).json()
    items = {i['id']: i for i in seen['items']}
    assert items['ink']['exists'] is True and items['water']['exists'] is False
    assert items['ink']['preview'] is True
    # This PC has the model but not the LoRA.
    assert items['ink']['missing'] == [{'kind': 'lora', 'name': 'anima\\ink.safetensors'}]
    done = c.post(
        '/api/image/presets/import',
        json={'token': seen['token'], 'choices': {'ink': {'as': 'ink_shared'}, 'water': 'add'}},
    ).json()
    assert sorted(done['written']) == ['ink_shared', 'water']
    presets = {p['id']: p for p in done['presets']}
    assert presets['ink']['name'] == 'changed here' and presets['ink_shared']['name'] == 'ink'
    # The preview came along with its record.
    assert (paths.data / 'image' / 'presets' / 'ink_shared.webp').is_file() and presets['ink_shared'][
        'preview_url'
    ]
    # A token is used once.
    again = c.post('/api/image/presets/import', json={'token': seen['token'], 'choices': {}})
    assert again.status_code == 400 and again.json()['error']['key'] == 'server.presets.share.expired'


def test_replace_skip_and_bad_packages(unlocked):
    c = unlocked
    _preset(c, 'ink')
    package = c.get('/api/image/presets/export').content
    _preset(c, 'ink', name='local')
    seen = c.post('/api/image/presets/import/preview', content=package).json()
    skipped = c.post(
        '/api/image/presets/import', json={'token': seen['token'], 'choices': {'ink': 'skip'}}
    ).json()
    assert skipped['written'] == [] and skipped['presets'][0]['name'] == 'local'
    seen = c.post('/api/image/presets/import/preview', content=package).json()
    replaced = c.post(
        '/api/image/presets/import', json={'token': seen['token'], 'choices': {'ink': 'replace'}}
    ).json()
    assert replaced['written'] == ['ink'] and replaced['presets'][0]['name'] == 'ink'
    # "add" never overwrites a preset that is already here.
    seen = c.post('/api/image/presets/import/preview', content=package).json()
    assert (
        c.post('/api/image/presets/import', json={'token': seen['token'], 'choices': {'ink': 'add'}}).json()[
            'written'
        ]
        == []
    )

    for raw in (
        b'not a zip',
        _zip({'other.json': '{}'}),
        _zip({'atelierx-presets.json': json.dumps({'kind': 'other'})}),
    ):
        refused = c.post('/api/image/presets/import/preview', content=raw)
        assert refused.status_code == 400 and refused.json()['error']['key'] == 'server.presets.share.bad'


def _zip(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return out.getvalue()


def test_ids_that_differ_only_in_case_are_the_same_preset(unlocked, paths):
    # Review of #196: on Windows "ink" and "Ink" are one file, so taking one for the other overwrote a preset.
    c = unlocked
    _preset(c, 'Ink', name='kept')
    _preset(c, 'water')
    package = c.get('/api/image/presets/export', params={'ids': 'water'}).content
    seen = c.post('/api/image/presets/import/preview', content=package).json()
    refused = c.post(
        '/api/image/presets/import', json={'token': seen['token'], 'choices': {'water': {'as': 'ink'}}}
    )
    assert refused.status_code == 400 and refused.json()['error']['key'] == 'server.presets.share.bad_id'
    names = {p['id']: p['name'] for p in c.get('/api/image/presets').json()}
    assert names['Ink'] == 'kept' and 'ink' not in names
    # A package's own id in another case is "already here".
    c.delete('/api/image/presets/water')
    _preset(c, 'WATER', name='local')
    seen = c.post('/api/image/presets/import/preview', content=package).json()
    assert seen['items'][0]['exists'] is True


def test_a_refused_choice_writes_nothing_and_keeps_the_package_for_another_try(unlocked):
    # Review of #196: the first preset was written before the second was refused, and the token was gone.
    c = unlocked
    _preset(c, 'ink', name='local')
    _preset(c, 'water')
    package = c.get('/api/image/presets/export').content
    c.put('/api/image/presets/ink', json={'name': 'changed here', 'service': 'comfyui'})
    seen = c.post('/api/image/presets/import/preview', content=package).json()
    bad = {'ink': 'replace', 'water': {'as': 'ink'}}
    refused = c.post('/api/image/presets/import', json={'token': seen['token'], 'choices': bad})
    assert refused.status_code == 400
    assert {p['id']: p['name'] for p in c.get('/api/image/presets').json()}['ink'] == 'changed here'
    fixed = {'ink': 'replace', 'water': {'as': 'water_2'}}
    done = c.post('/api/image/presets/import', json={'token': seen['token'], 'choices': fixed}).json()
    assert sorted(done['written']) == ['ink', 'water_2']


def test_members_that_unpack_too_large_are_refused_before_they_are_read(unlocked):
    # Review of #196: a small ZIP could unpack a huge preview into memory.
    c = unlocked
    _preset(c, 'ink')
    package = zipfile.ZipFile(io.BytesIO(c.get('/api/image/presets/export').content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in package.namelist():
            archive.writestr(name, package.read(name))
        archive.writestr('presets/ink.webp', b'\0' * (17 * 1024**2))
    assert len(out.getvalue()) < 200_000
    refused = c.post('/api/image/presets/import/preview', content=out.getvalue())
    assert (
        refused.status_code == 400 and refused.json()['error']['key'] == 'server.presets.share.too_big_inside'
    )
