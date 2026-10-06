"""PixAI (#43): a job becomes a task that is checked and fetched, and a sent task is never paid for twice."""

import io
import json

import httpx
from PIL import Image

from atelierx.image.internet import pixai

TARGET = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
TSUBAKI = '1983308862240288769'
HARUKA = '1861558740588989558'


def _png():
    buffer = io.BytesIO()
    Image.new('RGB', (40, 60), (30, 160, 120)).save(buffer, format='PNG')
    return buffer.getvalue()


class PixAI:
    """Answers like PixAI's API: tasks finish after ``checks`` status checks; ``media`` answers the download."""

    def __init__(self, checks=1, final='completed', media=None):
        self.checks, self.final, self.media = checks, final, media
        self.created, self.status_checks, self.downloads = [], 0, 0

    def __call__(self, request):
        path = request.url.path
        if request.method == 'POST' and path == '/v2/image/create':
            self.created.append(json.loads(request.content))
            return httpx.Response(
                200, json={'id': f't{len(self.created)}', 'status': 'waiting', 'outputs': {}}
            )
        if path.startswith('/v1/task/'):
            self.status_checks += 1
            if self.status_checks <= self.checks:
                return httpx.Response(200, json={'id': path.rsplit('/', 1)[1], 'status': 'running'})
            outputs = (
                {'mediaIds': ['m1'], 'mediaUrls': ['https://cdn/m1']} if self.final == 'completed' else {}
            )
            return httpx.Response(
                200, json={'id': path.rsplit('/', 1)[1], 'status': self.final, 'outputs': outputs}
            )
        if path == '/v1/media/m1/image':
            self.downloads += 1
            return self.media(request) if self.media else httpx.Response(200, content=_png())
        raise AssertionError(path)


def _setup(c, server, monkeypatch, loras=None):
    monkeypatch.setattr(pixai, 'POLL_EVERY', 0)
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.set_paused(True)
    c.post('/api/vault', json={'name': 'image-pixai', 'kind': 'api_key', 'value': 'pixai-test-key'})
    saved = c.put(
        '/api/image/services',
        json={'services': {'pixai': {'key': 'secret:image-pixai', 'interval': 0, 'loras': loras or []}}},
    )
    assert saved.status_code == 200, saved.json()
    runtime.services['pixai'].transport = httpx.MockTransport(server)
    return wid, runtime


def _run(c, wid, runtime, settings=None, **extra):
    body = {'service': 'pixai', 'targets': [TARGET], 'settings': settings or {}, 'repeat_ok': True, **extra}
    assert c.post(f'/api/works/{wid}/image/jobs', json=body).status_code == 200
    job = runtime.jobs[-1]
    job['status'] = 'running'
    runtime.run_job(job)
    return job


def test_a_job_becomes_a_task_that_is_checked_and_fetched(unlocked, monkeypatch):
    c = unlocked
    server = PixAI(checks=2)
    lora = {'id': '1700000000000000001', 'name': '빛', 'weight': 0.6, 'trigger_words': 'soft glow'}
    wid, runtime = _setup(c, server, monkeypatch, loras=[lora])
    settings = {'model': HARUKA, 'loras': [{'id': lora['id'], 'weight': 0.5, 'trigger_words': 'soft glow'}]}
    job = _run(c, wid, runtime, settings)
    assert job['status'] == 'done', job.get('error')
    assert job['prompt_id'] == 't1' and server.status_checks == 3 and server.downloads == 1

    body = server.created[0]
    assert body['modelVersionId'] == HARUKA and body['prompt'] == job['snapshot']['positive']
    assert body['negativePrompt'] == job['snapshot']['negative'] and body['batchSize'] == 1
    assert body['promptHelper'] == 'disable' and body['aspectRatio'] == '2:3' and body['size'] == '1k'
    assert body['sampling'] == {'method': 'Euler a', 'steps': 25, 'cfgScale': 6.0} and 'mode' not in body
    assert body['loras'] == [{'modelId': lora['id'], 'weight': 0.5, 'triggerWords': 'soft glow'}]
    assert 0 <= body['seed'] < 2**31

    record = runtime.gallery.metadata(job['image_url'].removeprefix('/api/image/files/'))
    assert record['service'] == 'pixai' and record['workflow']['modelVersionId'] == HARUKA

    info = c.get('/api/image/services/pixai/info').json()
    assert info['loras'][0]['name'] == '빛' and info['max_loras'] == 5
    assert [m['name'] for m in info['models']] == ['Haruka v2', 'Hoshino v2', 'Tsubaki.2']


