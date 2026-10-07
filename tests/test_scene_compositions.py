"""Compositions with a background, and one that hides the outfit (#162)."""


def _put(c, wid, kind, ident, item):
    response = c.put(f'/api/image/library/{kind}/{ident}', json={'scope': 'work', 'work': wid, 'item': item})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_composition_without_outfit_leaves_the_outfit_out_for_its_expression(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    _put(
        c,
        wid,
        'compositions',
        'bath',
        {
            'name': '욕실',
            'prompt': ['bathroom', 'shower', 'steam'],
            'hide_outfit': True,
            'suggest_slots': ['top'],
        },
    )
    _put(
        c,
        wid,
        'expressions',
        'shower',
        {
            'name': '샤워',
            'rating': 'general',
            'prompt': ['completely nude', 'showering'],
            'composition': 'bath',
        },
    )
    targets = [
        {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': expression}
        for expression in ('smile', 'shower')
    ]
    smile, shower = c.post(
        f'/api/works/{wid}/image/compose', json={'targets': targets, 'settings': {'family': 'anima'}}
    ).json()

    # The ordinary expression keeps its outfit and the default composition's white background.
    assert smile['outfit_hidden'] is False and smile['parts']['outfit']
    assert 'white background' in smile['positive']
    # The shower expression: no outfit tags, its own background, and the reason in the result.
    assert shower['outfit_hidden'] is True and shower['composition_name'] == '욕실'
    assert shower['parts']['outfit'] == '' and shower['outfit_slots'] == []
    assert 'bathroom' in shower['positive'] and 'completely nude' in shower['positive']
    assert 'white background' not in shower['positive']
    assert not set(smile['parts']['outfit'].split(', ')) & set(shower['positive'].split(', '))

    saved = c.get('/api/image/library/compositions', params={'work': wid}).json()
    assert saved['bath']['hide_outfit'] is True
