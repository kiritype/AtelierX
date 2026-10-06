"""Library fragments with groups and targets (#80): what they are written for decides whether they go in."""

import json

from atelierx.image import library


def _style(c, wid, ident, **item):
    return c.put(
        f'/api/image/library/styles/{ident}',
        json={'scope': 'work', 'work': wid, 'item': {'name': ident, 'prompt': [f'{ident} tag'], **item}},
    ).json()


def test_items_keep_a_group_and_several_known_targets(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    rules = c.get('/api/image/library/rules').json()
    assert [t['id'] for t in rules['targets']] == ['sdxl', 'anima', 'novelai', 'pixai']

    saved = _style(c, wid, 'film', group=' 화면 효과 ', targets=['sdxl', 'pixai', 'sdxl', 'nope'])
    assert saved['film']['group'] == '화면 효과'
    assert saved['film']['targets'] == ['sdxl', 'pixai']
    plain = _style(c, wid, 'plain')['plain']
    assert plain['group'] == '' and plain['targets'] == []

    # The default common prompts come grouped, and the quality tags are for the SDXL-style targets.
    common = c.get(f'/api/image/library/common?work={wid}').json()
    assert common['quality']['group'] == '품질'
    assert common['quality']['targets'] == ['sdxl', 'anima', 'pixai']
    assert common['background_simple']['targets'] == []


def test_files_from_before_read_their_model_family_as_targets(unlocked, paths):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    work = c.app.state.app.works.get(wid)
    path = work.app / 'image' / 'styles.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'items': {
                    'a': {'name': 'a', 'prompt': ['a'], 'model_family': 'anima'},
                    'b': {'name': 'b', 'prompt': ['b'], 'model_family': 'sdxl'},
                    'c': {'name': 'c', 'prompt': ['c'], 'model_family': 'shared'},
                },
            }
        ),
        encoding='utf-8',
    )
    styles = c.get(f'/api/image/library/styles?work={wid}').json()
    assert [styles[k]['targets'] for k in 'abc'] == [['anima'], ['sdxl'], []]
    assert 'model_family' not in styles['a']
    assert library.fits({'model_family': 'anima'}, 'sdxl') is False
    assert library.fits({'model_family': 'shared'}, 'sdxl') is True


def test_fragments_for_other_targets_are_left_out_and_named(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    _style(c, wid, 'nai_only', targets=['novelai'])
    _style(c, wid, 'everyone')
    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    body = {'targets': [target], 'style_ids': ['nai_only', 'everyone'], 'common_ids': ['quality']}

    anima = c.post(f'/api/works/{wid}/image/compose', json={**body, 'settings': {'family': 'anima'}}).json()[
        0
    ]
    assert 'everyone tag' in anima['positive'] and 'masterpiece' in anima['positive']
    assert 'nai_only tag' not in anima['positive']
    assert [w['key'] for w in anima['warnings']] == ['server.image.compose.left_out']
    assert anima['warnings'][0]['values']['targets'] == 'NovelAI'

    nai = c.post(f'/api/works/{wid}/image/compose', json={**body, 'settings': {'family': 'novelai'}}).json()[
        0
    ]
    assert 'nai_only tag' in nai['positive'] and 'masterpiece' not in nai['positive']


def test_the_target_list_can_be_changed_and_keeps_one(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    _style(c, wid, 'flux_look', targets=['flux'])
    rules = c.put(
        '/api/image/library/rules/targets',
        json={
            'targets': [{'id': 'sdxl', 'name': 'SDXL·IL'}, {'id': 'flux', 'name': 'Flux'}, {'id': 'bad id!'}]
        },
    ).json()
    assert [t['id'] for t in rules['targets']] == ['sdxl', 'flux']
    assert _style(c, wid, 'flux_look', targets=['flux'])['flux_look']['targets'] == ['flux']

    # Removing a target leaves the items alone; one written only for it now fits every target.
    c.put('/api/image/library/rules/targets', json={'targets': [{'id': 'sdxl', 'name': 'SDXL·IL'}]})
    assert c.get(f'/api/image/library/styles?work={wid}').json()['flux_look']['targets'] == []

    refused = c.put('/api/image/library/rules/targets', json={'targets': []})
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.image.library.targets'