def test_tsubaki_takes_a_mode_and_no_sampling(unlocked, monkeypatch):
    c = unlocked
    server = PixAI(checks=0)
    wid, runtime = _setup(c, server, monkeypatch)
    _run(c, wid, runtime, {'model': TSUBAKI, 'mode': 'pro'})
    assert server.created[0]['mode'] == 'pro' and 'sampling' not in server.created[0]


def test_settings_and_lora_lists_are_checked(unlocked, monkeypatch):
    c = unlocked
    wid, runtime = _setup(c, PixAI(), monkeypatch)
    nai = runtime.services['pixai']
    six = [{'id': str(1700000000000000000 + n)} for n in range(6)]
    for bad in ({'loras': six}, {'loras': [{'id': 'abc'}]}, {'model': 'tsubaki'}):
        refused = c.post(
            f'/api/works/{wid}/image/jobs', json={'service': 'pixai', 'targets': [TARGET], 'settings': bad}
        )
        assert refused.status_code == 400, bad
    assert nai.validate_settings({})['model'] == HARUKA
    refused = c.put('/api/image/services', json={'services': {'pixai': {'loras': [{'id': 'pixai.art/x'}]}}})
    assert refused.status_code == 400 and refused.json()['error']['key'] == 'server.image.services.lora'


def test_a_failed_task_fails_the_job(unlocked, monkeypatch):
    c = unlocked
    wid, runtime = _setup(c, PixAI(checks=0, final='failed'), monkeypatch)
    job = _run(c, wid, runtime)
    assert job['status'] == 'failed' and job['error'].key == 'server.pixai.task_failed'
    assert 'resume' not in job


def test_a_failed_download_is_retried_without_a_new_task(unlocked, monkeypatch):
    c = unlocked
    answers = [httpx.Response(500, text='busy'), httpx.Response(200, content=_png())]
    server = PixAI(checks=0, media=lambda request: answers.pop(0))
    wid, runtime = _setup(c, server, monkeypatch)
    job = _run(c, wid, runtime)
    assert job['status'] == 'failed' and job['error'].key == 'server.pixai.download_failed'
    assert job['resume'] == 't1'

    runtime.retry(job['id'])
    again = runtime.jobs[-1]
    assert again['resume'] == 't1'
    again['status'] = 'running'
    runtime.run_job(again)
    assert again['status'] == 'done' and len(server.created) == 1 and server.downloads == 2


def test_an_expired_result_says_so_and_is_not_resumed(unlocked, monkeypatch):
    c = unlocked
    wid, runtime = _setup(c, PixAI(checks=0, media=lambda request: httpx.Response(404)), monkeypatch)
    job = _run(c, wid, runtime)
    assert job['error'].key == 'server.pixai.expired' and 'resume' not in job


def test_after_a_restart_the_sent_task_is_fetched_not_sent_again(unlocked, monkeypatch):
    c = unlocked
    server = PixAI(checks=0)
    wid, runtime = _setup(c, server, monkeypatch)
    c.post(f'/api/works/{wid}/image/jobs', json={'service': 'pixai', 'targets': [TARGET], 'count': 2})
    sent, unsent = runtime.jobs[-2:]
    sent.update(status='running', prompt_id='t9')
    runtime.persist()

    runtime.jobs = []
    runtime.load_queue()
    runtime._resume_sent_jobs()
    sent, unsent = runtime.jobs[-2:]
    assert sent['status'] == 'queued' and sent['resume'] == 't9' and unsent['status'] == 'queued'
    sent['status'] = 'running'
    runtime.run_job(sent)
    assert sent['status'] == 'done' and server.created == []


def test_an_image_arriving_after_a_cancel_is_kept(unlocked, monkeypatch):
    c = unlocked
    holder = {}
    server = PixAI(checks=1)
    original = server.__call__

    def answer(request):
        if request.method == 'POST':
            holder['job']['status'] = 'cancelling'
        return original(request)

    wid, runtime = _setup(c, answer, monkeypatch)
    c.post(f'/api/works/{wid}/image/jobs', json={'service': 'pixai', 'targets': [TARGET]})
    holder['job'] = job = runtime.jobs[-1]
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done' and job['image_url']
