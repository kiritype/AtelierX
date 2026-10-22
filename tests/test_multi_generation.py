import copy

import pytest

from atelierx.image.multi import clean_multi, compose_multi
from test_single_generation import _png, _setup

MULTI = {
    'characters': [
        {'id': 'A', 'name': 'A', 'prompt': 'short black hair, blue jacket'},
        {'id': 'B', 'name': 'B', 'prompt': 'long blonde hair, red jacket'},
    ],
    'left_id': 'B',
}


def test_multi_preserves_structure_through_generation_restore_and_retry(unlocked, monkeypatch):
    wid, runtime = _setup(unlocked)
    adapter = runtime.services['comfyui']
    monkeypatch.setattr(adapter, 'busy', lambda: False)
    monkeypatch.setattr(adapter, 'submit', lambda job: {'id': 'fake', 'record': {}})
    monkeypatch.setattr(adapter, 'poll', lambda job, request: {'image': _png()})
    data = {
        'service': 'comfyui',
        'positive': 'gray background',
        'negative': 'duplicate',
        'settings': {'family': 'anima', 'seed': 42},
        'multi': MULTI,
    }
    response = unlocked.post(f'/api/works/{wid}/image/single', json=data)
    assert response.status_code == 200, response.text
    job = runtime.queue.get(response.json()['job_id'])
    assert job['snapshot']['positive'].index('long blonde') < job['snapshot']['positive'].index('short black')
    assert job['snapshot']['request']['multi'] == MULTI
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done'
    run = unlocked.get(f'/api/works/{wid}/image/single/runs').json()['runs'][0]
    assert run['actual']['multi'] == MULTI
    assert run['actual']['scene_positive'] == 'gray background'
    assert run['seed'] == 42
    runtime.remove_finished(job['id'])
    saved = unlocked.get(f'/api/works/{wid}/image/single/runs').json()['runs'][0]
    assert saved['actual']['multi'] == MULTI
    assert runtime.gallery.metadata(saved['path'])['schema_version'] == 3


@pytest.mark.parametrize('service,family', [('novelai', 'anima'), ('pixai', 'sdxl'), ('comfyui', 'sdxl')])
def test_unsupported_multi_service_never_silently_discards_inputs(service, family):
    with pytest.raises(ValueError):
        clean_multi(MULTI, service, family)


def test_two_distinct_people_only_and_no_individual_negative():
    for mutate in [
        lambda x: x['characters'].pop(),
        lambda x: x.update(left_id='missing'),
        lambda x: x['characters'][0].update(negative='red'),
        lambda x: x['characters'][0].update(id='B'),
    ]:
        value = copy.deepcopy(MULTI)
        mutate(value)
        with pytest.raises(ValueError):
            clean_multi(value, 'comfyui', 'anima')
    valid = clean_multi(MULTI, 'comfyui', 'anima')
    assert compose_multi('scene', valid).startswith('Two people. scene. On the left: long blonde')


def test_incompatible_model_is_rejected_before_enqueue(unlocked, monkeypatch):
    wid, runtime = _setup(unlocked)
    catalog = runtime.comfy.catalog()
    catalog['families'] = {'models': {catalog['models'][0]: 'sdxl'}}
    monkeypatch.setattr(runtime, 'catalog', lambda: catalog)
    response = unlocked.post(
        f'/api/works/{wid}/image/single',
        json={'positive': 'scene', 'settings': {'family': 'anima'}, 'multi': MULTI},
    )
    assert response.status_code == 400
    assert response.json()['error']['key'] == 'server.multi.compatibility'
    assert not runtime.queue.jobs


def test_retry_keeps_both_people_layout_and_seed(unlocked):
    wid, runtime = _setup(unlocked)
    response = unlocked.post(
        f'/api/works/{wid}/image/single',
        json={'positive': 'scene', 'settings': {'family': 'anima', 'seed': 73}, 'multi': MULTI},
    )
    old = runtime.queue.get(response.json()['job_id'])
    old['status'] = 'failed'
    response = unlocked.post(f'/api/image/jobs/{old["id"]}/retry', json={})
    assert response.status_code == 200, response.text
    new = runtime.queue.jobs[-1]
    assert new['id'] != old['id'] and new['seed'] == 73
    assert new['snapshot']['multi'] == MULTI
    assert new['snapshot']['positive'] == old['snapshot']['positive']
