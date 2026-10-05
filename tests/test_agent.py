"""Agent panel (11-agent): modes, guidelines settings, conversations with the mock model, proposals and adoption."""

import json

from atelierx.core import agent


def _work(c, sample='single'):
    return c.post(f'/api/samples/{sample}/install').json()['id']


def _events(response):
    out = []
    for block in response.text.split('\n\n'):
        lines = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line)
        if 'event' in lines:
            out.append((lines['event'], lines.get('data', '')))
    return out


def test_modes_come_from_app_defaults_and_can_be_overridden(unlocked, paths):
    c = unlocked
    wid = _work(c)
    modes = c.get(f'/api/works/{wid}/agent/modes').json()
    ids = [m['id'] for m in modes]
    assert {'idea', 'start', 'character', 'lorebook', 'jsx', 'review', 'free'} <= set(ids)
    assert ids[-1] == 'free'
    character = next(m for m in modes if m['id'] == 'character')
    assert character['scope'] == 'file' and character['name'] == '캐릭터 다듬기'

    item = c.get('/api/guidelines/file', params={'name': 'agent/character.md'}).json()
    saved = c.put(
        '/api/guidelines/file',
        params={'name': 'agent/character.md'},
        json={
            'text': item['text'].replace('캐릭터 다듬기', '인물 손보기'),
            'base_revision': item['revision'],
        },
    ).json()
    assert saved['default_text'] == item['text']
    modes = c.get(f'/api/works/{wid}/agent/modes').json()
    assert next(m for m in modes if m['id'] == 'character')['name'] == '인물 손보기'


def test_the_guidelines_screen_lists_edits_adds_and_deletes(unlocked):
    c = unlocked
    data = c.get('/api/guidelines').json()
    assert '파일을 직접 고칠 수 없다' in data['fixed']['agent']
    by_name = {i['name']: i for i in data['items']}
    assert by_name['agent/idea.md']['group'] == 'agent' and by_name['agent/idea.md']['source'] == 'default'
    assert by_name['compression.md']['group'] == 'task' and by_name['image-prompt.md']['group'] == 'image'

    item = c.get('/api/guidelines/file', params={'name': 'compression.md'}).json()
    c.put(
        '/api/guidelines/file',
        params={'name': 'compression.md'},
        json={'text': 'x', 'base_revision': item['revision']},
    )
    stale = c.put(
        '/api/guidelines/file',
        params={'name': 'compression.md'},
        json={'text': 'y', 'base_revision': item['revision']},
    )
    assert stale.status_code == 409
    by_name = {i['name']: i for i in c.get('/api/guidelines').json()['items']}
    assert by_name['compression.md']['source'] == 'modified'

    mode = '---\nname: 말투 점검\nscope: work\norder: 5\n---\n말투만 본다.\n'
    added = c.put(
        '/api/guidelines/file',
        params={'name': 'agent/tone.md'},
        json={'text': mode, 'base_revision': ''},
    )
    assert added.status_code == 200
    tone = next(i for i in c.get('/api/guidelines').json()['items'] if i['name'] == 'agent/tone.md')
    assert tone['source'] == 'custom' and tone['scope'] == 'work' and tone['order'] == 5

    assert c.delete('/api/guidelines/file', params={'name': 'agent/idea.md'}).status_code == 400
    assert c.delete('/api/guidelines/file', params={'name': 'agent/tone.md'}).status_code == 200
    for bad in ('../x.md', 'agent/Bad Name.md', 'a/b/c.md', 'x.txt'):
        assert c.get('/api/guidelines/file', params={'name': bad}).status_code == 400, bad


