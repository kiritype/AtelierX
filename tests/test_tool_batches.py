import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image

from atelierx.core.i18n import AppError
from atelierx.image.job_queue import JobQueue
from atelierx.image.tools.batches import MAX_INFLIGHT, ToolBatches
from atelierx.image.tools.workspace import ToolWorkspace
from atelierx.image.util import atomic_json


def runtime(paths):
    source = paths.root / 'sample.png'
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (2, 2)).save(source)
    lock = threading.RLock()
    return SimpleNamespace(
        paths=paths,
        lock=lock,
        queue=JobQueue(paths.state / 'queue.json', lock),
        gallery=SimpleNamespace(safe_path=lambda _: source),
    )


def test_8000_receipt_runs_in_bounded_chunks_and_preserves_all_results(paths):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    body = {'operation': 'gallery', 'request_id': 'request-8000', 'paths': [f'{i}.png' for i in range(8000)]}
    accepted = bulk.submit(body)
    assert accepted['total'] == 8000 and accepted['counts']['pending'] == 8000
    assert bulk.submit(body)['id'] == accepted['id']
    seen = set()
    while len(seen) < 8000:
        bulk.pump()
        assert 0 < len(rt.queue.jobs) <= MAX_INFLIGHT
        for job in rt.queue.jobs:
            assert job['id'] not in seen
            seen.add(job['id'])
            job.update(status='done', result={'sample': 'result'})
        rt.queue.persist()
    bulk.reconcile()
    assert not rt.queue.jobs
    assert bulk.public(accepted['id'])['counts']['done'] == 8000
    assert bulk.db.execute('SELECT count(*) FROM history').fetchone()[0] == 8000
    bulk.db.close()


def test_concurrent_duplicate_admission_capacity_cancel_and_retry(paths):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    body = {'operation': 'gallery', 'request_id': 'same-request', 'paths': ['one.png', 'two.png']}
    with ThreadPoolExecutor(2) as pool:
        accepted = list(pool.map(bulk.submit, [body, body]))
    assert accepted[0]['id'] == accepted[1]['id']
    with pytest.raises(AppError):
        bulk.submit({**body, 'paths': ['different.png']})
    rt.queue.jobs = [{'id': str(i), 'status': 'queued'} for i in range(5000)]
    bulk.pump()
    assert len(rt.queue.jobs) == 5000
    assert bulk.public(accepted[0]['id'])['counts']['pending'] == 2
    bulk.cancel(accepted[0]['id'])
    assert bulk.public(accepted[0]['id'])['counts']['cancelled'] == 2
    bulk.retry(accepted[0]['id'])
    rt.queue.jobs.clear()
    bulk.pump()
    rt.queue.jobs[0].update(status='done')
    rt.queue.jobs[1].update(status='failed', error='bad file')
    bulk.reconcile()
    bulk.retry(accepted[0]['id'])
    bulk.pump()
    assert len(rt.queue.jobs) == 1
    assert bulk.public(accepted[0]['id'])['counts']['done'] == 1
    bulk.db.close()


def test_unfinished_equivalent_work_is_reused_across_requests_and_restart(paths, monkeypatch):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    first = bulk.submit({'operation': 'gallery', 'request_id': 'first-run', 'paths': ['b', 'a']})
    again = bulk.submit({'operation': 'gallery', 'request_id': 'second-run', 'paths': ['a', 'b']})
    assert again['id'] == first['id'] and again['reused'] is True
    assert bulk.db.execute('SELECT count(*) FROM batches').fetchone()[0] == 1
    monkeypatch.setattr('atelierx.image.tools.batches.MAX_TARGETS', 2)
    assert (
        bulk.submit({'operation': 'gallery', 'request_id': 'third-run', 'paths': ['a', 'b']})['id']
        == first['id']
    )
    monkeypatch.undo()
    bulk.db.close()

    restored = ToolBatches(rt)
    assert (
        restored.submit({'operation': 'gallery', 'request_id': 'after-restart', 'paths': ['a', 'b']})['id']
        == first['id']
    )
    explicit = restored.submit(
        {'operation': 'gallery', 'request_id': 'explicit-run', 'paths': ['a', 'b'], 'rerun': True}
    )
    assert explicit['id'] != first['id']
    restored.cancel(first['id'])
    restored.cancel(explicit['id'])
    assert (
        restored.submit({'operation': 'gallery', 'request_id': 'second-run', 'paths': ['a', 'b']})['id']
        == first['id']
    )
    with pytest.raises(AppError):
        restored.submit({'operation': 'gallery', 'request_id': 'second-run', 'paths': ['a', 'different']})
    fresh = restored.submit({'operation': 'gallery', 'request_id': 'after-cancel', 'paths': ['a', 'b']})
    assert fresh['id'] not in (first['id'], explicit['id'])
    assert (
        restored.submit({'operation': 'gallery', 'request_id': 'after-cancel', 'paths': ['a', 'b']})['id']
        == fresh['id']
    )
    restored.db.close()


