"""Deployment codes of expressions and outfits (decision 0023): free text that can be part of a path."""

import json

from atelierx.image import library


def _expression(c, wid, ident, **item):
    return c.put(
        f'/api/image/library/expressions/{ident}',
        json={'scope': 'work', 'work': wid, 'item': {'name': ident, 'prompt': ['smile'], **item}},
    )


def test_default_expressions_have_codes_and_any_path_text_is_a_code(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    expressions = c.get(f'/api/image/library/expressions?work={wid}').json()
    assert [expressions[i]['code'] for i in ('neutral', 'smile', 'thinking')] == ['001', '002', '008']

    saved = _expression(c, wid, 'grin', code=' smile_a ')
    assert saved.status_code == 200 and saved.json()['grin']['code'] == 'smile_a'
    # The same code twice is allowed; the screen points it out.
    assert _expression(c, wid, 'grin2', code='002').status_code == 200
    assert _expression(c, wid, 'empty').json()['empty']['code'] == ''
    for bad in ('a/b', '..', 'x:y', 'q?'):
        assert _expression(c, wid, 'bad', code=bad).status_code == 400, bad


def test_default_codes_fill_only_items_that_never_had_one(paths):
    library_dir = paths.data / 'image'
    library_dir.mkdir(parents=True, exist_ok=True)
    (library_dir / 'expressions.json').write_text(
        json.dumps(
            {
                'schema_version': 1,
                'items': {
                    'smile': {'name': '미소', 'prompt': ['smile']},
                    'sad': {'name': '슬픔', 'code': '', 'prompt': ['sad']},
                    'mine': {'name': '내 표정', 'prompt': ['wink']},
                },
            }
        ),
        encoding='utf-8',
    )
    library.fill_default_codes(paths)
    items = json.loads((library_dir / 'expressions.json').read_text(encoding='utf-8'))['items']
    assert items['smile']['code'] == '002'
    assert items['sad']['code'] == ''
    assert 'code' not in items['mine']


def test_an_outfit_code_is_kept_and_does_not_unlink_the_outfit_from_its_text(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    url = f'/api/works/{wid}/image/characters/C001'
    loaded = c.get(url).json()
    design = loaded['design']
    outfit_id = next(iter(design['outfits']))
    had_source = 'source' in design['outfits'][outfit_id]
    design['outfits'][outfit_id]['code'] = ' uniform '
    saved = c.put(url, json={'design': design, 'base_revision': loaded['revision']})
    assert saved.status_code == 200
    outfit = saved.json()['design']['outfits'][outfit_id]
    assert outfit['code'] == 'uniform'
    assert ('source' in outfit) == had_source

    design = saved.json()['design']
    design['outfits'][outfit_id]['code'] = 'a/b'
    bad = c.put(url, json={'design': design, 'base_revision': saved.json()['revision']})
    assert bad.status_code == 400
