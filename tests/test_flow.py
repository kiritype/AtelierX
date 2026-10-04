import time


def test_first_run_and_lock(client):
    assert client.get('/api/auth/status').json()['initialized'] is False
    assert client.get('/api/works').status_code == 401
    client.post('/api/auth/setup', json={'password': 'pass1234'})
    assert client.get('/api/works').status_code == 200
    client.post('/api/auth/lock')
    assert client.get('/api/works').status_code == 401
    assert client.post('/api/auth/unlock', json={'password': 'wrong'}).status_code == 401
    assert client.post('/api/auth/unlock', json={'password': 'pass1234'}).status_code == 200
    assert client.get('/api/works').status_code == 200


def test_other_origin_is_rejected(unlocked):
    assert unlocked.get('/api/works', headers={'origin': 'http://evil.example'}).status_code == 403


def test_defaults_copied(unlocked, paths):
    assert (paths.data / 'guidelines' / 'compression.md').is_file()
    assert (paths.data / 'image' / 'compose.json').is_file()
    assert (paths.data / 'tags' / 'danbooru.csv').is_file()


def test_work_and_items(unlocked):
    c = unlocked
    card = c.post('/api/works', json={'name': '테스트', 'scale': 'single'}).json()
    wid = card['id']
    assert wid == 'W001'
    c.post(f'/api/works/{wid}/folder', json={'path': '인물'})
    item = c.post(f'/api/works/{wid}/file', json={'path': '인물/하나'}).json()
    assert item['path'] == '인물/하나.md' and item['kind'] == 'lorebook'
    saved = c.put(
        f'/api/works/{wid}/file?path=인물/하나.md',
        json={
            'meta': {'id': 'C001', 'kind': 'character', 'keywords': ['하나', '언니, 동생']},
            'body': '## 식별\n하나.\n## 외모\n긴 머리\n',
            'base_hash': item['hash'],
        },
    ).json()
    assert saved['meta']['keywords'] == ['하나', '언니, 동생']
    assert saved['kind'] == 'character'
    stale = c.put(f'/api/works/{wid}/file?path=인물/하나.md', json={'body': 'x', 'base_hash': item['hash']})
    assert stale.status_code == 409
    tree = c.get(f'/api/works/{wid}/tree').json()
    assert tree[0]['name'] == '인물' and tree[0]['children'][0]['id'] == 'C001'
    assert c.get(f'/api/works/{wid}/suggest-id?kind=character').json()['id'] == 'C002'
    moved = c.post(f'/api/works/{wid}/move', json={'from': '인물/하나.md', 'to': '하나.md'}).json()
    assert moved['path'] == '하나.md'
    issues = c.get(f'/api/works/{wid}/check').json()
    assert any(i['message']['key'] == 'check.main_count' for i in issues)
    c.delete(f'/api/works/{wid}/file?path=하나.md')
    trash = c.get(f'/api/works/{wid}/trash').json()
    assert trash[0]['ids'] == ['C001']
    c.post(f'/api/works/{wid}/trash/{trash[0]["id"]}/restore')
    assert c.get(f'/api/works/{wid}/file?path=하나.md').status_code == 200


def test_bad_paths_rejected(unlocked):
    wid = unlocked.post('/api/works', json={'name': 'A'}).json()['id']
    assert unlocked.post(f'/api/works/{wid}/file', json={'path': '../x'}).status_code == 400
    assert unlocked.post(f'/api/works/{wid}/file', json={'path': '.atelierx/x'}).status_code == 400


def test_sample_snapshot_export(unlocked, tmp_path):
    c = unlocked
    card = c.post('/api/samples/simulation/install').json()
    wid = card['id']
    snaps = c.get(f'/api/works/{wid}/snapshots').json()
    assert snaps[0]['reason'] == 'import'
    preview = c.get(f'/api/works/{wid}/export/preview').json()
    assert 'UI/StatusPanel.jsx' in preview['include']
    job = c.post(f'/api/works/{wid}/export', json={'target': str(tmp_path / 'out')}).json()
    for _ in range(50):
        status = next(j for j in c.get('/api/jobs').json() if j['id'] == job['id'])['status']
        if status in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert status == 'done'
    out = (tmp_path / 'out' / 'UI' / 'StatusPanel.jsx').read_text(encoding='utf-8')
    assert not out.startswith('/*---')
    table = (tmp_path / 'out' / '_keywords.md').read_text(encoding='utf-8')
    assert table.startswith('| 경로 | ID | 이름 |')
    assert '| 인물/리나.md |' in table