def test_restart_recovers_pending_intent_without_repeating_done_items(paths):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    accepted = bulk.submit({'operation': 'gallery', 'request_id': 'restart-test', 'paths': ['a', 'b', 'c']})
    bulk.pump()
    rt.queue.jobs[0].update(status='done')
    rt.queue.jobs[1].update(status='running')
    rt.queue.persist()
    bulk.reconcile()
    # Simulate a crash after an intent commits but before the queued job is appended.
    rt.queue.jobs = [job for job in rt.queue.jobs if job['status'] == 'running']
    rt.queue.persist()
    bulk.db.close()
    rt.queue.load()
    restored = ToolBatches(rt)
    counts = restored.public(accepted['id'])['counts']
    assert counts['done'] == 1 and counts['interrupted'] == 1 and counts['pending'] == 1
    restored.pump()
    assert len(rt.queue.jobs) == 1
    restored.db.close()


def test_changed_or_missing_source_fails_individually(paths):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    accepted = bulk.submit({'operation': 'gallery', 'request_id': 'source-test', 'paths': ['a']})
    rt.gallery.safe_path('a').unlink()
    bulk.pump()
    assert bulk.public(accepted['id'])['counts']['failed'] == 1
    assert not rt.queue.paused
    bulk.db.close()


def test_workspace_migrates_legacy_and_pages_without_truncating(paths):
    legacy = [{'id': str(i), 'source': 'gallery', 'path': f'{i}.png'} for i in range(2501)]
    path = paths.data / 'image' / 'tools' / 'tools.json'
    atomic_json(path, {'schema_version': 1, 'items': legacy})
    gallery = SimpleNamespace(safe_path=lambda name: paths.output / name)
    workspace = ToolWorkspace(paths, gallery)
    assert workspace.public(2400, 200)['total'] == 2501
    assert len(workspace.public(2400, 200)['items']) == 101
    workspace.set_tags('2500', {'tags': ['sample']})
    restored = ToolWorkspace(paths, gallery)
    assert len(restored.items) == 2501 and restored.get('2500')['tags']['tags'] == ['sample']
    assert path.is_file()


def test_2501_gallery_targets_are_all_added_to_sqlite_workspace(paths):
    rt = runtime(paths)
    rt.tools = ToolWorkspace(paths, rt.gallery)
    bulk = ToolBatches(rt)
    accepted = bulk.submit(
        {'operation': 'gallery', 'request_id': 'gallery-2501', 'paths': [f'{i}.png' for i in range(2501)]}
    )
    while bulk.public(accepted['id'])['counts']['done'] < 2501:
        bulk.pump()
        for job in list(rt.queue.jobs):
            bulk.run_cpu(job)
        bulk.reconcile()
    assert len(rt.tools.ids()['ids']) == 2501
    assert len(ToolWorkspace(paths, rt.gallery).items) == 2501
    bulk.db.close()


def test_committed_cancel_survives_crash_before_queue_cancel(paths):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    accepted = bulk.submit({'operation': 'gallery', 'request_id': 'cancel-crash', 'paths': ['a']})
    bulk.pump()
    with bulk.db:
        bulk.db.execute('UPDATE batches SET cancelled=1 WHERE id=?', (accepted['id'],))
    bulk.db.close()
    rt.queue.load()
    restored = ToolBatches(rt)
    assert restored.public(accepted['id'])['counts']['cancelled'] == 1
    assert not rt.queue.jobs
    restored.db.close()


