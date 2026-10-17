"""Gallery regeneration keeps comparison cells and their original results."""

from atelierx.image.gallery import Gallery
from atelierx.image.util import atomic_json
from test_image import FakeComfy
from test_single_generation import _png


def _completed(runtime, job):
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')
    return job['image_url'].removeprefix('/api/image/files/')


def test_lab_regeneration_keeps_source_cell_through_queue_retry_and_reload(unlocked):
    client = unlocked
    runtime = client.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    reference = runtime.paths.output / 'reference.png'
    reference.write_bytes(_png())
    queued = client.post(
        '/api/image/lab',
        json={
            'positive': 'a distant mountain',
            'count': 2,
            'source': 'reference.png',
            'settings': {'seed': 100},
            'sweep': {'key': 'cfg', 'values': [4, 6]},
        },
    )
    assert queued.status_code == 200, queued.text
    original_other = _completed(runtime, runtime.jobs[0])
    original_target = _completed(runtime, runtime.jobs[3])
    client.post('/api/image/queue/cancel-queued')
    client.post('/api/image/queue/clear-finished')

    first = client.post('/api/image/gallery/regenerate', json={'items': [original_target], 'review': False})
    assert first.status_code == 200, first.text
    attempt = runtime.jobs[-1]
    assert (attempt['lab_row'], attempt['lab_column'], attempt['lab_index']) == (1, 1, 4)
    assert (attempt['lab_group'], attempt['lab_variant'], attempt['lab_sweep']) == (
        queued.json()['lab_group'],
        'CFG 6.0',
        'cfg',
    )
    assert attempt['lab_source'] == 'reference.png'
    assert attempt['source_path'] == original_target
    runtime.queue.load()  # A queued job keeps its cell coordinates after reopening the queue.
    attempt = runtime.jobs[-1]
    run = client.get('/api/image/lab/runs').json()['runs'][0]
    cells = {(cell['row'], cell['column']): cell for cell in run['cells']}
    assert cells[(0, 0)]['path'] == original_other
    assert 'regenerations' not in cells[(0, 0)]
    assert cells[(1, 1)]['path'] == original_target
    assert cells[(1, 1)]['regenerations'][0]['status'] == 'queued'

    attempt['status'] = 'failed'
    runtime.queue.persist()
    retried = client.post(f'/api/image/jobs/{attempt["id"]}/retry')
    assert retried.status_code == 200, retried.text
    retry_job = runtime.queue.get(retried.json()['job_id'])
    assert retry_job['source_path'] == original_target
    assert (retry_job['lab_row'], retry_job['lab_column']) == (1, 1)
    regenerated = _completed(runtime, retry_job)
    second = client.post('/api/image/gallery/regenerate', json={'items': [regenerated], 'review': False})
    assert second.status_code == 200, second.text
    repeated = runtime.jobs[-1]
    assert repeated['source_path'] == regenerated
    assert (repeated['lab_row'], repeated['lab_column']) == (1, 1)
    regenerated_again = _completed(runtime, repeated)
    client.post('/api/image/queue/clear-finished')
    runtime.gallery = Gallery(runtime.paths)
    runtime.gallery.scan(force=True)  # Rebuild from PNG sidecars, as after an app restart.
    run = client.get('/api/image/lab/runs').json()['runs'][0]
    cells = {(cell['row'], cell['column']): cell for cell in run['cells']}
    assert (run['rows'], run['columns']) == (2, 2)
    assert cells[(0, 0)]['path'] == original_other
    assert cells[(1, 1)]['path'] == original_target
    assert {entry['path'] for entry in cells[(1, 1)]['regenerations']} == {regenerated, regenerated_again}
    assert {entry['seed'] for entry in cells[(1, 1)]['regenerations']} == {
        runtime.gallery.metadata(path)['seed'] for path in (regenerated, regenerated_again)
    }
    assert run['source'] == 'reference.png'


def test_lab_regeneration_rejects_missing_cell_coordinates(unlocked):
    client = unlocked
    runtime = client.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    client.post('/api/image/lab', json={'positive': 'one leaf', 'count': 1})
    original = _completed(runtime, runtime.jobs[0])
    record = runtime.gallery.metadata(original)
    record.pop('lab_row')
    atomic_json(runtime.gallery.safe_path(original).with_suffix('.json'), record)
    refused = client.post('/api/image/gallery/regenerate', json={'items': [original], 'review': False})
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.lab.missing_cell'
    assert len(runtime.jobs) == 1
