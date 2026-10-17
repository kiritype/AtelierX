"""Tool results retain the generation origin used by gallery regeneration."""

from PIL import Image

from atelierx.image.util import atomic_json
from test_single_generation import _png, _setup


def _generated(runtime, wid, kind, service):
    snapshot = {
        'kind': kind,
        'work_id': wid,
        'service': service,
        'positive': 'original prompt',
        'negative': 'original negative',
        'settings': {'seed': 7},
    }
    job = {
        'id': f'origin-{kind}',
        'kind': kind,
        'work_id': wid,
        'service': service,
        'seed': 7,
        'snapshot': snapshot,
    }
    if kind == 'lab':
        lab = {'lab_group': 'abc123', 'lab_index': 1, 'lab_row': 2, 'lab_column': 3, 'lab_variant': 'cfg 7'}
        job.update(lab)
        snapshot.update(lab)
    elif kind == 'character':
        ids = {'character_id': 'C001', 'outfit_id': 'O001', 'expression_id': 'E001'}
        job.update(ids)
        snapshot.update(ids)
        job.pop('kind')
        snapshot.pop('kind')
    url = runtime.save_result(job, _png(), {}, 'fake-id')
    return url.removeprefix('/api/image/files/')


def _process(runtime, relative, *, changed=False):
    item = runtime.tools.add_gallery([relative])['items'][0]
    made = {'positive': 'redrawn prompt', 'settings': {'seed': 999}} if changed else None
    url, path = runtime._store_result(
        item,
        Image.new('RGB', (32, 24), (70, 110, 170)),
        'upscale',
        {'scale': 2},
        None,
        'post-job',
        made=made,
    )
    return url.removeprefix('/api/image/files/'), path