def test_queue_write_failure_keeps_durable_intent_and_completed_result(paths, monkeypatch):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    accepted = bulk.submit({'operation': 'gallery', 'request_id': 'persist-failure', 'paths': ['a']})
    persist = rt.queue.persist

    def fail():
        raise OSError('disk full')

    monkeypatch.setattr(rt.queue, 'persist', fail)
    with pytest.raises(RuntimeError, match='persist bulk'):
        bulk.pump()
    assert bulk.public(accepted['id'])['counts']['queued'] == 1
    assert len(rt.queue.jobs) == 1
    monkeypatch.setattr(rt.queue, 'persist', persist)
    rt.queue.jobs[0].update(status='done', result={'saved': True})
    bulk.reconcile()
    assert bulk.public(accepted['id'])['counts']['done'] == 1
    assert bulk.details(accepted['id'])['items'][0]['result']['result'] == {'saved': True}
    assert not rt.queue.jobs
    bulk.db.close()


def test_pending_source_resolves_current_portable_location(paths, tmp_path):
    import shutil

    rt = runtime(paths)
    bulk = ToolBatches(rt)
    accepted = bulk.submit({'operation': 'gallery', 'request_id': 'portable-move', 'paths': ['a']})
    original = rt.gallery.safe_path('a')
    moved = tmp_path / 'relocated.png'
    shutil.copy2(original, moved)
    original.unlink()
    rt.gallery.safe_path = lambda _: moved
    bulk.pump()
    assert bulk.public(accepted['id'])['counts']['queued'] == 1
    bulk.db.close()


def test_restart_recovers_committed_output_before_done_write(paths):
    rt = runtime(paths)
    rt.tools = SimpleNamespace(items=[], add_gallery=lambda names: names)
    bulk = ToolBatches(rt)
    accepted = bulk.submit({'operation': 'gallery', 'request_id': 'output-crash', 'paths': ['a']})
    bulk.pump()
    job = rt.queue.jobs[0]
    job['status'] = 'running'
    rt.queue.persist()
    paths.output.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (2, 2)).save(paths.output / 'result.png')
    atomic_json(paths.output / 'result.json', {'job_id': job['id']})
    atomic_json(paths.output / 'unrelated.json', ['user', 'document'])
    atomic_json(paths.output / 'unrelated2.json', {'postprocessing': 'unknown'})
    bulk.db.close()
    rt.queue.load()
    restored = ToolBatches(rt)
    assert restored.public(accepted['id'])['counts']['done'] == 1
    restored.retry(accepted['id'])
    restored.pump()
    assert not rt.queue.jobs
    restored.db.close()


def test_bulk_api_freezes_mask_and_recovers_output(unlocked, paths):
    from test_tools import png, upload

    rt = unlocked.app.state.app.image
    rt.stop.set()
    rt._thread.join(timeout=5)
    item = upload(unlocked, 'sample.png', png())['added'][0]
    rt.tools.set_mask(item['id'], Image.new('L', (40, 30), 255), 'edited')
    body = {
        'operation': 'censor',
        'request_id': 'api-censor-batch',
        'ids': [item['id']],
        'treatment': 'color',
        'color': '#ff0000',
        'opacity': 100,
    }
    response = unlocked.post('/api/image/tools/batches', json=body)
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert unlocked.post('/api/image/tools/batches', json=body).json()['id'] == accepted['id']
    assert unlocked.post('/api/image/tools/batches', json={**body, 'opacity': 50}).status_code == 409
    # Simulate a receipt persisted by 0.4.1 before the new matching key existed.
    with rt.bulk.db:
        previous = json.loads(
            rt.bulk.db.execute('SELECT settings FROM batches WHERE id=?', (accepted['id'],)).fetchone()[0]
        )
        previous.pop('_submission_key')
        rt.bulk.db.execute('UPDATE batches SET settings=? WHERE id=?', (json.dumps(previous), accepted['id']))
    reused = unlocked.post('/api/image/tools/batches', json={**body, 'request_id': 'second-censor'}).json()
    assert reused['id'] == accepted['id'] and reused['reused'] is True
    other_settings = unlocked.post(
        '/api/image/tools/batches', json={**body, 'request_id': 'new-opacity', 'opacity': 50}
    ).json()
    assert other_settings['id'] != accepted['id']
    rt.tools.set_mask(item['id'], Image.new('L', (40, 30), 0), 'edited')
    other_mask = unlocked.post('/api/image/tools/batches', json={**body, 'request_id': 'new-mask'}).json()
    assert other_mask['id'] not in (accepted['id'], other_settings['id'])
    rt.bulk.pump()
    job = rt.queue.jobs[0]
    rt.bulk.run_cpu(job)
    rt.bulk.reconcile()
    assert rt.bulk.public(accepted['id'])['counts']['done'] == 1
    result = rt.tools.items[-1]
    with Image.open(rt.tools.file(result)) as image:
        assert image.convert('RGB').getpixel((10, 10)) == (255, 0, 0)
    assert unlocked.get('/api/image/tools/items?offset=0&limit=1').json()['total'] == 2
    assert unlocked.get('/api/image/tools/items?offset=oops').status_code == 400
    assert (
        unlocked.post(f'/api/image/tools/batches/{accepted["id"]}/retry', json={}).json()['counts']['done']
        == 1
    )


