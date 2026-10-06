"""One life cycle for every long-running job (#89): the same names, cancelling until stopped, old files read anew."""

import json
import time

from atelierx.core import lifecycle
from atelierx.image.lora import store


def test_old_names_are_read_as_the_shared_ones():
    assert lifecycle.normalize({'status': 'completed'}) == {'status': 'done'}
    assert lifecycle.normalize({'status': 'training'}) == {'status': 'running', 'phase': 'training'}
    assert lifecycle.normalize({'status': 'waiting_gpu'}) == {'status': 'queued', 'phase': 'waiting_gpu'}
    assert lifecycle.normalize({'status': 'failed'}) == {'status': 'failed'}


def test_a_queue_file_from_before_reads_completed_jobs_as_done(unlocked):
    runtime = unlocked.app.state.app.image
    runtime.queue.path.parent.mkdir(parents=True, exist_ok=True)
    runtime.queue.path.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'paused': False,
                'jobs': [
                    {'id': 'a', 'status': 'completed'},
                    {'id': 'b', 'status': 'running'},
                    {'id': 'c', 'status': 'failed'},
                ],
            }
        ),
        encoding='utf-8',
    )
    runtime.load_queue()
    assert [j['status'] for j in runtime.jobs] == ['done', 'interrupted', 'failed']
    assert runtime.remove_finished()['removed'] == 3


def test_a_training_record_from_before_reads_its_step_as_a_phase(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    work = c.app.state.app.works.get(wid)
    path = store.run_file(work, 'C001', 'R009')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'status': 'training', 'output_name': 'x'}), encoding='utf-8')
    run = store.read(path)
    assert run['status'] == 'running' and run['phase'] == 'training'
    assert store.runs(work, 'C001')[0]['status'] == 'running'


def test_a_cancelled_llm_job_is_cancelling_until_it_has_stopped(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    job = c.post(f'/api/works/{wid}/relations/extract', json={}).json()
    cancelled = c.post(f'/api/jobs/{job["id"]}/cancel').json()
    assert cancelled['status'] in ('cancelling', 'cancelled')
    for _ in range(50):
        status = next(j for j in c.get('/api/jobs').json() if j['id'] == job['id'])['status']
        if status != 'cancelling':
            break
        time.sleep(0.05)
    assert status == 'cancelled'
    again = c.post(f'/api/jobs/{job["id"]}/cancel').json()
    assert again['status'] == 'cancelled'


def test_the_jobs_panel_lists_unfinished_image_work(unlocked):
    from test_image import FakeComfy

    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    assert c.get('/api/activity').json() == {'items': []}
    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    c.post(f'/api/works/{wid}/image/jobs', json={'targets': [target], 'count': 3})
    runtime.jobs[0]['status'] = 'running'
    (queue,) = c.get('/api/activity').json()['items']
    assert queue == {
        'kind': 'image_queue',
        'status': 'running',
        'counts': {'running': 1, 'queued': 2},
        'paused': True,
    }
    runtime.cancel_queued()
    runtime.jobs[0]['status'] = 'done'
    assert c.get('/api/activity').json() == {'items': []}