def test_a_conversation_streams_a_proposal_that_is_reviewed_and_adopted(unlocked):
    c = unlocked
    wid = _work(c)
    path = '인물/윤하람.md'
    before = c.get(f'/api/works/{wid}/file', params={'path': path}).json()
    session = c.post(
        f'/api/works/{wid}/agent/sessions',
        json={'mode': 'character', 'scope': {'kind': 'file', 'paths': [path]}},
    ).json()
    sid = session['id']
    preview = c.post(
        f'/api/works/{wid}/agent/sessions/{sid}/preview', json={'message': '말투를 다듬어 줘'}
    ).json()
    assert preview['files'] == 1 and preview['tokens'] < preview['budget'] and not preview['omitted']

    events = _events(
        c.post(f'/api/works/{wid}/agent/sessions/{sid}/send', json={'message': '말투를 다듬어 줘'})
    )
    assert events[0][0] == 'context' and events[-1][0] == 'end'
    end = json.loads(events[-1][1])
    assert end['finish_reason'] == 'stop' and end['turn'] == 2
    proposal = end['proposals'][0]
    assert proposal['path'] == path and not proposal['new'] and not proposal['truncated']
    assert proposal['base_hash'] == before['hash'] and proposal['warnings'] == []

    doc = c.get(f'/api/works/{wid}/agent/sessions/{sid}').json()
    assert doc['title'] == '말투를 다듬어 줘'
    assert [t['role'] for t in doc['turns']] == ['user', 'assistant']
    assert c.get(f'/api/works/{wid}/agent/sessions').json()[0]['turns'] == 2

    draft_id = c.post(f'/api/works/{wid}/agent/sessions/{sid}/proposals/2/1/review').json()['draft_id']
    # Sending the same proposal again opens the same draft.
    assert (
        c.post(f'/api/works/{wid}/agent/sessions/{sid}/proposals/2/1/review').json()['draft_id'] == draft_id
    )
    draft = c.get(f'/api/works/{wid}/drafts/{draft_id}').json()
    assert draft['kind'] == 'agent_file' and draft['target']['base_hash'] == before['hash']
    text = draft['candidates'][0]['text']
    assert '(모의 에이전트가 덧붙인 줄)' in text and text.startswith('---\n')

    applied = c.post(f'/api/works/{wid}/agent-drafts/{draft_id}/apply', json={'text': text}).json()
    after = c.get(f'/api/works/{wid}/file', params={'path': path}).json()
    assert applied['hash'] == after['hash'] and '(모의 에이전트가 덧붙인 줄)' in after['body']
    assert after['meta']['id'] == before['meta']['id']
    assert any(s['reason'] == 'before_llm' for s in c.get(f'/api/works/{wid}/snapshots').json())
    again = c.post(f'/api/works/{wid}/agent-drafts/{draft_id}/apply', json={'text': text})
    assert again.status_code == 409
    stored = c.get(f'/api/works/{wid}/agent/sessions/{sid}').json()['turns'][1]['proposals'][0]
    assert stored['draft_id'] == draft_id and stored['draft_status'] == 'applied'


def test_a_proposal_for_a_file_changed_since_the_answer_is_refused(unlocked):
    c = unlocked
    wid = _work(c)
    path = '인물/윤하람.md'
    sid = c.post(
        f'/api/works/{wid}/agent/sessions', json={'mode': 'free', 'scope': {'kind': 'file', 'paths': [path]}}
    ).json()['id']
    c.post(f'/api/works/{wid}/agent/sessions/{sid}/send', json={'message': '고쳐 줘'})
    item = c.get(f'/api/works/{wid}/file', params={'path': path}).json()
    c.put(
        f'/api/works/{wid}/file',
        params={'path': path},
        json={'body': item['body'] + '\n덧붙임', 'base_hash': item['hash']},
    )
    stale = c.post(f'/api/works/{wid}/agent/sessions/{sid}/proposals/2/1/review')
    assert stale.status_code == 409 and stale.json()['error']['key'] == 'server.agent.stale'


def test_new_files_are_created_only_when_adopted_and_ids_stay_unique(unlocked):
    c = unlocked
    wid = _work(c)
    sessions_dir_work = c.post(
        f'/api/works/{wid}/agent/sessions', json={'mode': 'free', 'scope': {'kind': 'work'}}
    ).json()
    assert sessions_dir_work['scope'] == {'kind': 'work', 'paths': []}
    from atelierx.core.drafts import (
        Drafts,
    )

    work = unlocked.app.state.app.works.get(wid)
    drafts = Drafts(work)
    new = drafts.create(
        'agent_file',
        {'path': '장소/서점.md', 'id': 'L009', 'base_hash': None, 'new': True},
        {},
        [{'text': '---\nkind: lorebook\nid: L009\n---\n동네 서점.\n'}],
    )
    assert not (work.folder / '장소' / '서점.md').exists()
    created = c.post(
        f'/api/works/{wid}/agent-drafts/{new["id"]}/apply', json={'text': new['candidates'][0]['text']}
    )
    assert created.status_code == 200 and (work.folder / '장소' / '서점.md').is_file()

    taken = drafts.create(
        'agent_file',
        {'path': '장소/다른곳.md', 'id': 'C001', 'base_hash': None, 'new': True},
        {},
        [{'text': '---\nkind: lorebook\nid: C001\n---\n'}],
    )
    refused = c.post(
        f'/api/works/{wid}/agent-drafts/{taken["id"]}/apply', json={'text': taken['candidates'][0]['text']}
    )
    assert refused.status_code == 409 and refused.json()['error']['key'] == 'server.works.id_taken'
    broken = drafts.create(
        'agent_file', {'path': '장소/깨짐.md', 'new': True}, {}, [{'text': '---\nkind: [\n---\n'}]
    )
    assert (
        c.post(
            f'/api/works/{wid}/agent-drafts/{broken["id"]}/apply', json={'text': '---\nkind: [\n---\n'}
        ).status_code
        == 400
    )