def test_clear_completed_receipts_preserves_images_masks_and_retries(unlocked, monkeypatch):
    from test_tools import png, upload

    rt = unlocked.app.state.app.image
    rt.stop.set()
    rt._thread.join(timeout=5)
    item = upload(unlocked, 'keep.png', png())['added'][0]
    rt.tools.set_mask(item['id'], Image.new('L', (40, 30), 255), 'edited')
    original = rt.tools.file(rt.tools.get(item['id']))
    mask = rt.tools.mask_path(item['id'], 'censor')
    body = {'operation': 'censor', 'request_id': 'clear-success', 'ids': [item['id']], 'treatment': 'color'}
    accepted = unlocked.post('/api/image/tools/batches', json=body).json()
    assert unlocked.post('/api/image/tools/batches/clear-completed', json={}).json()['cleared'] == 0
    assert unlocked.post('/api/image/tools/remove', json={'ids': [item['id']]}).status_code == 409
    assert original.is_file() and mask.is_file()
    rt.bulk.pump()
    rt.bulk.run_cpu(rt.queue.jobs[0])
    rt.bulk.reconcile()
    result = rt.tools.file(rt.tools.items[-1])
    assert rt.bulk.public(accepted['id'])['counts']['done'] == 1
    assert unlocked.post('/api/image/tools/batches/clear-completed', json={}).json()['cleared'] == 1
    assert accepted['id'] not in [
        batch['id'] for batch in unlocked.get('/api/image/tools/batches').json()['batches']
    ]
    assert original.is_file() and mask.is_file() and result.is_file()
    assert unlocked.post('/api/image/tools/batches', json=body).json()['id'] == accepted['id']
    assert unlocked.post('/api/image/tools/batches/clear-completed', json={}).json()['cleared'] == 0
    rt.queue.jobs.append({'id': 'legacy-tool-job', 'tool_item': item['id'], 'status': 'queued'})
    assert unlocked.post('/api/image/tools/remove', json={'ids': [item['id']]}).status_code == 409
    rt.queue.jobs.pop()
    monkeypatch.setattr(rt.convert, 'in_use', lambda ids: True)
    assert unlocked.post('/api/image/tools/remove', json={'ids': [item['id']]}).status_code == 409
    monkeypatch.setattr(rt.convert, 'in_use', lambda ids: False)
    assert unlocked.post('/api/image/tools/remove', json={'ids': [item['id']]}).json()['removed'] == 1
    assert not original.exists() and not mask.exists() and result.is_file()


def test_clear_completed_keeps_cancelled_and_retriable_receipts(paths):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    accepted = bulk.submit({'operation': 'gallery', 'request_id': 'clear-cancelled', 'paths': ['a']})
    bulk.cancel(accepted['id'])
    assert bulk.clear_completed()['cleared'] == 0
    assert accepted['id'] in [batch['id'] for batch in bulk.list()['batches']]
    bulk.retry(accepted['id'])
    assert bulk.public(accepted['id'])['counts']['pending'] == 1
    bulk.db.close()