def test_single_and_lab_postprocess_keep_origin_across_multiple_passes(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    for kind, service in (('single', 'novelai'), ('lab', 'comfyui')):
        original = _generated(runtime, wid, kind, service)
        first, _ = _process(runtime, original, changed=True)
        second, _ = _process(runtime, first)
        record = runtime.gallery.metadata(second)
        assert record['kind'] == 'postprocess'
        assert record['source']['path'] == first
        assert record['service'] == service
        if kind == 'single':
            assert record['work_id'] == wid
        assert record['positive'] == 'redrawn prompt'

        response = client.post('/api/image/gallery/regenerate', json={'items': [second], 'review': False})
        assert response.status_code == 200, response.text
        assert (
            response.json()['warning']['key'] == 'server.pipeline.post_processed_images_are_regenerated_from'
        )
        fresh = runtime.jobs[-1]
        assert fresh['kind'] == kind and fresh['service'] == service
        assert fresh['snapshot']['positive'] == 'original prompt'
        assert fresh['snapshot']['settings']['seed'] == fresh['seed']
        assert fresh['source_path'] == second
        if kind == 'single':
            assert fresh['work_id'] == wid
            assert runtime.save_result(fresh, _png(), {}, 'fake-id').startswith(
                f'/api/image/files/_single/{wid}/'
            )
        else:
            assert fresh['lab_group'] == 'abc123'
            assert runtime.save_result(fresh, _png(), {}, 'fake-id').startswith('/api/image/files/_lab/')


def test_old_postprocess_chain_recovers_origin_from_source_paths(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    original = _generated(runtime, wid, 'single', 'pixai')
    first, first_path = _process(runtime, original)
    second, second_path = _process(runtime, first)
    for path in (first_path, second_path):
        record = runtime.gallery.metadata(path.relative_to(runtime.paths.output).as_posix())
        record.pop('service', None)
        record.pop('work_id', None)
        atomic_json(path.with_suffix('.json'), record)
    runtime.gallery._meta_cache.clear()  # A fresh process has no cached sidecars.
    response = client.post('/api/image/gallery/regenerate', json={'items': [second], 'review': False})
    assert response.status_code == 200, response.text
    assert runtime.jobs[-1]['service'] == 'pixai'
    assert runtime.jobs[-1]['kind'] == 'single'


def test_character_postprocess_retains_service_and_identity(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    original = _generated(runtime, wid, 'character', 'novelai')
    processed, _ = _process(runtime, original)
    record = runtime.gallery.metadata(processed)
    assert record['service'] == 'novelai'
    assert record['character_id'] == 'C001'
    source = runtime.rounds.source_job(processed)
    assert source['service'] == 'novelai'
    assert source['character_id'] == 'C001'
    assert source['postprocessed']


def test_legacy_lab_origin_has_unambiguous_comfyui_service(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    original = _generated(runtime, wid, 'lab', 'comfyui')
    path = runtime.gallery.safe_path(original)
    record = runtime.gallery.metadata(original)
    record.pop('service')
    atomic_json(path.with_suffix('.json'), record)
    processed, _ = _process(runtime, original)
    response = client.post('/api/image/gallery/regenerate', json={'items': [processed], 'review': False})
    assert response.status_code == 200, response.text
    assert runtime.jobs[-1]['service'] == 'comfyui'


def test_postprocess_without_origin_or_service_rejects_regeneration(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    original = _generated(runtime, wid, 'single', 'novelai')
    processed, path = _process(runtime, original)
    original_path = runtime.gallery.safe_path(original)
    original_record = runtime.gallery.metadata(original)
    original_record.pop('service')
    atomic_json(original_path.with_suffix('.json'), original_record)
    refused = client.post('/api/image/gallery/regenerate', json={'items': [processed]})
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.gallery.unknown_generation_service'
    assert not runtime.jobs

    record = runtime.gallery.metadata(processed)
    record['source']['path'] = 'missing.png'
    atomic_json(path.with_suffix('.json'), record)
    refused = client.post('/api/image/gallery/regenerate', json={'items': [processed]})
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.gallery.no_generation_origin'


def test_cycle_and_uploaded_image_do_not_invent_a_generation_origin(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    original = _generated(runtime, wid, 'single', 'comfyui')
    processed, path = _process(runtime, original)
    record = runtime.gallery.metadata(processed)
    record['source']['path'] = processed
    atomic_json(path.with_suffix('.json'), record)
    refused = client.post('/api/image/gallery/regenerate', json={'items': [processed]})
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.gallery.no_generation_origin'

    item = runtime.tools.upload('external.png', _png())['added'][0]
    url, _ = runtime._store_result(
        item,
        Image.new('RGB', (32, 24), (70, 110, 170)),
        'upscale',
        {},
        None,
        'post-job',
        made={'positive': 'redrawn prompt', 'settings': {'seed': 3}},
    )
    external = url.removeprefix('/api/image/files/')
    refused = client.post('/api/image/gallery/regenerate', json={'items': [external]})
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.gallery.no_generation_origin'


def test_character_without_explicit_service_is_not_reassigned(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    original = _generated(runtime, wid, 'character', 'novelai')
    path = runtime.gallery.safe_path(original)
    record = runtime.gallery.metadata(original)
    record.pop('service')
    atomic_json(path.with_suffix('.json'), record)
    refused = client.post('/api/image/gallery/regenerate', json={'items': [original]})
    assert refused.status_code == 400
    assert refused.json()['error']['key'] == 'server.gallery.unknown_generation_service'


def test_regeneration_queue_reload_and_retry_keep_source_in_snapshot(unlocked):
    client = unlocked
    wid, runtime = _setup(client)
    original = _generated(runtime, wid, 'single', 'novelai')
    processed, _ = _process(runtime, original)
    response = client.post('/api/image/gallery/regenerate', json={'items': [processed], 'review': False})
    assert response.status_code == 200, response.text
    runtime.queue.load()
    job = runtime.jobs[-1]
    assert job['snapshot']['source_path'] == processed
    job['status'] = 'failed'
    runtime.queue.persist()
    retried = client.post(f'/api/image/jobs/{job["id"]}/retry')
    assert retried.status_code == 200, retried.text
    retry_job = runtime.queue.get(retried.json()['job_id'])
    assert retry_job['kind'] == 'single' and retry_job['service'] == 'novelai'
    assert retry_job['snapshot']['source_path'] == processed
    saved = runtime.save_result(retry_job, _png(), {}, 'fake-id')
    record = runtime.gallery.metadata(saved.removeprefix('/api/image/files/'))
    assert record['source_path'] == processed
    assert record['kind'] == 'single' and record['service'] == 'novelai'
