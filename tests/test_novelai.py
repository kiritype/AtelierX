"""NovelAI (#42): requests as its API documents them, answers kept as PNG, and paid requests never resent by the app."""

import base64
import io
import json
import zipfile

import httpx
from PIL import Image, PngImagePlugin

from atelierx.image.internet import common

TARGET = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}


def _png(comment='{"steps": 28}'):
    info = PngImagePlugin.PngInfo()
    info.add_text('Comment', comment)
    buffer = io.BytesIO()
    Image.new('RGB', (32, 48), (220, 120, 60)).save(buffer, format='PNG', pnginfo=info)
    return buffer.getvalue()


def _zip(png):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('image_0.png', png)
    return buffer.getvalue()


class Server:
    """Answers like NovelAI; ``replies`` are returned in turn (a callable may also raise)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return reply(request) if callable(reply) else reply


def _setup(c, server, limit=50):
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.set_paused(True)
    c.post('/api/vault', json={'name': 'image-novelai', 'kind': 'api_key', 'value': 'pst-test-token'})
    c.put(
        '/api/image/services',
        json={
            'max_images_per_run': limit,
            'services': {'novelai': {'key': 'secret:image-novelai', 'interval': 0}},
        },
    )
    nai = runtime.services['novelai']
    nai.transport = httpx.MockTransport(server)
    return wid, runtime


def _queue_and_run(c, wid, runtime, settings=None, **extra):
    body = {
        'service': 'novelai',
        'targets': [TARGET],
        'settings': settings or {'model': 'nai-diffusion-5-full'},
        **extra,
    }
    assert c.post(f'/api/works/{wid}/image/jobs', json=body).status_code == 200
    job = runtime.jobs[-1]
    job['status'] = 'running'
    runtime.run_job(job)
    return job


def test_settings_are_checked_and_completed(unlocked):
    nai = unlocked.app.state.app.image.services['novelai']
    settings = nai.validate_settings({'model': 'nai-diffusion-5-full', 'width': 1024, 'height': 1024})
    assert settings['steps'] == 28 and settings['sampler'] == 'k_euler_ancestral' and settings['seed'] == -1
    for bad in ({'width': 1000}, {'model': 'Bad Model!'}, {'steps': 90}):
        try:
            nai.validate_settings(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    info = unlocked.get('/api/image/services/novelai/info').json()
    assert [m['id'] for m in info['models']][:3] == [
        'nai-diffusion-4-5-full',
        'nai-diffusion-4-5-curated',
        'nai-diffusion-5-full',
    ]
    assert info['free'] == {'pixels': 1048576, 'steps': 28}


def test_an_image_is_requested_as_documented_and_saved_with_its_own_metadata(unlocked):
    c = unlocked
    server = Server(
        httpx.Response(200, content=_zip(_png()), headers={'content-type': 'application/x-zip-compressed'})
    )
    wid, runtime = _setup(c, server)
    job = _queue_and_run(c, wid, runtime)
    assert job['status'] == 'completed', job.get('error')

    request = server.requests[0]
    assert str(request.url) == 'https://image.novelai.net/ai/generate-image'
    assert request.headers['authorization'] == 'Bearer pst-test-token'
    body = json.loads(request.content)
    params = body['parameters']
    assert body['model'] == 'nai-diffusion-5-full' and body['action'] == 'generate'
    assert params['seed'] == job['seed'] and params['n_samples'] == 1 and params['width'] == 832
    assert params['v4_prompt']['caption']['base_caption'] == body['input'] == job['snapshot']['positive']
    assert params['v4_negative_prompt']['caption']['base_caption'] == params['negative_prompt']
    assert 'w001_c001' not in body['input']

    saved = runtime.paths.output / job['image_url'].removeprefix('/api/image/files/')
    image = Image.open(saved)
    assert image.text['Comment'] == '{"steps": 28}' and 'prompt' not in image.text
    record = json.loads(saved.with_suffix('.json').read_text(encoding='utf-8'))
    assert record['service'] == 'novelai' and record['workflow']['model'] == 'nai-diffusion-5-full'


def test_a_base64_json_answer_works_too(unlocked):
    c = unlocked
    png = base64.b64encode(_png()).decode()
    wid, runtime = _setup(
        c, Server(httpx.Response(201, json={'images': [{'index': 0, 'seed': 1, 'image': png}]}))
    )
    assert _queue_and_run(c, wid, runtime)['status'] == 'completed'


def test_refusals_fail_the_job_with_the_reason_and_pause_the_queue(unlocked):
    c = unlocked
    server = Server(httpx.Response(401, json={'statusCode': 401, 'message': 'Invalid token'}))
    wid, runtime = _setup(c, server)
    runtime.gpu.generation_allowed = lambda: False  # keep the worker thread away
    runtime.set_paused(False)
    job = _queue_and_run(c, wid, runtime)
    assert job['status'] == 'failed' and job['error'].key == 'server.image.services.bad_key'
    assert runtime.paused is True

    server.replies = [httpx.Response(402, json={'message': 'Not enough Anlas'})]
    job = _queue_and_run(c, wid, runtime, repeat_ok=True)
    assert job['error'].key == 'server.image.services.no_credit' and 'Anlas' in job['error']


def test_busy_refusals_are_retried_but_a_request_without_answer_is_not(unlocked, monkeypatch):
    c = unlocked
    monkeypatch.setattr(common, 'BUSY_WAIT', 0)
    ok = httpx.Response(200, content=_zip(_png()))
    server = Server(httpx.Response(429, json={'message': 'Concurrent generation is locked'}), ok)
    wid, runtime = _setup(c, server)
    job = _queue_and_run(c, wid, runtime)
    assert job['status'] == 'completed' and len(server.requests) == 2

    def no_answer(request):
        raise httpx.ReadTimeout('timed out', request=request)

    server.requests, server.replies = [], [no_answer]
    job = _queue_and_run(c, wid, runtime, repeat_ok=True)
    assert job['status'] == 'failed' and job['error'].key == 'server.image.services.no_answer'
    assert len(server.requests) == 1

    server.requests, server.replies = [], [httpx.Response(429, json={})]
    job = _queue_and_run(c, wid, runtime, repeat_ok=True)
    assert (
        job['error'].key == 'server.image.services.busy'
        and len(server.requests) == 1 + common.RETRIES_WHEN_BUSY
    )


def test_an_image_arriving_after_a_cancel_is_kept(unlocked):
    c = unlocked
    holder = {}

    def answer(request):
        holder['job']['status'] = 'cancelling'  # cancelled while the request was out
        return httpx.Response(200, content=_zip(_png()))

    wid, runtime = _setup(c, Server(answer))
    c.post(f'/api/works/{wid}/image/jobs', json={'service': 'novelai', 'targets': [TARGET]})
    holder['job'] = job = runtime.jobs[-1]
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'completed' and job['image_url']


def test_the_same_request_again_soon_asks_first(unlocked):
    c = unlocked
    wid, _ = _setup(c, Server(httpx.Response(200, content=_zip(_png()))))
    body = {'service': 'novelai', 'targets': [TARGET], 'settings': {'seed': -1}}
    assert c.post(f'/api/works/{wid}/image/jobs', json=body).status_code == 200
    again = c.post(f'/api/works/{wid}/image/jobs', json=body)
    assert again.status_code == 409 and again.json()['error']['key'] == 'server.image.services.repeat'
    assert c.post(f'/api/works/{wid}/image/jobs', json={**body, 'repeat_ok': True}).status_code == 200
    other = {**body, 'settings': {'steps': 20}}
    assert c.post(f'/api/works/{wid}/image/jobs', json=other).status_code == 200


def test_the_account_shows_anlas_left(unlocked):
    c = unlocked
    subscription = {
        'tier': 3,
        'active': True,
        'trainingStepsLeft': {'fixedTrainingStepsLeft': 9000, 'purchasedTrainingSteps': 500},
    }
    server = Server(httpx.Response(200, json=subscription))
    _setup(c, server)
    account = c.get('/api/image/services/novelai/account').json()
    assert account == {'tier': 3, 'active': True, 'anlas': 9500, 'opus': True}
    assert str(server.requests[0].url) == 'https://image.novelai.net/user/subscription'

    c.put('/api/image/services', json={'services': {'novelai': {'key': None}}})
    missing = c.get('/api/image/services/novelai/account')
    assert missing.status_code == 502 and missing.json()['error']['key'] == 'server.image.services.no_key'


def test_regenerating_a_novelai_image_asks_novelai_and_never_automatically(unlocked):
    c = unlocked
    wid, runtime = _setup(c, Server(httpx.Response(200, content=_zip(_png()))))
    job = _queue_and_run(c, wid, runtime)
    relative = job['image_url'].removeprefix('/api/image/files/')
    item = c.get('/api/image/gallery', params={'work': wid}).json()['results'][0]
    assert item['service'] == 'novelai'

    again = c.post('/api/image/gallery/regenerate', json={'items': [relative], 'review': False}).json()
    assert again['count'] == 1
    fresh = runtime.jobs[-1]
    assert fresh['service'] == 'novelai' and fresh['seed'] != job['seed']
    assert fresh['snapshot']['settings']['model'] == 'nai-diffusion-5-full'

    # A failed automatic review does not send a paid request again on its own.
    rounds = runtime.rounds
    round_ = {
        'id': 'r1',
        'status': 'failed_review',
        'regenerations': 0,
        'max_auto_regenerations': 2,
        'attempts': [{'path': relative}],
        'current_job_id': job['id'],
    }
    rounds.rounds.append(round_)
    before = len(runtime.jobs)
    rounds._regenerate_failed([round_])
    assert len(runtime.jobs) == before
    assert round_['status'] == 'needs_attention' and round_['error'].key == 'server.review.no_auto_paid'