def test_many_completed_receipts_do_not_hide_an_older_active_job(paths):
    rt = runtime(paths)
    bulk = ToolBatches(rt)
    active = bulk.submit({'operation': 'gallery', 'request_id': 'older-active', 'paths': ['a']})
    with bulk.db:
        for n in range(120):
            ident = f'completed-{n}'
            bulk.db.execute(
                'INSERT INTO batches(id,request_id,fingerprint,operation,settings,created_at) VALUES(?,?,?,?,?,?)',
                (ident, f'completed-request-{n}', 'fingerprint', 'gallery', '{}', f'9999-{n:03}'),
            )
            bulk.db.execute(
                "INSERT INTO items(batch,ordinal,target,status) VALUES(?,0,?,'done')",
                (ident, '{"id":"a"}'),
            )
    listed = bulk.list()
    assert listed['batches'][0]['id'] == active['id']
    assert len(listed['batches']) == 101 and listed['more_completed'] is True
    assert listed['running_count'] == 1 and listed['failed_count'] == 0
    bulk.db.close()


def test_bulk_tag_and_postprocess_api_use_frozen_settings(unlocked):
    from test_tools import ToolComfy, png, upload

    rt = unlocked.app.state.app.image
    rt.stop.set()
    rt._thread.join(timeout=5)
    rt.stop.clear()  # Worker is joined; run_job may poll the fake service synchronously.
    rt.comfy = ToolComfy()
    item = upload(unlocked, 'sample.png', png())['added'][0]
    for operation, options in [
        ('tag', {'threshold': 0.42}),
        ('postprocess', {'op': 'upscale', 'options': {'scale': 2}}),
    ]:
        body = {
            'operation': operation,
            'request_id': f'api-{operation}-frozen',
            'ids': [item['id']],
            **options,
        }
        response = unlocked.post('/api/image/tools/batches', json=body)
        assert response.status_code == 200, response.text
        accepted = response.json()
        with rt.bulk.db:
            saved = json.loads(
                rt.bulk.db.execute('SELECT settings FROM batches WHERE id=?', (accepted['id'],)).fetchone()[0]
            )
            saved.pop('_submission_key')
            rt.bulk.db.execute(
                'UPDATE batches SET settings=? WHERE id=?', (json.dumps(saved), accepted['id'])
            )
        repeated = unlocked.post(
            '/api/image/tools/batches', json={**body, 'request_id': f'legacy-{operation}'}
        ).json()
        assert repeated['id'] == accepted['id'] and repeated['reused'] is True
        rt.bulk.pump()
        job = rt.queue.jobs[0]
        rt.queue.update(job, status='running')
        rt.run_job(job)
        assert job['status'] == 'done', job.get('error')
        # Removing finished queue entries must first archive the receipt result.
        rt.remove_finished(job['id'])
        assert rt.bulk.public(accepted['id'])['counts']['done'] == 1
        if operation == 'tag':
            assert rt.tools.get(item['id'])['tags']['threshold'] == 0.42
        else:
            assert rt.comfy.prompts[-1]['2']['inputs']['upscale_model'] == '2x-Anime.pth'


def test_detect_mask_result_is_recovered_before_retry(unlocked, monkeypatch):
    from test_tools import png, upload

    rt = unlocked.app.state.app.image
    rt.stop.set()
    rt._thread.join(timeout=5)
    item = upload(unlocked, 'sample.png', png())['added'][0]
    monkeypatch.setattr(
        rt, 'postprocess_info', lambda: {'available': True, 'ops': ['detect'], 'prefix': 'AtelierX'}
    )
    response = unlocked.post(
        '/api/image/tools/batches',
        json={
            'operation': 'postprocess',
            'op': 'detect',
            'options': {'confidence': 0.6},
            'ids': [item['id']],
            'request_id': 'detect-recovery',
        },
    )
    assert response.status_code == 200, response.text
    ident = response.json()['id']
    rt.bulk.pump()
    job = rt.queue.jobs[0]
    assert job['post_options']['confidence'] == 0.6
    rt.save_post(job, png(), {})  # Synthetic detector result; no real model is invoked.
    rt.queue.update(job, status='failed', error='failed after saving output')
    with pytest.raises(ValueError):
        rt.queue.retry(job['id'])
    rt.bulk.retry(ident)
    assert rt.bulk.public(ident)['counts']['done'] == 1
    assert rt.tools.get(item['id'])['mask']['job_id'] == job['id']
    assert not rt.queue.jobs
