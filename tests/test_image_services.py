"""Choosing an image service (#41): settings with vault references, a per-run limit, and jobs that name their service."""

import io

from PIL import Image

from test_image import FakeComfy

TARGET = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}


class InternetService:
    """Stands in for NovelAI: its own settings, no GPU."""

    id = 'novelai'
    local_gpu = False
    wait_limit = result_limit = 60

    def busy(self):
        return False

    def validate_settings(self, settings):
        if settings.get('model') not in (None, 'v4.5', 'v5'):
            raise ValueError('unknown model')
        return {'model': settings.get('model') or 'v4.5', 'width': 832, 'height': 1216, 'seed': -1}

    def submit(self, job):
        return {'id': 'n1', 'record': {'input': job['snapshot']['positive']}}

    def poll(self, job, sent):
        buffer = io.BytesIO()
        Image.new('RGB', (32, 32), (90, 60, 200)).save(buffer, format='PNG')
        return {'image': buffer.getvalue()}

    def cancel(self, job, sent):
        return True


def _setup(c):
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)  # the test runs jobs itself
    runtime.gpu.admit = lambda kind: None
    return wid, runtime


def test_service_settings_keep_vault_references_and_a_limit(unlocked):
    c = unlocked
    _, runtime = _setup(c)
    listed = c.get('/api/image/services').json()
    assert listed['max_images_per_run'] == 50
    assert [(s['id'], s['supported'], s['connected']) for s in listed['services']] == [
        ('novelai', False, False),
        ('pixai', False, False),
    ]

    c.post('/api/vault', json={'name': 'image-novelai', 'kind': 'api_key', 'value': 'pst-test-123'})
    runtime.services['novelai'] = InternetService()
    saved = c.put(
        '/api/image/services',
        json={
            'max_images_per_run': 0,
            'services': {'novelai': {'key': 'secret:image-novelai', 'interval': 5}},
        },
    ).json()
    novelai = saved['services'][0]
    assert saved['max_images_per_run'] == 0
    assert novelai == {
        'id': 'novelai',
        'name': 'NovelAI',
        'key': 'secret:image-novelai',
        'interval': 5.0,
        'supported': True,
        'connected': True,
    }
    assert runtime.service_config.key('novelai') == 'pst-test-123'
    assert 'pst-test-123' not in (runtime.paths.data / 'image' / 'services.json').read_text(encoding='utf-8')

    for body, key in (
        ({'services': {'novelai': {'key': 'pst-plain'}}}, 'server.llm.secret_reference'),
        ({'services': {'midjourney': {}}}, 'server.image.services.unknown'),
        ({'max_images_per_run': -1}, 'server.image.services.limit'),
        ({'services': {'pixai': {'interval': 9999}}}, 'server.image.services.interval'),
    ):
        refused = c.put('/api/image/services', json=body)
        assert refused.status_code == 400 and refused.json()['error']['key'] == key


def test_a_job_for_an_internet_service_is_composed_for_it_and_skips_local_parts(unlocked):
    c = unlocked
    wid, runtime = _setup(c)
    runtime.services['novelai'] = InternetService()
    c.put(
        '/api/image/library/common/nai_quality',
        json={
            'scope': 'global',
            'item': {
                'name': 'NAI',
                'target': 'positive',
                'prompt': ['very aesthetic'],
                'targets': ['novelai'],
            },
        },
    )
    body = {
        'service': 'novelai',
        'targets': [TARGET],
        'settings': {'model': 'v5'},
        'common_ids': ['quality', 'nai_quality'],
    }
    preview = c.post(f'/api/works/{wid}/image/compose', json=body).json()[0]
    assert 'very aesthetic' in preview['positive'] and 'masterpiece' not in preview['positive']

    queued = c.post(f'/api/works/{wid}/image/jobs', json={**body, 'count': 2}).json()
    assert queued['count'] == 2
    job = runtime.jobs[0]
    assert job['service'] == 'novelai' and job['snapshot']['service'] == 'novelai'
    assert job['snapshot']['settings']['model'] == 'v5' and 'loras' not in job['snapshot']['settings']
    assert 'w001_c001' not in job['snapshot']['positive']  # no trigger word without a local LoRA

    # An internet service's job is not on this PC's GPU: a local LLM is not held back by it.
    assert runtime.on_gpu(job) is False
    job['status'] = 'running'
    assert runtime.gpu.try_llm() is True
    runtime.gpu.end_llm()
    runtime.run_job(job)
    assert job['status'] == 'completed' and job['prompt_id'] == 'n1'

    refused = c.post(f'/api/works/{wid}/image/jobs', json={**body, 'settings': {'model': 'v9'}})
    assert refused.status_code == 400
    unknown = c.post(f'/api/works/{wid}/image/jobs', json={**body, 'service': 'pixai'})
    assert unknown.status_code == 400 and unknown.json()['error']['key'] == 'server.worker.unknown_service'


def test_the_per_run_limit_applies_to_internet_services_only(unlocked):
    c = unlocked
    wid, runtime = _setup(c)
    runtime.services['novelai'] = InternetService()
    c.put('/api/image/services', json={'max_images_per_run': 3})
    body = {'service': 'novelai', 'targets': [TARGET], 'count': 4}
    over = c.post(f'/api/works/{wid}/image/jobs', json=body)
    assert over.status_code == 400 and over.json()['error']['key'] == 'server.image.services.over_limit'
    assert over.json()['error']['values'] == {'n': 4, 'limit': 3}
    assert c.post(f'/api/works/{wid}/image/jobs', json={**body, 'count': 3}).json()['count'] == 3
    # The local image server has no such limit.
    assert c.post(f'/api/works/{wid}/image/jobs', json={'targets': [TARGET], 'count': 4}).json()['count'] == 4
    c.put('/api/image/services', json={'max_images_per_run': 0})
    assert c.post(f'/api/works/{wid}/image/jobs', json=body).json()['count'] == 4
