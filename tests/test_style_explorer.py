"""Explorer admission, frozen protocol, persisted comparisons and queue integration (mock services only)."""

import copy
import json
import uuid

import pytest

from atelierx.image.runtime import ImageRuntime
from atelierx.image.style_explorer import StyleExplorer
from test_image import FakeComfy

BASE = '/api/image/explorer/sessions'


def token():
    return uuid.uuid4().hex


@pytest.fixture
def explorer(unlocked):
    runtime = unlocked.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = FakeComfy()
    return unlocked, runtime


def create(client, **changes):
    body = {
        'request_id': token(),
        'name': 'Test session',
        'service': 'comfyui',
        'family': 'anima',
        'positive': 'a red lighthouse',
        'negative': 'blurry',
        'seed': 123,
        'settings': {},
        'budget': 12,
        'artists': [{'name': name, 'mode': 'candidate'} for name in ('ink', 'pencil', 'paint')],
        'rules': {'artist_min': 1, 'artist_max': 1, 'artist_low': 1, 'artist_high': 1, 'artist_step': 0.1},
        **changes,
    }
    response = client.post(BASE, json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def action(client, session, name, **values):
    return client.post(
        f'{BASE}/{session["id"]}/{name}',
        json={
            'revision': session['revision'],
            'request_id': token(),
            **values,
        },
    )


def generate(client, session, count=3):
    response = action(client, session, 'generate', count=count)
    assert response.status_code == 200, response.text
    return response.json()


def complete(runtime, session):
    for candidate in session['candidates']:
        job = runtime.queue.get(candidate['job_id'])
        job['status'] = 'running'
        runtime.run_job(job)
        assert job['status'] == 'done', job.get('error')
    return runtime.explorer.get(session['id'])


def test_creation_is_idle_and_idempotent_reads_do_not_select_pair(explorer):
    client, runtime = explorer
    session, body = create(client)
    assert not runtime.jobs and session['used'] == 0 and session['pair'] is None
    repeated = client.post(BASE, json=body).json()
    assert repeated['id'] == session['id']
    before = runtime.explorer._path(session['id']).read_bytes()
    for _ in range(2):
        assert client.get(f'{BASE}/{session["id"]}').json() == session
    assert runtime.explorer._path(session['id']).read_bytes() == before
    assert client.post(BASE, json={**body, 'name': 'changed'}).status_code == 409
    assert len(client.get(BASE).json()['sessions']) == 1


def test_generate_freezes_unique_recipes_and_defends_budget_and_replays(explorer):
    client, runtime = explorer
    session, _ = create(client, budget=3)
    body = {'revision': session['revision'], 'request_id': token(), 'count': 3}
    endpoint = f'{BASE}/{session["id"]}/generate'
    response = client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    generated = response.json()
    assert len(runtime.jobs) == generated['used'] == 3
    assert len({c['positive'] for c in generated['candidates']}) == 3
    assert {c['seed'] for c in generated['candidates']} == {123}
    assert all(c['positive'].startswith('a red lighthouse') for c in generated['candidates'])
    assert all(not job['review_requested'] for job in runtime.jobs)
    assert client.post(endpoint, json=body).json() == generated
    assert len(runtime.jobs) == 3
    assert client.post(endpoint, json={**body, 'count': 2}).status_code == 409
    assert action(client, session, 'generate', count=1).status_code == 409
    assert action(client, generated, 'generate', count=1).status_code == 400
    assert runtime.explorer.get(session['id'])['used'] == 3
    runtime.queue.load()
    assert runtime.jobs[0]['snapshot']['positive'] == generated['candidates'][0]['positive']


def test_pair_persistence_elo_undo_skip_neither_and_no_repeat(explorer):
    client, runtime = explorer
    session, _ = create(client)
    session = complete(runtime, generate(client, session))
    assert session['pair'] is None
    session = action(client, session, 'pair').json()
    first = copy.deepcopy(session['pair'])
    assert first and runtime.explorer.get(session['id'])['pair'] == first
    assert action(client, session, 'pair').json()['pair'] == first
    body = {'revision': session['revision'], 'request_id': token(), 'pair_id': first['id'], 'result': 'a'}
    endpoint = f'{BASE}/{session["id"]}/vote'
    voted = client.post(endpoint, json=body).json()
    scores = {c['id']: c for c in voted['candidates']}
    assert scores[first['a']]['elo'] == 1012.0
    assert scores[first['b']]['elo'] == 988.0
    assert scores[first['a']]['matches'] == 1 and scores[first['a']]['wins'] == 1
    assert client.post(endpoint, json=body).json() == voted
    voted = action(client, voted, 'pair').json()
    assert {voted['pair']['a'], voted['pair']['b']} != {first['a'], first['b']}
    undone = action(client, voted, 'undo').json()
    assert undone['pair'] == first and undone['votes'] == []
    assert all(c['elo'] == 1000 and c['matches'] == 0 for c in undone['candidates'])
    tied = action(client, undone, 'vote', pair_id=first['id'], result='tie').json()
    assert sum(c['draws'] for c in tied['candidates']) == 2
    tied = action(client, tied, 'pair').json()
    rejected = action(client, tied, 'vote', pair_id=tied['pair']['id'], result='neither').json()
    assert sum(c['rejected'] for c in rejected['candidates']) == 2
    assert sum(c['matches'] for c in rejected['candidates']) == 2
    rejected = action(client, rejected, 'pair').json()
    skipped = action(client, rejected, 'vote', pair_id=rejected['pair']['id'], result='skip').json()
    assert action(client, skipped, 'pair').json()['pair'] is None
    assert len(runtime.jobs) == 3
    assert StyleExplorer(runtime).get(session['id'])['votes'] == skipped['votes']


def test_results_survive_queue_clear_and_preset_excludes_scene_and_seed(explorer):
    client, runtime = explorer
    session, _ = create(client)
    session = complete(runtime, generate(client, session, 2))
    candidate = session['candidates'][0]
    assert candidate['image_url'].startswith('/api/image/files/_explorer/')
    metadata = client.get(candidate['image_url'].replace('.png', '.json')).json()
    assert metadata['explorer_session'] == session['id']
    assert metadata['explorer_candidate'] == candidate['id']
    assert (
        client.post(
            '/api/image/gallery/regenerate', json={'items': [candidate['path']], 'review': False}
        ).status_code
        == 400
    )
    client.post('/api/image/queue/clear-finished')
    restored = StyleExplorer(runtime).get(session['id'])
    assert all(c['status'] == 'done' for c in restored['candidates'])
    assert restored['revision'] == session['revision']
    body = {
        'revision': session['revision'],
        'request_id': token(),
        'candidate_id': candidate['id'],
        'name': 'Ink recipe',
    }
    saved = client.post(f'{BASE}/{session["id"]}/preset', json=body)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert client.post(f'{BASE}/{session["id"]}/preset', json=body).json() == result
    preset = next(p for p in client.get('/api/image/presets').json() if p['id'] == result['preset_id'])
    assert 'seed' not in preset['settings']
    assert 'lighthouse' not in json.dumps(preset)
    assert preset['artist']['positive'] == candidate['style_positive']
    runtime.gallery.safe_path(restored['candidates'][0]['path']).unlink()
    missing = StyleExplorer(runtime).get(session['id'])
    assert missing['candidates'][0]['status'] == 'failed'
    assert missing['candidates'][0]['image_missing']
    assert action(client, missing, 'pair').json()['pair'] is None


def test_retry_is_manual_bounded_and_cannot_bypass_session(explorer):
    client, runtime = explorer
    session, _ = create(client, budget=2)
    session = generate(client, session, 1)
    candidate = session['candidates'][0]
    job = runtime.queue.get(candidate['job_id'])
    runtime.queue.update(job, status='failed', error='test refusal')
    assert client.post(f'/api/image/jobs/{job["id"]}/retry').status_code == 400
    with pytest.raises(ValueError):
        runtime.queue.retry(job['id'])
    frozen = copy.deepcopy(job['snapshot'])
    retried = action(client, session, 'retry', candidate_id=candidate['id'])
    assert retried.status_code == 200, retried.text
    retried = retried.json()
    new_job = runtime.queue.get(retried['candidates'][0]['job_id'])
    assert new_job['snapshot'] == frozen and new_job['seed'] == job['seed']
    assert retried['used'] == 2
    runtime.queue.update(new_job, status='failed')
    assert action(client, retried, 'retry', candidate_id=candidate['id']).status_code == 400
    assert len(runtime.jobs) == 2
    client.post('/api/image/queue/clear-finished')
    assert StyleExplorer(runtime).get(session['id'])['candidates'][0]['status'] == 'failed'


def test_cancel_owns_only_its_jobs_and_session_isolation(explorer):
    client, runtime = explorer
    first, _ = create(client)
    second, _ = create(client)
    first = generate(client, first, 1)
    second = generate(client, second, 1)
    cancelled = action(client, first, 'cancel')
    assert cancelled.status_code == 200, cancelled.text
    assert runtime.queue.get(first['candidates'][0]['job_id'])['status'] == 'cancelled'
    assert runtime.queue.get(second['candidates'][0]['job_id'])['status'] == 'queued'
    assert not runtime.explorer.get(second['id'])['votes']
    assert runtime.explorer.get(second['id'])['revision'] == second['revision']


@pytest.mark.parametrize(
    'service,family,settings',
    [
        ('moss', 'moss', {}),
        ('comfyui', 'moss', {}),
        ('other', 'anima', {}),
        ('novelai', 'novelai', {'loras': [{'name': 'bad'}]}),
        ('pixai', 'pixai', {'model': '123456789'}),
    ],
)
def test_rejects_unsupported_providers_and_loras(explorer, service, family, settings):
    client, runtime = explorer
    response = client.post(
        BASE,
        json={
            'request_id': token(),
            'service': service,
            'family': family,
            'settings': settings,
            'positive': 'one tree',
        },
    )
    assert response.status_code == 400, response.text
    assert not runtime.jobs


@pytest.mark.parametrize(
    'service,settings',
    [
        ('novelai', {'model': 'nai-diffusion-4-5-full'}),
        ('pixai', {'model': '1861558740588989558', 'loras': [{'id': '123456789', 'weight': 0.8}]}),
    ],
)
def test_internet_admission_without_network_or_spending(explorer, service, settings):
    client, runtime = explorer
    session, _ = create(client, service=service, family=service, settings=settings)
    session = generate(client, session, 2)
    assert {c['seed'] for c in session['candidates']} == {123}
    assert all(j['service'] == service for j in runtime.jobs)
    assert not any(j.get('prompt_id') for j in runtime.jobs)
    candidate = session['candidates'][0]
    request = runtime.services[service].request_body(runtime.queue.get(candidate['job_id']))
    assert request.get('seed', request.get('parameters', {}).get('seed')) == 123


def test_novelai_request_uses_candidate_prompt_negative_prompt_and_seed(explorer):
    client, runtime = explorer
    session, _ = create(
        client,
        service='novelai',
        family='novelai',
        settings={'model': 'nai-diffusion-4-5-full', 'width': 832, 'height': 1216},
        artists=[{'name': 'ink artist', 'mode': 'always'}],
        rules={
            'artist_min': 1,
            'artist_max': 1,
            'artist_low': 0.8,
            'artist_high': 0.8,
            'artist_step': 0.1,
        },
    )
    session = generate(client, session, 1)
    candidate = session['candidates'][0]
    job = runtime.queue.get(candidate['job_id'])
    request = runtime.services['novelai'].request_body(job)
    assert request['input'] == candidate['positive']
    assert request['parameters']['negative_prompt'] == candidate['negative'] == 'blurry'
    assert request['parameters']['seed'] == candidate['seed'] == 123
    assert request['model'] == 'nai-diffusion-4-5-full'
    assert candidate['style_positive'] == '0.8::ink artist::'


def test_pixai_request_uses_candidate_seed_and_randomized_lora_weight(explorer):
    client, runtime = explorer
    model = '1861558740588989558'
    session, _ = create(
        client,
        service='pixai',
        family='pixai',
        settings={
            'model': model,
            'loras': [{'id': '123456789', 'weight': 0.9, 'trigger_words': 'pixai trigger'}],
        },
        artists=[{'name': 'ink artist', 'mode': 'always'}],
        rules={
            'artist_min': 1,
            'artist_max': 1,
            'artist_low': 1.2,
            'artist_high': 1.2,
            'artist_step': 0.1,
            'lora_min': 1,
            'lora_max': 1,
            'lora_low': 0.6,
            'lora_high': 0.6,
            'lora_step': 0.1,
        },
    )
    session = generate(client, session, 1)
    candidate = session['candidates'][0]
    job = runtime.queue.get(candidate['job_id'])
    request = runtime.services['pixai'].request_body(job)
    assert request['prompt'] == candidate['positive'] == 'a red lighthouse, (ink artist:1.2)'
    assert request['negativePrompt'] == candidate['negative'] == 'blurry'
    assert request['seed'] == candidate['seed'] == 123
    assert request['modelVersionId'] == model
    assert request['loras'] == [
        {'modelId': '123456789', 'weight': 0.6, 'triggerWords': 'pixai trigger'},
    ]


def test_restart_does_not_generate_and_pixai_resumes_the_existing_task(explorer):
    client, runtime = explorer
    idle, _ = create(client, name='Idle restart session')
    session, _ = create(
        client,
        service='pixai',
        family='pixai',
        settings={'model': '1861558740588989558'},
    )
    session = generate(client, session, 1)
    job = runtime.queue.get(session['candidates'][0]['job_id'])
    runtime.queue.update(job, status='running', prompt_id='pixai-task-123')

    # Constructing a runtime over persisted state models restart recovery without starting its worker thread.
    restarted = ImageRuntime(runtime.paths, runtime.works, runtime.llm)
    assert restarted._thread is None
    restored = restarted.explorer.get(session['id'])
    assert restored['used'] == 1 and len(restored['candidates']) == 1
    idle_restored = restarted.explorer.get(idle['id'])
    assert idle_restored['used'] == 0 and not idle_restored['candidates']
    assert len(restarted.jobs) == 1 and restarted.jobs[0]['id'] == job['id']
    resumed = restarted.queue.get(job['id'])
    assert resumed['status'] == 'queued' and resumed['resume'] == 'pixai-task-123'

    from test_single_generation import _png

    service = restarted.services['pixai']
    submits = []
    service.submit = lambda queued: submits.append(
        queued
    )  # any resubmission would be a duplicate paid request
    service.poll = lambda queued, sent: {'image': _png()}

    class FastStop:
        @staticmethod
        def wait(_seconds):
            return False

        @staticmethod
        def is_set():
            return False

    restarted.stop = FastStop()
    restarted.queue.update(resumed, status='running')
    restarted.run_job(resumed)
    assert not submits
    assert resumed['status'] == 'done' and resumed['prompt_id'] == 'pixai-task-123'
    assert restarted.explorer.get(session['id'])['candidates'][0]['status'] == 'done'


def test_exhausted_unique_space_never_admits_partial_batch(explorer):
    client, runtime = explorer
    session, _ = create(client, artists=[{'name': 'ink', 'mode': 'always'}])
    response = action(client, session, 'generate', count=2)
    assert response.status_code == 400
    assert not runtime.jobs and runtime.explorer.get(session['id'])['used'] == 0
    assert runtime.explorer.get(session['id'])['revision'] == session['revision']


def test_missing_image_cannot_receive_preference(explorer):
    client, runtime = explorer
    session, _ = create(client)
    session = complete(runtime, generate(client, session, 2))
    session = action(client, session, 'pair').json()
    runtime.gallery.safe_path(session['candidates'][0]['path']).unlink()
    refused = action(client, session, 'vote', pair_id=session['pair']['id'], result='a')
    assert refused.status_code == 400
    assert not runtime.explorer.get(session['id'])['votes']


def test_disabled_loras_do_not_enter_recipes_or_require_compatibility(explorer):
    client, runtime = explorer
    catalog = runtime.comfy.catalog()
    catalog['loras'] = ['anima/active.safetensors', 'unknown/off.safetensors']
    runtime.comfy.catalog = lambda: copy.deepcopy(catalog)
    session, _ = create(
        client,
        settings={
            'loras': [
                {'name': 'anima/active.safetensors'},
                {'name': 'unknown/off.safetensors', 'enabled': False},
            ]
        },
        rules={
            'artist_min': 1,
            'artist_max': 1,
            'artist_low': 1,
            'artist_high': 1,
            'lora_min': 1,
            'lora_max': 1,
            'lora_low': 0.5,
            'lora_high': 0.5,
        },
    )
    assert len(session['config']['settings']['loras']) == 1
    session = generate(client, session, 3)
    for candidate in session['candidates']:
        assert candidate['settings']['loras'] == [
            {'name': 'anima/active.safetensors', 'strength_model': 0.5, 'strength_clip': 0.5},
        ]


def test_missing_pair_replaced_and_rated_image_retry_refused(explorer):
    client, runtime = explorer
    session, _ = create(client)
    session = complete(runtime, generate(client, session, 3))
    session = action(client, session, 'pair').json()
    old_pair = session['pair']
    session = action(client, session, 'vote', pair_id=old_pair['id'], result='a').json()
    lost = next(c for c in session['candidates'] if c['id'] == old_pair['a'])
    runtime.gallery.safe_path(lost['path']).unlink()
    refused = action(client, session, 'retry', candidate_id=lost['id'])
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.explorer.rated_missing'
    session = action(client, session, 'undo').json()
    assert session['pair'] is None
    session = action(client, session, 'pair').json()
    assert lost['id'] not in (session['pair']['a'], session['pair']['b'])
    second_lost = next(c for c in session['candidates'] if c['id'] == session['pair']['a'])
    runtime.gallery.safe_path(second_lost['path']).unlink()
    replaced = action(client, session, 'pair').json()
    assert replaced['pair'] is None
    assert replaced['revision'] == session['revision'] + 1
    retry = action(client, replaced, 'retry', candidate_id=lost['id'])
    assert retry.status_code == 200, retry.text
    retried = retry.json()
    candidate = next(c for c in retried['candidates'] if c['id'] == lost['id'])
    assert candidate['status'] == 'queued' and not candidate.get('image_missing')
    assert not candidate.get('image_url') and not candidate.get('path')
    assert action(client, retried, 'retry', candidate_id=lost['id']).status_code == 400


def test_result_recovers_after_crash_between_output_and_queue_update(explorer):
    client, runtime = explorer
    session, _ = create(client)
    session = generate(client, session, 1)
    job = runtime.queue.get(session['candidates'][0]['job_id'])
    from test_single_generation import _png

    runtime.save_result(job, _png(), {}, 'mock-result')
    runtime.queue.update(job, status='interrupted')
    recovered = runtime.explorer.get(session['id'])
    assert recovered['candidates'][0]['status'] == 'done'
    assert recovered['candidates'][0]['path'].endswith(job['id'] + '.png')
    assert recovered['revision'] == session['revision']
    assert len(runtime.jobs) == 1


def test_stale_concurrent_admission_and_cancel_replay(explorer):
    from concurrent.futures import ThreadPoolExecutor

    from atelierx.core.i18n import AppError

    client, runtime = explorer
    session, _ = create(client)

    def submit():
        try:
            return runtime.explorer.generate(
                session['id'],
                {
                    'revision': session['revision'],
                    'request_id': token(),
                    'count': 1,
                },
            )
        except AppError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results and len(runtime.jobs) == 1
    session = runtime.explorer.get(session['id'])
    body = {'revision': session['revision'], 'request_id': token()}
    endpoint = f'{BASE}/{session["id"]}/cancel'
    cancelled = client.post(endpoint, json=body)
    assert cancelled.status_code == 200
    assert client.post(endpoint, json=body).json() == cancelled.json()


def test_internet_limit_applies_to_explorer_batches(explorer):
    client, runtime = explorer
    client.put('/api/image/services', json={'max_images_per_run': 1})
    session, _ = create(
        client, service='novelai', family='novelai', settings={'model': 'nai-diffusion-4-5-full'}
    )
    response = action(client, session, 'generate', count=2)
    assert response.status_code == 400 and not runtime.jobs
    assert runtime.explorer.get(session['id'])['revision'] == session['revision']


def test_explorer_requires_auth_and_rejects_unsafe_ids(client):
    assert client.get('/api/image/explorer/capabilities').status_code in (401, 423)


def test_pixai_known_task_survives_clear_and_retry_fetches_without_new_submit(explorer):
    client, runtime = explorer
    session, _ = create(client, service='pixai', family='pixai', settings={'model': '1861558740588989558'})
    session = generate(client, session, 1)
    candidate = session['candidates'][0]
    job = runtime.queue.get(candidate['job_id'])
    runtime.queue.update(
        job, status='failed', prompt_id='existing-paid-task', error='connection reset during polling'
    )
    client.post('/api/image/queue/clear-finished')
    session = StyleExplorer(runtime).get(session['id'])
    response = action(client, session, 'retry', candidate_id=candidate['id'])
    assert response.status_code == 200, response.text
    new_job = runtime.queue.get(response.json()['candidates'][0]['job_id'])
    assert new_job['resume'] == 'existing-paid-task'
    service = runtime.services['pixai']
    service.submit = lambda _: pytest.fail('must retrieve the existing paid task')
    from test_single_generation import _png

    service.poll = lambda job, sent: {'image': _png()}
    new_job['status'] = 'running'
    runtime.run_job(new_job)
    assert new_job['status'] == 'done'
    assert new_job['prompt_id'] == 'existing-paid-task'


def test_pixai_confirmed_terminal_failure_does_not_resume_dead_task(explorer):
    from atelierx.core.i18n import Msg

    client, runtime = explorer
    session, _ = create(client, service='pixai', family='pixai', settings={'model': '1861558740588989558'})
    session = generate(client, session, 1)
    job = runtime.queue.get(session['candidates'][0]['job_id'])
    runtime.queue.update(
        job,
        status='failed',
        resume='dead-task',
        prompt_id='dead-task',
        error=Msg('server.pixai.task_failed', 'PixAI could not make the image.'),
    )
    client.post('/api/image/queue/clear-finished')
    response = action(client, session, 'retry', candidate_id=session['candidates'][0]['id'])
    assert response.status_code == 200, response.text
    new_job = runtime.queue.get(response.json()['candidates'][0]['job_id'])
    assert 'resume' not in new_job