def test_reading_proposals(unlocked):
    c = unlocked
    wid = _work(c)
    work = unlocked.app.state.app.works.get(wid)
    original = (work.folder / '인물' / '윤하람.md').read_text(encoding='utf-8')
    shorter = original[: len(original) // 3]
    text = (
        '설명\n<<<file path="./인물/윤하람.md">>>\n' + shorter + '\n(이하 동일)\n<<<end>>>\n'
        '<<<file path="메모/새 메모.md">>>\n```markdown\n---\nkind: note\n---\n메모\n```\n<<<end>>>\n'
        '<<<file path="../밖.md">>>\nx\n<<<end>>>\n'
        '<<<file path="그림.png">>>\nx\n<<<end>>>\n'
        '<<<file path="메모/끊김.md">>>\n---\nkind: note\n---\n쓰다가'
    )
    found = {p['path']: p for p in agent.proposals(work, text)}
    harang = found['인물/윤하람.md']
    assert {'omission', 'shrunk'} <= set(harang['warnings']) and not harang['new']
    memo = found['메모/새 메모.md']
    assert memo['new'] and memo['text'] == '---\nkind: note\n---\n메모\n' and memo['warnings'] == []
    assert found['../밖.md']['rejected'] == 'bad_path'
    assert found['그림.png']['rejected'] == 'not_item'
    assert found['메모/끊김.md']['truncated']
    twice = agent.proposals(
        work, '<<<file path="a.md">>>\n1\n<<<end>>>\n<<<file path="a.md">>>\n2\n<<<end>>>'
    )
    assert len(twice) == 1 and twice[0]['text'] == '2\n'
    wrapped = agent.proposals(
        work, '<<<file path="메모/a.md">>>\n---\nkind: note\n---\n`{{user}}`에게 인사했다.\n<<<end>>>'
    )
    assert wrapped[0]['warnings'] == ['wrapped_ref']
    changed = original.replace('id: C001', 'id: C099')
    assert (
        'id_changed'
        in agent.proposals(work, f'<<<file path="인물/윤하람.md">>>\n{changed}<<<end>>>')[0]['warnings']
    )


def test_bodies_that_do_not_fit_the_budget_stay_in_the_listing_only(unlocked, paths):
    c = unlocked
    wid = _work(c)
    s = unlocked.app.state.app
    work = s.works.get(wid)
    effective = s.presets.effective(work.doc())
    session = {'mode': 'review', 'scope': {'kind': 'work', 'paths': []}, 'turns': []}
    messages, summary = agent.build(
        work, paths, effective, effective['linked'], session, '검토해 줘', [], 100000
    )
    assert summary['files'] == len(work.index()) and not summary['omitted']
    assert (
        '## 모드 지침' in messages[0]['content']
        and '<<<file path="인물/윤하람.md">>>' in messages[0]['content']
    )
    small, summary = agent.build(work, paths, effective, effective['linked'], session, '검토해 줘', [], 1500)
    assert summary['omitted'] and summary['files'] < len(work.index())
    assert '인물/윤하람.md' in small[0]['content']  # still listed
    attached, _ = agent.build(
        work,
        paths,
        effective,
        effective['linked'],
        session,
        '이 부분',
        [{'path': '인물/윤하람.md', 'from': 3, 'to': 4, 'text': '고른 글'}],
        100000,
    )
    assert attached[-1]['content'].startswith('[첨부 인물/윤하람.md:3-4]\n고른 글')


def test_an_edit_saved_while_the_answer_streams_is_not_overwritten(unlocked, monkeypatch):
    c = unlocked
    wid = _work(c)
    path = '인물/윤하람.md'
    s = unlocked.app.state.app
    work = s.works.get(wid)
    real_stream = s.llm.stream

    async def stream_with_an_edit(task, messages, **kwargs):
        edited = False
        async for event in real_stream(task, messages, **kwargs):
            if not edited:
                # The user saves while the answer is still coming; the model saw the text before this edit.
                item = work.get_item(path)
                work.save_item(path, {}, item['body'] + '\nUSER EDIT\n', item['hash'])
                edited = True
            yield event

    monkeypatch.setattr(s.llm, 'stream', stream_with_an_edit)
    sid = c.post(
        f'/api/works/{wid}/agent/sessions', json={'mode': 'free', 'scope': {'kind': 'file', 'paths': [path]}}
    ).json()['id']
    end = json.loads(
        _events(c.post(f'/api/works/{wid}/agent/sessions/{sid}/send', json={'message': '고쳐 줘'}))[-1][1]
    )
    assert end['proposals'][0]['warnings'] == ['changed_since']
    review = c.post(f'/api/works/{wid}/agent/sessions/{sid}/proposals/2/1/review')
    assert review.status_code == 409 and review.json()['error']['key'] == 'server.agent.stale'
    assert 'USER EDIT' in work.get_item(path)['body']


def test_a_proposal_for_a_file_the_model_never_saw_is_flagged(unlocked):
    c = unlocked
    wid = _work(c)
    work = unlocked.app.state.app.works.get(wid)
    text = (work.folder / '장소' / '카페 노을.md').read_text(encoding='utf-8')
    found = agent.proposals(work, f'<<<file path="장소/카페 노을.md">>>\n{text}<<<end>>>', seen={})
    assert found[0]['warnings'] == ['not_in_context']
