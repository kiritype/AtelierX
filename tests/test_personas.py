"""Personas: one list for the whole app, and the {{user}} section the test chat sends."""

import json


def test_the_list_is_saved_for_the_whole_app_with_a_revision_check(unlocked):
    c = unlocked
    empty = c.get('/api/personas').json()
    assert empty['personas'] == []
    saved = c.put(
        '/api/personas',
        json={
            'base_revision': empty['revision'],
            'personas': [
                {'name': ' 소연 ', 'description': '대학생.\r\n말이 빠르다.'},
                {'name': '', 'description': ''},
            ],
        },
    ).json()
    first, second = saved['personas']
    assert first['name'] == '소연' and first['description'] == '대학생.\n말이 빠르다.'
    assert first['id'].startswith('p-') and first['id'] != second['id']
    assert c.get('/api/personas').json() == saved

    stale = c.put('/api/personas', json={'base_revision': empty['revision'], 'personas': []})
    assert stale.status_code == 409 and stale.json()['error']['key'] == 'server.personas.stale'
    too_long = c.put(
        '/api/personas', json={'base_revision': saved['revision'], 'personas': [{'name': 'x' * 101}]}
    )
    assert too_long.status_code == 400

    # An unchanged persona keeps its id and time; a removed one is gone.
    kept = c.put('/api/personas', json={'base_revision': saved['revision'], 'personas': [first]}).json()
    assert kept['personas'] == [first]


def test_the_persona_is_a_user_section_with_reserved_names_replaced(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    persona = {'name': '소연', 'description': '{{char}}의 소꿉친구.\n존댓말을 쓴다.'}
    ctx = c.post(
        f'/api/works/{wid}/chat/preview', json={'history': [], 'message': '안녕', 'persona': persona}
    ).json()
    assert ctx['user_name'] == '소연'
    section = ctx['system'].split('## 소연 설정\n', 1)[1]
    assert section.startswith('이름: 소연\n')
    assert '존댓말을 쓴다.' in section and '{{char}}' not in section

    # A description without a name is still sent; the name falls back to 사용자.
    nameless = c.post(
        f'/api/works/{wid}/chat/preview',
        json={'history': [], 'message': '안녕', 'persona': {'name': '', 'description': '말수가 적다.'}},
    ).json()
    assert '## 사용자 설정\n말수가 적다.' in nameless['system']


def test_preview_matches_the_sent_context_without_running_the_model(unlocked, monkeypatch):
    c = unlocked
    wid = c.post('/api/samples/ensemble/install').json()['id']
    llm = c.app.state.app.llm
    payload = {
        'history': [{'role': 'assistant', 'text': '농구부 훈련이 끝났습니다.'}],
        'message': '언제 모이나요?',
        'persona': {'name': '소연', 'description': '새로 전학 왔다.'},
    }

    def unexpected_model_request(*args, **kwargs):
        raise AssertionError('Preview must assemble the context locally without touching the model.')

    with monkeypatch.context() as blocked:
        blocked.setattr(llm, 'require_consent', unexpected_model_request)
        blocked.setattr(llm, 'stream', unexpected_model_request)
        preview = c.post(f'/api/works/{wid}/chat/preview', json=payload)
    assert preview.status_code == 200
    assert 'L002' in {item['id'] for item in preview.json()['picked']}
    assert c.get(f'/api/works/{wid}/tests/runs').json() == []

    sent = c.post(f'/api/works/{wid}/chat/send', json=payload)
    assert sent.status_code == 200
    event, data = sent.text.split('\n\n', 1)[0].splitlines()
    assert event == 'event: context'
    assert json.loads(data.removeprefix('data: ')) == preview.json()
