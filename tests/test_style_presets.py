"""Style presets (#169): the generation preset with a service, tags and artist tags; style fragments folded into them."""

import json

from atelierx.image import library
from test_image import FakeComfy


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')


def test_presets_from_before_read_as_comfyui_presets_without_artist_tags():
    doc = library.preset_doc(
        {'name': 'old', 'family': 'sdxl', 'settings': {'steps': 28}, 'common': ['quality']}, 'old'
    )
    assert doc == {
        'schema_version': 2,
        'name': 'old',
        'service': 'comfyui',
        'family': 'sdxl',
        'tags': [],
        'settings': {'steps': 28},
        'artist': {'positive': '', 'negative': ''},
        'common': ['quality'],
    }
    nai = library.preset_doc(
        {
            'service': 'novelai',
            'family': 'anima',
            'tags': [' 수채 ', '수채', ''],
            'artist': {'positive': ['a', 'b']},
        },
        'nai',
    )
    # An internet service is its own family; tags are trimmed and kept once.
    assert (nai['family'], nai['tags'], nai['artist']['positive']) == ('novelai', ['수채'], 'a, b')


def test_style_fragments_fold_into_presets_once(paths):
    image = paths.data / 'image'
    _write(
        image / 'styles.json',
        {
            'schema_version': 1,
            'items': {
                'my01': {
                    'name': 'my01',
                    'prompt': ['(@topu:2.4)', '@kyokucho'],
                    'negative': ['@bad'],
                    'targets': ['anima'],
                },
                'my02': {
                    'name': '수채 느낌',
                    'prompt': ['@watercolor artist'],
                    'group': '수채',
                    'targets': ['novelai'],
                },
                'my03': {'name': 'sdxl', 'prompt': ['@sdxl artist'], 'model_family': 'sdxl'},
            },
        },
    )
    _write(
        image / 'presets' / 'w002_anima.json',
        {
            'schema_version': 1,
            'name': '무진기담',
            'family': 'anima',
            'settings': {'steps': 32},
            'styles': ['my01'],
        },
    )
    work = paths.works / '작품' / '.atelierx'
    _write(work / 'work.json', {'id': 'W002'})
    _write(
        work / 'image' / 'styles.json',
        {'schema_version': 1, 'items': {'film': {'name': 'film', 'prompt': ['@film']}}},
    )

    library.migrate_styles(paths)
    presets = {p['id']: p for p in library.presets(paths)}
    assert set(presets) == {'w002_anima', 'my02', 'my03', 'W002_film'}
    # The style a preset picked became its artist tags; the preset keeps its settings.
    assert presets['w002_anima']['artist'] == {'positive': '(@topu:2.4), @kyokucho', 'negative': '@bad'}
    assert presets['w002_anima']['settings'] == {'steps': 32}
    stored = json.loads((image / 'presets' / 'w002_anima.json').read_text(encoding='utf-8'))
    assert 'styles' not in stored and stored['schema_version'] == 2
    # Styles no preset used become presets of their own, for the service or family they were written for.
    assert (presets['my02']['name'], presets['my02']['service'], presets['my02']['tags']) == (
        '수채 느낌',
        'novelai',
        ['수채'],
    )
    assert (presets['my03']['service'], presets['my03']['family']) == ('comfyui', 'sdxl')
    assert presets['W002_film']['artist']['positive'] == '@film' and presets['W002_film']['settings'] == {}
    # The old files are kept aside, and running again changes nothing.
    assert (image / 'styles.migrated.json').is_file() and not (image / 'styles.json').exists()
    assert (work / 'image' / 'styles.migrated.json').is_file()
    library.migrate_styles(paths)
    assert {p['id'] for p in library.presets(paths)} == set(presets)


def test_the_order_names_artist_where_style_was(paths):
    _write(paths.data / 'image' / 'compose.json', {'order': ['common', 'style', 'composition']})
    assert library.compose_rules(paths)['order'] == ['common', 'artist', 'composition']


def test_a_preset_gives_its_artist_tags_and_only_to_its_service(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    c.put(
        '/api/image/presets/ink',
        json={
            'name': '먹선',
            'service': 'comfyui',
            'family': 'anima',
            'tags': ['선화'],
            'settings': {'steps': 20},
            'artist': {'positive': '@ink artist, # tried @other', 'negative': '@bad artist'},
        },
    )
    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    composed = c.post(
        f'/api/works/{wid}/image/compose', json={'targets': [target], 'preset_id': 'ink'}
    ).json()[0]
    assert composed['parts']['artist'] == '@ink artist' and '@bad artist' in composed['negative']
    assert composed['artist'] == {'positive': '@ink artist', 'negative': '@bad artist'}
    # The screen may change the artist tags for one run.
    edited = c.post(
        f'/api/works/{wid}/image/compose',
        json={'targets': [target], 'preset_id': 'ink', 'artist': {'positive': '@other'}},
    ).json()[0]
    assert edited['parts']['artist'] == '@other'
    refused = c.post(
        f'/api/works/{wid}/image/compose',
        json={'targets': [target], 'preset_id': 'ink', 'service': 'novelai'},
    )
    assert (
        refused.status_code == 400 and refused.json()['error']['key'] == 'server.image.queue.preset_service'
    )


def test_a_preview_is_made_once_kept_as_webp_and_marked_stale_when_the_preset_changes(unlocked):
    c = unlocked
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    preset = {
        'name': '먹선',
        'service': 'comfyui',
        'family': 'anima',
        'settings': {'model': 'anima\\m.safetensors', 'steps': 20},
        'artist': {'positive': '@ink artist', 'negative': '@bad artist'},
        'common': ['quality'],
    }
    c.put('/api/image/presets/ink', json=preset)
    queued = c.post('/api/image/presets/ink/preview').json()
    assert queued['count'] == 1 and queued['seeds'] == [1234567]
    (job,) = runtime.jobs
    # The fixed subject, rated safe, after the preset's common prompts and artist tags.
    positive = job['snapshot']['positive']
    assert positive.startswith('masterpiece') and positive.endswith('@ink artist, 1girl, solo, safe')
    assert '@bad artist' in job['snapshot']['negative'] and 'nsfw' in job['snapshot']['negative']
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')

    (listed,) = c.get('/api/image/presets').json()
    assert listed['preview_stale'] is False and listed['preview']['seed'] == 1234567
    image = c.get(listed['preview_url'])
    assert image.status_code == 200 and image.content[:4] == b'RIFF'

    # Changing what the picture depends on, or the shared seed, makes it stale; the name does not.
    c.put('/api/image/presets/ink', json={**listed, 'name': '먹선 2'})
    assert c.get('/api/image/presets').json()[0]['preview_stale'] is False
    c.put('/api/image/presets/ink', json={**listed, 'artist': {'positive': '@other'}})
    assert c.get('/api/image/presets').json()[0]['preview_stale'] is True
    c.put('/api/image/presets/ink', json=listed)
    c.put('/api/image/settings/presets', json={'preview_seed': 42})
    assert c.get('/api/image/presets').json()[0]['preview_stale'] is True

    c.delete('/api/image/presets/ink')
    assert c.get(listed['preview_url']).status_code == 404


def test_previews_are_made_with_comfyui_only(unlocked):
    c = unlocked
    c.put('/api/image/presets/nai', json={'name': 'nai', 'service': 'novelai'})
    refused = c.post('/api/image/presets/nai/preview')
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.image.presets.preview_comfy_only'
