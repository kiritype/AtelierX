import json
import time

from atelierx.core.editor_tasks import preserves_protected


def _finished_job(client, job_id):
    for _ in range(100):
        job = next(j for j in client.get('/api/jobs').json() if j['id'] == job_id)
        if job['status'] in ('done', 'failed'):
            return job
        time.sleep(0.02)
    raise AssertionError('editor job did not finish')


def _make_work(client):
    wid = client.post('/api/works', json={'name': 'Editor test'}).json()['id']
    paths = ('메인.md', '인물.md')
    for path, kind, ident, text in (
        (paths[0], 'main', 'M001', 'Hello {{user}}.\n\n<StatusPanel value="x" />'),
        (paths[1], 'character', 'C001', 'A character with a clear age.'),
    ):
        client.post(f'/api/works/{wid}/file', json={'path': path, 'kind': kind})
        initial = client.get(f'/api/works/{wid}/file', params={'path': path}).json()
        client.put(f'/api/works/{wid}/file', params={'path': path}, json={
            'meta': {'id': ident}, 'body': text, 'base_hash': initial['hash'],
        })
    return wid, paths


def _install_fake_connection(client, monkeypatch):
    providers = client.get('/api/providers').json()
    providers['providers']['fake'] = {
        'name': 'Fake local', 'type': 'openai_compatible', 'base_url': 'http://localhost:1234/v1',
        'default_model': 'fake-model', 'trusted': True,
    }
    providers['tasks']['consistency'] = {'provider': 'fake'}
    providers['tasks']['compression'] = {'provider': 'fake'}
    client.put('/api/providers', json=providers)
    llm = client.app.state.app.llm
    calls = []

    async def complete(task, messages, **kwargs):
        calls.append((task, messages))
        if task == 'compression':
            text = json.dumps({'text': 'Hello {{user}}.\n\n<StatusPanel value="x" />', 'note': 'tidy'})
        else:
            text = json.dumps({'issues': [{'reason': 'age differs', 'evidence': 'age is 17', 'path': '인물.md'}]})
        return {'text': text, 'provider': 'fake', 'model': 'fake-model', 'usage': None}

    monkeypatch.setattr(llm, 'complete', complete)
    return calls


def test_editor_review_and_explicit_consistency_use_json_llm(unlocked, monkeypatch):
    client = unlocked
    wid, paths = _make_work(client)
    calls = _install_fake_connection(client, monkeypatch)

    response = client.post(f'/api/works/{wid}/editor/content-review', json={'path': paths[0], 'instruction': 'Focus on clarity.'})
    assert response.status_code == 200
    job = _finished_job(client, response.json()['id'])
    assert job['status'] == 'done'
    draft = client.get(f'/api/works/{wid}/drafts/{job["result"]["draft"]}').json()
    assert draft['kind'] == 'content_review'
    assert draft['target']['base_hash']
    assert draft['request']['original'].startswith('Hello')
    assert draft['candidates'][0]['issues'][0]['reason'] == 'age differs'
    assert calls[0][0] == 'consistency'
    assert 'Focus on clarity.' in calls[0][1][1]['content']
    assert client.post(f'/api/works/{wid}/drafts/{draft["id"]}/apply', json={}).status_code == 400

    missing = client.post(f'/api/works/{wid}/editor/consistency', json={})
    assert missing.status_code == 400
    compared = client.post(f'/api/works/{wid}/editor/consistency', json={'compare_paths': list(paths)})
    result = _finished_job(client, compared.json()['id'])
    comparison = client.get(f'/api/works/{wid}/drafts/{result["result"]["draft"]}').json()
    assert comparison['target']['paths'] == list(paths)
    assert calls[-1][1][1]['content'].count('경로:') == 2


def test_format_preserves_syntax_and_rejects_stale_or_review_apply(unlocked, monkeypatch):
    client = unlocked
    wid, paths = _make_work(client)
    calls = _install_fake_connection(client, monkeypatch)
    original = client.get(f'/api/works/{wid}/file', params={'path': paths[0]}).json()
    response = client.post(f'/api/works/{wid}/editor/format', json={'path': paths[0], 'mode': 'tidy'})
    job = _finished_job(client, response.json()['id'])
    draft_id = job['result']['draft']
    draft = client.get(f'/api/works/{wid}/drafts/{draft_id}').json()
    assert draft['kind'] == 'text_edit'
    assert preserves_protected(original['body'], draft['candidates'][0]['text'])
    assert calls[0][0] == 'compression'
    assert '편집자' in calls[0][1][0]['content']

    changed = original['body'] + '\nnew line'
    client.put(f'/api/works/{wid}/file', params={'path': paths[0]}, json={
        'meta': None, 'body': changed, 'base_hash': original['hash'],
    })
    stale = client.post(f'/api/works/{wid}/editor-drafts/{draft_id}/apply', json={'candidate': 0})
    assert stale.status_code == 409
    readonly = client.post(f'/api/works/{wid}/editor-drafts/{draft_id}/apply', json={'candidate': 0})
    assert readonly.status_code == 409

    latest = client.get(f'/api/works/{wid}/file', params={'path': paths[0]}).json()
    applied_job = _finished_job(client, client.post(
        f'/api/works/{wid}/editor/format', json={'path': paths[0], 'mode': 'tidy'}
    ).json()['id'])
    applied = client.post(
        f'/api/works/{wid}/drafts/{applied_job["result"]["draft"]}/apply', json={'candidate': 0}
    )
    assert applied.status_code == 200
    assert client.get(f'/api/works/{wid}/file', params={'path': paths[0]}).json()['meta']['id'] == latest['meta']['id']


def test_format_syntax_guard():
    assert preserves_protected('Hi {{user}} <StatusPanel />', '<StatusPanel /> Hi {{user}}')
    assert not preserves_protected('Hi {{user}} <StatusPanel />', 'Hi <StatusPanel />')
    assert not preserves_protected('<StatusPanel />', '<StatusPanel title="changed" />')
