"""Chat test sets (#50): saved inputs, runs with model and snapshot, compared later."""


def _work(c):
    return c.post('/api/samples/single/install').json()['id']


def test_a_set_is_saved_run_twice_and_its_runs_say_what_they_ran_against(unlocked):
    c = unlocked
    wid = _work(c)
    empty = c.get(f'/api/works/{wid}/tests/sets').json()
    assert empty['sets'] == []
    saved = c.put(
        f'/api/works/{wid}/tests/sets',
        json={
            'base_revision': empty['revision'],
            'sets': [
                {
                    'name': '첫 만남',
                    'start': '시작 상황.md',
                    'persona': {'name': '도윤', 'description': '조용한 손님'},
                    'inputs': ['안녕하세요', '', '오늘 추천 메뉴는?'],
                }
            ],
        },
    ).json()
    (test_set,) = saved['sets']
    assert test_set['inputs'] == ['안녕하세요', '오늘 추천 메뉴는?'] and len(test_set['id']) == 8

    first = c.post(f'/api/works/{wid}/tests/runs', json={'set_id': test_set['id']}).json()
    assert first['status'] == 'running' and first['model']['provider'] == 'local' and first['snapshot']['id']
    turns = [
        {'input': '안녕하세요', 'reply': '어서 오세요'},
        {'input': '오늘 추천 메뉴는?', 'reply': '노을 라떼요'},
    ]
    done = c.put(f'/api/works/{wid}/tests/runs/{first["id"]}', json={'turns': turns, 'status': 'done'}).json()
    assert done['status'] == 'done' and done['finished_at'] and done['turns'][1]['reply'] == '노을 라떼요'

    # The work changes, then the same set runs again: the run points at a newer snapshot.
    work = c.app.state.app.works.get(wid)
    item = work.get_item('메인.md')
    work.save_item('메인.md', {}, item['body'] + '\n- 말투를 바꿈\n', item['hash'])
    second = c.post(f'/api/works/{wid}/tests/runs', json={'set_id': test_set['id']}).json()
    assert second['snapshot']['id'] != first['snapshot']['id']
    c.put(f'/api/works/{wid}/tests/runs/{second["id"]}', json={'turns': turns[:1], 'status': 'stopped'})

    runs = c.get(f'/api/works/{wid}/tests/runs', params={'set': test_set['id']}).json()
    assert [r['id'] for r in runs] == [second['id'], first['id']]
    assert runs[0]['status'] == 'stopped' and runs[0]['turns'] == 1 and runs[0]['inputs'] == 2
    assert c.get(f'/api/works/{wid}/tests/runs/{first["id"]}').json()['set']['name'] == '첫 만남'

    left = c.delete(f'/api/works/{wid}/tests/runs/{second["id"]}').json()
    assert [r['id'] for r in left] == [first['id']]


def test_sets_are_checked(unlocked):
    c = unlocked
    wid = _work(c)
    revision = c.get(f'/api/works/{wid}/tests/sets').json()['revision']
    stale = c.put(f'/api/works/{wid}/tests/sets', json={'base_revision': 'old', 'sets': []})
    assert stale.status_code == 409
    for bad in ({'name': '', 'inputs': ['x']}, {'name': 'x', 'inputs': []}):
        answer = c.put(f'/api/works/{wid}/tests/sets', json={'base_revision': revision, 'sets': [bad]})
        assert answer.status_code == 400
    outside = c.put(
        f'/api/works/{wid}/tests/sets',
        json={'base_revision': revision, 'sets': [{'name': 'x', 'inputs': ['y'], 'start': '../x.md'}]},
    )
    assert outside.status_code == 400
    assert c.post(f'/api/works/{wid}/tests/runs', json={'set_id': 'nope'}).status_code == 404
    assert c.get(f'/api/works/{wid}/tests/runs/../x').status_code in (404, 400)


def test_a_body_that_is_not_json_or_not_utf8_is_a_bad_request(unlocked):
    wid = _work(unlocked)
    # Cut-off JSON, and Korean sent in the legacy Windows code page instead of UTF-8.
    for raw in (b'{"sets": [', '{"name": "안녕"}'.encode('cp949')):
        response = unlocked.put(
            f'/api/works/{wid}/tests/sets', content=raw, headers={'Content-Type': 'application/json'}
        )
        assert response.status_code == 400
        assert response.json()['error']['key'] == 'server.request.invalid_json'