def test_sample_hashes_refreshed(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    design = c.get(f'/api/works/{wid}/image/characters/C001').json()
    assert set(design['status'].values()) == {'fresh'}


def test_chat_preview_activation(unlocked):
    c = unlocked
    wid = c.post('/api/samples/ensemble/install').json()['id']
    ctx = c.post(
        f'/api/works/{wid}/chat/preview', json={'history': [], 'message': '농구부는 언제 연습해?'}
    ).json()
    assert 'L002' in [p['id'] for p in ctx['picked']]


def test_compress_mock_flow(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    job = c.post(f'/api/works/{wid}/compress', json={'path': '인물/윤하람.md'}).json()
    for _ in range(100):
        j = next(j for j in c.get('/api/jobs').json() if j['id'] == job['id'])
        if j['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert j['status'] == 'done', j
    draft = c.get(f'/api/works/{wid}/drafts/{j["result"]["draft"]}').json()
    assert len(draft['candidates']) == 2 and draft['blocks']
    text = '\n\n'.join(b['text'] for b in draft['candidates'][0]['blocks'])
    result = c.post(
        f'/api/works/{wid}/drafts/{draft["id"]}/apply', json={'text': text, 'mode': 'new_file'}
    ).json()
    assert result['path'].endswith('(압축).md')


def test_compress_run_mock_override_does_not_change_saved_task_connection(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    providers = c.get('/api/providers').json()
    providers['providers']['remote'] = {
        'name': 'Remote', 'type': 'openai_compatible', 'base_url': 'https://llm.example.com/v1',
        'default_model': 'remote-model',
    }
    providers['tasks']['compression'] = {'provider': 'remote', 'model': 'saved-model'}
    c.put('/api/providers', json=providers)

    response = c.post(
        f'/api/works/{wid}/compress',
        json={'path': '인물/윤하람.md', 'llm': {'provider': 'local'}},
    )
    assert response.status_code == 200
    for _ in range(100):
        job = next(j for j in c.get('/api/jobs').json() if j['id'] == response.json()['id'])
        if job['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert job['status'] == 'done', job
    task = c.get('/api/providers').json()['tasks']['compression']
    assert task == {'provider': 'remote', 'model': 'saved-model'}


def test_relations_glossary_and_test_reply(unlocked):
    c = unlocked
    wid = c.post('/api/samples/ensemble/install').json()['id']
    rel = c.get(f'/api/works/{wid}/relations').json()
    ids = [p['id'] for p in rel['view']]
    assert ids[0] == '{{user}}' and 'C001' in ids and 'N01' in ids
    rel['relations'].append({'from': 'C001', 'to': 'X99', 'kind': '?'})
    rel['layout'] = {'C001': {'x': 10, 'y': 20}}
    saved = c.put(f'/api/works/{wid}/relations', json=rel).json()
    assert saved['layout']['C001'] == {'x': 10, 'y': 20}
    keys = [i['message']['key'] for i in c.get(f'/api/works/{wid}/check').json()]
    assert 'check.relation_missing_person' in keys
    glossary = c.get(f'/api/works/{wid}/glossary').json()
    assert glossary['terms'][0]['use'] == '청원고'

    sim = c.post('/api/samples/simulation/install').json()['id']
    with c.stream('POST', f'/api/works/{sim}/chat/send', json={'history': [], 'message': '안녕'}) as response:
        text = ''.join(response.iter_text())
    assert 'event: context' in text and '(모의' in text and 'event: error' not in text


def test_jsx_props_and_checks(unlocked):
    c = unlocked
    wid = c.post('/api/samples/simulation/install').json()['id']
    props = c.get(f'/api/works/{wid}/jsx/J001/props').json()
    assert {p['name'] for p in props} == {'basic', 'late'}
    bad = c.put(f'/api/works/{wid}/jsx/J001/props/x', content='{"a": ')
    assert bad.status_code == 400 and bad.json()['error']['key'] == 'server.jsx.bad_json'
    saved = c.put(f'/api/works/{wid}/jsx/J001/props/empty', content='{}').json()
    assert 'empty' in [p['name'] for p in saved]
    assert 'empty' not in [p['name'] for p in c.delete(f'/api/works/{wid}/jsx/J001/props/empty').json()]
    assert c.put(f'/api/works/{wid}/jsx/J001/props/a.b', content='{}').status_code == 400

    item = c.get(f'/api/works/{wid}/file', params={'path': 'UI/StatusPanel.jsx'}).json()
    body = 'import x from "y";\n' + item['body'].replace(
        'const data', 'const [n] = useReducer(f, 0);\n  const data'
    )
    c.put(
        f'/api/works/{wid}/file',
        params={'path': 'UI/StatusPanel.jsx'},
        json={'meta': {}, 'body': body, 'base_hash': item['hash']},
    )
    keys = {
        i['message']['key']
        for i in c.get(f'/api/works/{wid}/check').json()
        if i['path'] == 'UI/StatusPanel.jsx'
    }
    assert {'check.jsx_forbidden', 'check.jsx_hook'} <= keys


def test_authoring_skeleton(unlocked):
    import time

    c = unlocked
    wid = c.post('/api/works', json={'name': '빈 작품', 'scale': 'ensemble'}).json()['id']
    qs = c.get(f'/api/works/{wid}/authoring/questions').json()
    assert qs['scale'] == 'ensemble' and len(qs['questions']) >= 5
    answers = [{'question': q, 'answer': ''} for q in qs['questions']]
    answers[1]['answer'] = '하린, 17살 반장\n준, 농구부'
    job = c.post(f'/api/works/{wid}/authoring', json={'answers': answers}).json()
    for _ in range(50):
        status = next(j for j in c.get('/api/jobs').json() if j['id'] == job['id'])
        if status['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    draft = c.get(f'/api/works/{wid}/drafts/{status["result"]["draft"]}').json()
    files = draft['candidates'][0]['files']
    assert {'인물/하린.md', '인물/준.md', '메인.md'} <= {f['path'] for f in files}
    chosen = [f for f in files if f['path'] != '세계관/배경.md']
    result = c.post(
        f'/api/works/{wid}/drafts/{draft["id"]}/apply',
        json={'files': chosen, 'relations': draft['candidates'][0]['relations']},
    ).json()
    assert '인물/하린.md' in result['created'] and result['relations_added'] >= 2
    again = c.post(
        f'/api/works/{wid}/drafts/{draft["id"]}/apply', json={'files': chosen[:1], 'relations': []}
    ).json()
    assert again['skipped'][0]['why'] == 'exists'
    item = c.get(f'/api/works/{wid}/file', params={'path': '인물/하린.md'}).json()
    assert item['kind'] == 'character' and item['meta']['keywords'] == ['하린']


def _wait_job(c, job):
    import time

    for _ in range(80):
        status = next(j for j in c.get('/api/jobs').json() if j['id'] == job['id'])
        if status['status'] in ('done', 'failed'):
            return status
        time.sleep(0.05)
    raise AssertionError('job did not finish')


def test_relations_extract_and_consistency(unlocked):
    c = unlocked
    wid = c.post('/api/samples/ensemble/install').json()['id']
    done = _wait_job(c, c.post(f'/api/works/{wid}/relations/extract', json={}).json())
    draft = c.get(f'/api/works/{wid}/drafts/{done["result"]["draft"]}').json()
    rows = draft['candidates'][0]['rows']
    assert rows and rows[0]['type'] == 'relation' and rows[0]['to'] == '{{user}}'
    applied = c.post(f'/api/works/{wid}/drafts/{draft["id"]}/apply', json={'rows': rows}).json()
    assert applied['added'] == len(rows)

    done = _wait_job(c, c.post(f'/api/works/{wid}/consistency', json={}).json())
    draft = c.get(f'/api/works/{wid}/drafts/{done["result"]["draft"]}').json()
    issue = draft['candidates'][0]['issues'][0]
    assert issue['verified'] and issue['status'] == 'open'
    result = c.post(
        f'/api/works/{wid}/drafts/{draft["id"]}/issues/0', json={'action': 'ignore', 'note': '의도'}
    ).json()
    assert result['status'] == 'ignored'
    again = _wait_job(c, c.post(f'/api/works/{wid}/consistency', json={}).json())
    folded = c.get(f'/api/works/{wid}/drafts/{again["result"]["draft"]}').json()['candidates'][0]['issues'][0]
    assert folded['status'] == 'ignored'


def test_jsx_prompt_text_usages_and_insert(unlocked):
    c = unlocked
    wid = c.post('/api/samples/simulation/install').json()['id']
    usages = c.get(f'/api/works/{wid}/jsx/J001/usages').json()
    assert usages and usages[0]['elements']
    done = _wait_job(
        c, c.post(f'/api/works/{wid}/jsx/J001/prompt-text', json={'props': {'data': {'day': 3}}}).json()
    )
    draft = c.get(f'/api/works/{wid}/drafts/{done["result"]["draft"]}').json()
    text = draft['candidates'][0]['text']
    assert draft['candidates'][0]['elements'][0]['attrs'] == {'data': {'day': 3}}
    out = c.post(
        f'/api/works/{wid}/drafts/{draft["id"]}/apply', json={'text': text, 'new_path': '규칙/상태창 문구.md'}
    ).json()
    assert out['path'] == '규칙/상태창 문구.md'
    item = c.get(f'/api/works/{wid}/file', params={'path': out['path']}).json()
    assert '<StatusPanel' in item['body']
    broken = c.post(
        f'/api/works/{wid}/jsx/elements',
        json={'text': '<StatusPanel data=\'{"a": x}\' />', 'name': 'StatusPanel'},
    ).json()
    assert broken[0]['errors']


def test_rename_text(unlocked):
    c = unlocked
    wid = c.post('/api/samples/ensemble/install').json()['id']
    hits = c.post(f'/api/works/{wid}/rename-text/preview', json={'find': '서윤', 'replace': '서아'}).json()
    wheres = {h['where'] for h in hits}
    assert {'body', 'keyword', 'relation'} <= wheres
    risky = [h for h in hits if h['josa']]
    assert risky, 'final consonant changes (윤 → 아) should flag particles'
    keep = [h['id'] for h in hits if h['where'] != 'relation']
    result = c.post(
        f'/api/works/{wid}/rename-text', json={'find': '서윤', 'replace': '서아', 'hits': keep}
    ).json()
    assert result['changed'] and not result['relations']
    left = c.post(f'/api/works/{wid}/rename-text/preview', json={'find': '서윤', 'replace': '서아'}).json()
    assert {h['where'] for h in left} == {'relation'}
    file_hits = c.post(
        f'/api/works/{wid}/rename-text/preview',
        json={'find': '한서윤', 'replace': '한서연', 'targets': ['filename']},
    ).json()
    assert file_hits and file_hits[0]['after'].endswith('한서연.md')


def test_external_consent_and_usage(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    providers = c.get('/api/providers').json()
    providers['providers']['remote'] = {
        'name': '외부',
        'type': 'openai_compatible',
        'base_url': 'https://llm.example.com/v1',
        'default_model': 'm',
    }
    providers['tasks'] = {'compression': {'provider': 'remote'}}
    c.put('/api/providers', json=providers)
    blocked = c.post(f'/api/works/{wid}/compress', json={'path': '메인.md'})
    assert blocked.status_code == 428
    error = blocked.json()['error']
    assert error['key'] == 'server.llm.consent_needed' and error['values']['provider'] == 'remote'
    # A local connection never asks.
    assert c.post(f'/api/works/{wid}/authoring', json={'answers': []}).status_code == 200
    c.patch(f'/api/works/{wid}', json={'llm_consent': ['remote']})
    providers['providers']['remote']['type'] = 'mock'  # consent passes; keep the job offline
    c.put('/api/providers', json=providers)
    assert c.post(f'/api/works/{wid}/compress', json={'path': '메인.md'}).status_code == 200
    assert c.get('/api/usage').json()['rows'] == []


def test_save_points_prune_and_export_leftovers(unlocked, tmp_path):
    from datetime import datetime, timedelta

    from atelierx.core.snapshots import Snapshots
    from atelierx.core.works import Work

    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    item = c.get(f'/api/works/{wid}/file', params={'path': '메인.md'}).json()
    c.put(
        f'/api/works/{wid}/file',
        params={'path': '메인.md'},
        json={'body': item['body'] + '\n추가', 'base_hash': item['hash']},
    )
    reasons = [s['reason'] for s in c.get(f'/api/works/{wid}/snapshots').json()]
    assert reasons[0] == 'save'
    c.post(f'/api/works/{wid}/snapshots/save-point')  # nothing changed since: no new snapshot
    assert len(c.get(f'/api/works/{wid}/snapshots').json()) == len(reasons)

    folder = next(p for p in (tmp_path / 'data' / 'works').iterdir() if p.is_dir())
    snaps = Snapshots(Work(folder))
    old = (datetime.now().astimezone() - timedelta(days=40)).isoformat(timespec='seconds')
    for n in range(3):
        made = snaps.create('save', force=True)
        path = snaps.root / 'snapshots' / f'{made["id"]}.json'
        doc = snaps.get(made['id'])
        doc['created_at'] = old
        path.write_text(
            __import__('json').dumps({k: v for k, v in doc.items() if k != 'id'}), encoding='utf-8'
        )
    assert snaps.prune(keep_recent=1, daily_days=30) >= 2
    assert all(s.get('parent') in {x['id'] for x in snaps.list()} | {None} for s in snaps.list())

    target = tmp_path / 'out'
    (target / '옛').mkdir(parents=True)
    (target / '옛' / '지운 항목.md').write_text('x', encoding='utf-8')
    state = c.get(f'/api/works/{wid}/export/preview', params={'target': str(target)}).json()['target']
    assert state['exists'] and state['leftovers'] == ['옛/지운 항목.md']
