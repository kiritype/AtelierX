"""Compositions with a background, and one that hides the outfit (#162)."""

from image_ids import image_id


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
    assert saved[image_id(c, 'compositions', 'bath', wid)]['hide_outfit'] is True


def test_visual_shot_replaces_expression_composition_and_keeps_other_prompt_parts(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    url = f'/api/works/{wid}/image/compose'
    request = {
        'targets': [target],
        'artist': {'positive': 'soft color'},
        'overrides': {'appearance': 'blue eyes'},
    }
    baseline = c.post(url, json=request).json()[0]
    assert baseline['composition_id'] and baseline['outfit_slots']

    catalog = c.get('/api/image/library/rules').json()['shot_choices']
    for framing, expected in [
        ('face', 'portrait'),
        ('upper', 'upper body'),
        ('cowboy', 'cowboy shot'),
        ('full', 'full body'),
    ]:
        shot = {'framing': framing, 'direction': 'back', 'height': 'high'}
        response = c.post(url, json={**request, 'shot': shot})
        assert response.status_code == 200, response.text
        result = response.json()[0]
        assert result['shot'] == shot and result['composition_id'] is None
        assert result['parts']['composition'] == f'{expected}, from behind, from above'
        assert catalog['framing'][framing]['prompt'] == expected
        assert result['parts']['composition'] in result['positive']
        assert 'white background' not in result['positive']
        assert 'from behind' not in result['negative']
        for part in ('common', 'artist', 'appearance', 'expression'):
            assert result['parts'][part] == baseline['parts'][part]
        if framing == 'face':
            assert not result['outfit_slots'] and not result['parts']['outfit']
        if framing == 'upper':
            assert 'top' in result['outfit_slots'] and 'bottom' not in result['outfit_slots']
        if framing in ('cowboy', 'full'):
            assert 'bottom' in result['outfit_slots']

    invalid = c.post(url, json={**request, 'shot': {**shot, 'direction': ['back']}})
    assert invalid.status_code == 400
    assert invalid.json()['error']['key'] == 'server.image.compose.invalid_shot'
    assert c.post(url, json=request).json()[0] == baseline


def test_visual_shot_preview_matches_queued_prompt(unlocked):
    from test_image import FakeComfy

    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = FakeComfy()
    request = {
        'targets': [{'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}],
        'shot': {'framing': 'cowboy', 'direction': 'three_quarter', 'height': 'low'},
        'settings': {'seed': 13},
    }
    preview = c.post(f'/api/works/{wid}/image/compose', json=request).json()[0]
    result = c.post(f'/api/works/{wid}/image/jobs', json=request)
    assert result.status_code == 200, result.text
    job = runtime.queue.select(lambda item: item.get('work_id') == wid)[0]['snapshot']
    assert job['parts']['composition'] == 'cowboy shot, three-quarter view, from below'
    for key in ('shot', 'outfit_slots', 'positive', 'negative'):
        assert job[key] == preview[key]
