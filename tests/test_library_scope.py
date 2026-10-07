"""Changing the scope of a library item (#147): work → global moves it, global → work overrides it in this work."""


def _put(c, wid, ident, scope, from_scope=None, **item):
    body = {'scope': scope, 'work': wid, 'item': {'name': ident, 'prompt': [f'{ident} tag'], **item}}
    if from_scope:
        body['from_scope'] = from_scope
    return c.put(f'/api/image/library/styles/{ident}', json=body)


def _scopes(c, wid, ident):
    """Where the item is stored: the work's own list shows the work copy first; the global list has no work."""
    merged = c.get(f'/api/image/library/styles?work={wid}').json().get(ident)
    global_only = c.get('/api/image/library/styles').json().get(ident)
    return merged and merged['scope'], merged and merged['overrides'], global_only is not None


def test_saving_a_work_item_as_global_moves_it(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    assert _put(c, wid, 'soft', 'work').status_code == 200
    assert _scopes(c, wid, 'soft') == ('work', False, False)

    moved = _put(c, wid, 'soft', 'global', from_scope='work', prompt=['moved tag'])
    assert moved.status_code == 200
    assert moved.json()['soft']['scope'] == 'global'
    assert _scopes(c, wid, 'soft') == ('global', False, True)
    assert c.get('/api/image/library/styles').json()['soft']['prompt'] == ['moved tag']


def test_moving_onto_an_existing_global_item_replaces_it(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    _put(c, wid, 'film', 'global', prompt=['global tag'])
    _put(c, wid, 'film', 'work', prompt=['work tag'])
    assert _scopes(c, wid, 'film') == ('work', True, True)

    _put(c, wid, 'film', 'global', from_scope='work', prompt=['work tag'])
    assert _scopes(c, wid, 'film') == ('global', False, True)
    assert c.get('/api/image/library/styles').json()['film']['prompt'] == ['work tag']


def test_saving_a_global_item_for_one_work_overrides_it_there(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    _put(c, wid, 'ink', 'global', prompt=['global tag'])
    # Without from_scope (the screen sends it only when moving to global) both copies stay.
    _put(c, wid, 'ink', 'work', prompt=['work tag'])
    assert _scopes(c, wid, 'ink') == ('work', True, True)
    assert c.get('/api/image/library/styles').json()['ink']['prompt'] == ['global tag']


def test_an_unknown_from_scope_is_refused(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    assert _put(c, wid, 'odd', 'global', from_scope='elsewhere').status_code == 400
