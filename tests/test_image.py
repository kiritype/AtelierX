import io
import json

from PIL import Image

from atelierx.image.deployment_export import plan_paths


def test_deployment_export_uses_expression_metadata_and_reports_collisions():
    items = [
        {
            'path': 'w/C001/images/o01/smile/001_003.png',
            'work_id': 'w',
            'character_id': 'C001',
            'outfit_id': 'o01',
            'expression_id': 'smile',
        },
        {
            'path': 'w/C001/images/o01/frown/001_004.png',
            'work_id': 'w',
            'character_id': 'C001',
            'outfit_id': 'o01',
            'expression_id': 'frown',
        },
    ]
    mapping, collisions = plan_paths(items, one_work=True)
    assert mapping == {
        items[0]['path']: 'C001/o01/smile.png',
        items[1]['path']: 'C001/o01/frown.png',
    }
    assert collisions == []
    numeric_expression = {**items[0], 'expression_id': '001'}
    numeric_mapping, _ = plan_paths([numeric_expression], one_work=True)
    assert numeric_mapping[items[0]['path']] == 'C001/o01/001.png'
    duplicate = {**items[0], 'path': 'w/C001/images/o01/smile/001_005.png'}
    _, collisions = plan_paths([items[0], duplicate], one_work=True)
    assert collisions == ['C001/o01/smile.png']


class FakeComfy:
    """Enough of ComfyUI's HTTP API for one generation."""

    url = 'http://127.0.0.1:8188'

    def __init__(self):
        self.prompts = []

    def catalog(self):
        return {
            'connected': True,
            'models': ['anima\\m.safetensors'],
            'text_encoders': ['qwen.safetensors'],
            'vaes': ['vae.safetensors'],
            'loras': [],
            'samplers': ['er_sde'],
            'schedulers': ['simple'],
            'clip_types': ['stable_diffusion'],
            'model_entries': {},
            'defaults': {},
        }

    def request(self, path, body=None, raw=False, timeout=15):
        if path in ('/queue', '/free'):
            return {}
        if path == '/prompt':
            self.prompts.append(body['prompt'])
            return {'prompt_id': 'p1'}
        if path.startswith('/history/'):
            return {
                'p1': {
                    'status': {'status_str': 'success'},
                    'outputs': {'output': {'images': [{'filename': 'a.png'}]}},
                }
            }
        if path.startswith('/view'):
            buffer = io.BytesIO()
            Image.new('RGB', (32, 32), (200, 40, 40)).save(buffer, format='PNG')
            return buffer.getvalue()
        raise AssertionError(path)


def test_library_compose_queue_and_save(unlocked, tmp_path):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)  # the test runs the job itself instead of the worker thread

    rules = c.get('/api/image/library/rules').json()
    assert [s['id'] for s in rules['slots']][:2] == ['full', 'hands']
    saved = c.put(
        '/api/image/library/styles/soft',
        json={
            'scope': 'work',
            'work': wid,
            'item': {'name': '부드럽게', 'prompt': 'soft lighting, soft lighting'},
        },
    ).json()
    assert saved['soft']['prompt'] == ['soft lighting'] and saved['soft']['scope'] == 'work'

    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    preview = c.post(
        f'/api/works/{wid}/image/compose', json={'targets': [target], 'style_ids': ['soft']}
    ).json()[0]
    assert preview['positive'].startswith('masterpiece')
    assert 'w001_c001' not in preview['positive'] and 'soft lighting' in preview['positive']
    assert 'white shirt' in preview['parts']['outfit']

    queued = c.post(
        f'/api/works/{wid}/image/jobs', json={'targets': [target], 'count': 2, 'style_ids': ['soft']}
    ).json()
    assert queued['count'] == 2
    jobs = c.get('/api/image/queue').json()['jobs']
    assert [j['status'] for j in jobs] == ['queued', 'queued']

    job = runtime.jobs[0]
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')
    graph = runtime.comfy.prompts[0]
    assert graph['1']['class_type'] == 'UNETLoader' and 'soft lighting' in json.dumps(
        graph, ensure_ascii=False
    )
    image = c.get(job['image_url'])
    assert image.status_code == 200
    png = Image.open(io.BytesIO(image.content))
    assert (
        'prompt' in png.text
        and 'workflow' in png.text
        and json.loads(png.text['atelierx'])['character_id'] == 'C001'
    )
    record = c.get(job['metadata_url']).json()
    assert record['seed'] == job['seed'] and record['outfit_id'] == 'o01'
    assert '/images/o01/smile/001.png' in job['image_url']

    assert c.post(f'/api/image/jobs/{runtime.jobs[1]["id"]}/cancel').status_code == 200
    assert c.post('/api/image/queue/clear-finished').json()['removed'] == 2
    assert c.get('/api/image/files/..%2Fconfig%2Fvault.json').status_code in (400, 404)


def test_tag_lookup(unlocked):
    c = unlocked
    done = c.get('/api/image/tags/complete', params={'q': 'long h'}).json()
    assert done['available'] and done['tags'][0]['tag'] == 'long hair'
    checked = c.post('/api/image/tags/check', json={'tags': ['1girl', 'longhair', 'zzzz_not_a_tag']}).json()[
        'tags'
    ]
    assert [t['status'] for t in checked] == ['ok', 'alias', 'unknown']
    assert checked[1]['alias_of']['tag'] == 'long hair'


def test_gallery_review_export_and_vlm_round(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    runtime.gpu.admit = lambda kind: None  # no nvidia-smi in tests
    settings = c.put('/api/image/review/settings', json={'enabled': True, 'max_auto_regenerations': 2}).json()
    assert settings['enabled'] and settings['connection']['local']

    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    c.post(f'/api/works/{wid}/image/jobs', json={'targets': [target], 'count': 2})
    for job in list(runtime.jobs):
        job['status'] = 'running'
        runtime.run_job(job)
        assert job['status'] == 'done', job.get('error')
    assert all(j.get('review_round_id') for j in runtime.jobs)

    tree = c.get('/api/image/gallery/tree').json()
    assert tree['works'][0]['characters'][0]['outfits'][0]['count'] == 2
    page = c.get('/api/image/gallery', params={'work': wid, 'sort': 'code'}).json()
    assert page['total'] == 2 and page['results'][0]['human_status'] == 'unreviewed'
    first, second = page['results']
    assert c.get(first['thumbnail_url']).headers['content-type'] == 'image/webp'
    detail = c.get('/api/image/gallery/detail', params={'path': first['path']}).json()
    assert detail['record']['expression_id'] == 'smile' and 'workflow' not in detail['record']

    # The mock connection passes everything; a person still adopts.
    runtime.set_paused(False)
    assert runtime.process_ready() is True
    rounds = c.get('/api/image/review/rounds').json()['rounds']
    assert [r['status'] for r in rounds] == ['awaiting_human', 'awaiting_human']
    assert c.get('/api/image/gallery', params={'auto_status': 'pass'}).json()['total'] == 2

    plan = c.post('/api/image/gallery/export/plan', json={'filters': {'work': wid}}).json()
    # Needed combinations without an adopted image: the generated one and, from the completeness board, never made ones.
    assert plan['count'] == 0 and {f'{wid}/C001/o01/smile', f'{wid}/C001/o01/neutral'} <= set(plan['missing'])
    reviewed = c.post(
        '/api/image/gallery/review', json={'verdict': 'pass', 'items': [{'path': second['path']}]}
    ).json()
    assert reviewed['results'][0]['adopted']
    assert {r['status'] for r in c.get('/api/image/review/rounds').json()['rounds']} == {'human_accepted'}
    assert c.get('/api/image/gallery', params={'adopted': '1'}).json()['total'] == 1
    refused = c.post('/api/image/gallery/export', json={'filters': {'work': wid}})
    assert refused.status_code == 400 and refused.json()['error']['key'] == 'server.gallery.export_incomplete'
    exported = c.post('/api/image/gallery/export', json={'filters': {'work': wid}, 'allow_partial': True})
    assert exported.status_code == 200
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(exported.content)).namelist()
    assert names == ['C001/o01/smile.png', 'manifest.json']
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read('manifest.json'))
    assert list(manifest['source_to_export'].values()) == ['C001/o01/smile.png']
    stripped = c.post(
        '/api/image/gallery/export',
        json={'filters': {'work': wid}, 'strip_metadata': True, 'allow_partial': True},
    )
    with zipfile.ZipFile(io.BytesIO(stripped.content)) as archive:
        clean = Image.open(io.BytesIO(archive.read('C001/o01/smile.png')))
    assert clean.size == (32, 32) and not getattr(clean, 'text', {})
    assert (runtime.paths.output / 'reviews.json').is_file()

    # A failed verdict on the adopted image drops the adoption.
    c.post('/api/image/gallery/review', json={'verdict': 'fail', 'items': [second['path']]})
    assert c.get('/api/image/gallery', params={'adopted': '1'}).json()['total'] == 0

    regenerated = c.post(
        '/api/image/gallery/regenerate', json={'items': [first['path']], 'review': False}
    ).json()
    assert regenerated['count'] == 1 and not regenerated['reviewing']
    fresh = runtime.jobs[-1]
    assert fresh['status'] == 'queued' and fresh['seed'] != first['seed']
    assert fresh['snapshot']['positive'] and fresh['character_id'] == 'C001'
    assert c.get('/api/image/gallery/thumbnail', params={'path': '../config/vault.json'}).status_code == 404


def test_image_review_run_override_requires_selected_consent_and_is_kept_on_round(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    c.put('/api/image/review/settings', json={'enabled': True})
    providers = c.get('/api/providers').json()
    providers['providers']['remote'] = {
        'name': 'Remote',
        'type': 'openai_compatible',
        'base_url': 'https://llm.example.com/v1',
        'default_model': 'review-model',
    }
    c.put('/api/providers', json=providers)
    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    body = {'targets': [target], 'llm': {'provider': 'remote'}}

    blocked = c.post(f'/api/works/{wid}/image/jobs', json=body)
    assert blocked.status_code == 428
    c.patch(f'/api/works/{wid}', json={'llm_consent': ['remote']})
    providers['providers']['remote']['type'] = 'mock'
    c.put('/api/providers', json=providers)
    assert c.post(f'/api/works/{wid}/image/jobs', json=body).status_code == 200

    assert runtime.jobs[0]['review_llm'] == {'provider': 'remote'}
    assert runtime.rounds.rounds[0]['llm'] == {'provider': 'remote'}
    assert c.get('/api/providers').json()['tasks'].get('image_review') is None


def stop_worker(runtime):
    """End the image worker thread, so a test that runs jobs and reviews itself does not race it."""
    runtime.stop.set()
    if runtime._thread is not None:
        runtime._thread.join(timeout=5)
        runtime._thread = None
    runtime.stop.clear()  # jobs run by the test check the same signal


def test_vlm_fail_regenerates_until_the_limit(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    stop_worker(runtime)
    runtime.gpu.admit = lambda kind: None
    runtime.rounds.review_one = lambda path, snapshot, work, override=None: {
        'verdict': 'fail',
        'evidence': 'wrong hair colour',
    }
    c.put('/api/image/review/settings', json={'enabled': True, 'max_auto_regenerations': 1})
    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    c.post(f'/api/works/{wid}/image/jobs', json={'targets': [target]})
    for _ in range(2):
        job = next(j for j in runtime.jobs if j['status'] == 'queued')
        job['status'] = 'running'
        runtime.run_job(job)
        assert runtime.process_ready() is True
    (round_,) = runtime.rounds.rounds
    assert round_['status'] == 'limit_reached' and round_['regenerations'] == 1
    assert len(runtime.jobs) == 2 and runtime.jobs[1]['regeneration'] == 1
    assert [a['verdict'] for a in round_['attempts']] == ['fail', 'fail']


def test_lab_sweep_runs_survive_clearing_the_queue(unlocked):
    c = unlocked
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    bad = c.post('/api/image/lab', json={'positive': '1girl', 'sweep': {'key': 'cfg', 'values': [4]}})
    assert bad.status_code == 400
    queued = c.post(
        '/api/image/lab',
        json={
            'positive': '1girl, smile',
            'negative': 'lowres',
            'count': 2,
            'sweep': {'key': 'cfg', 'values': [4, 6]},
        },
    ).json()
    assert queued['count'] == 4
    (run,) = c.get('/api/image/lab/runs').json()['runs']
    assert (run['rows'], run['columns'], run['sweep']) == (2, 2, 'cfg')
    assert {cell['status'] for cell in run['cells']} == {'queued'}
    # One seed per row: both values of a row share it.
    assert run['cells'][0]['seed'] == run['cells'][1]['seed'] != run['cells'][2]['seed']

    job = runtime.jobs[1]
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')
    assert '/_lab/' in job['image_url'] and runtime.comfy.prompts[0]
    c.post('/api/image/queue/cancel-queued')
    c.post('/api/image/queue/clear-finished')
    (run,) = c.get('/api/image/lab/runs').json()['runs']
    (cell,) = run['cells']
    assert (cell['row'], cell['column'], cell['lab_variant']) == (0, 1, 'CFG 6.0')
    record = c.get('/api/image/gallery/detail', params={'path': cell['path']}).json()['record']
    assert record['settings']['cfg'] == 6.0 and record['kind'] == 'lab'


def test_lab_lora_files_share_seeds_and_preserve_other_settings(unlocked):
    c = unlocked
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    catalog = runtime.comfy.catalog()
    catalog['loras'] = ['anima/e02.safetensors', 'anima/e04.safetensors', 'style.safetensors']
    runtime.comfy.catalog = lambda: catalog
    runtime.set_paused(True)
    body = {
        'positive': '1girl, character_trigger',
        'negative': 'lowres',
        'count': 2,
        'settings': {
            'seed': 123,
            'loras': [
                {'name': 'style.safetensors', 'strength_model': 0.4, 'strength_clip': 0.5},
                {'name': 'anima/e02.safetensors', 'strength_model': 0.8, 'strength_clip': 0.7},
            ],
        },
        'sweep': {'key': 'lora_file', 'lora_index': 1, 'values': catalog['loras'][:2]},
    }
    assert c.post('/api/image/lab', json=body).json()['count'] == 4
    assert [j['seed'] for j in runtime.jobs] == [123, 123, 124, 124]
    for i, job in enumerate(runtime.jobs):
        snapshot = job['snapshot']
        assert snapshot['positive'] == body['positive'] and snapshot['negative'] == 'lowres'
        loras = snapshot['settings']['loras']
        assert loras[0] == body['settings']['loras'][0]
        assert loras[1] == {**body['settings']['loras'][1], 'name': catalog['loras'][i % 2]}
    for sweep in [
        {'values': ['anima/e02.safetensors', 'missing.safetensors']},
        {'values': ['anima/e02.safetensors'] * 2},
        {'values': ['anima/e02.safetensors', 'style.safetensors']},
        {'lora_index': -1},
        {'lora_index': True},
        {'lora_index': 3},
    ]:
        invalid = {**body, 'sweep': {**body['sweep'], **sweep}}
        assert c.post('/api/image/lab', json=invalid).status_code == 400
        assert len(runtime.jobs) == 4
    # Empty settings append one comparison slot at strength 1.
    assert (
        c.post(
            '/api/image/lab',
            json={
                **body,
                'settings': {},
                'sweep': {
                    **body['sweep'],
                    'lora_index': 0,
                },
            },
        ).status_code
        == 200
    )
    assert runtime.jobs[-1]['snapshot']['settings']['loras'] == [
        {'name': 'anima/e04.safetensors', 'strength_model': 1, 'strength_clip': 1},
    ]
    job = runtime.jobs[1]
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'done', job.get('error')
    c.post('/api/image/queue/cancel-queued')
    c.post('/api/image/queue/clear-finished')
    run = c.get('/api/image/lab/runs').json()['runs'][0]
    assert run['sweep'] == 'lora_file' and run['cells'][0]['lab_variant'] == 'anima/e04.safetensors'


def test_output_trash_moves_restores_and_purges(unlocked):
    c = unlocked
    runtime = c.app.state.app.image
    folder = runtime.paths.output / 'W009' / 'C001' / 'images' / 'o01' / 'smile'
    folder.mkdir(parents=True)
    Image.new('RGB', (8, 8), (1, 2, 3)).save(folder / '001.png')
    (folder / '001.json').write_text('{"character_id": "C001"}', encoding='utf-8')
    path = 'W009/C001/images/o01/smile/001.png'
    c.post('/api/image/gallery/review', json={'verdict': 'pass', 'items': [path]})
    c.post('/api/image/tools/gallery', json={'paths': [path]})

    assert c.post('/api/image/gallery/delete', json={'paths': [path]}).json()['deleted'] == 1
    assert not (folder / '001.png').exists() and not (folder / '001.json').exists()
    assert c.get('/api/image/gallery', params={'work': 'W009'}).json()['total'] == 0
    assert c.get('/api/image/tools/items').json()['items'] == []
    (entry,) = c.get('/api/image/trash').json()['entries']
    assert entry['path'] == path and c.get(entry['image_url']).status_code == 200

    # The verdict comes back with the image.
    assert c.post('/api/image/trash/restore', json={'ids': [entry['id']]}).json()['restored'] == [path]
    (item,) = c.get('/api/image/gallery', params={'work': 'W009'}).json()['results']
    assert item['human_status'] == 'pass' and item['adopted'] and (folder / '001.json').exists()

    c.post('/api/image/gallery/delete', json={'paths': [path]})
    assert c.post('/api/image/trash/purge', json={}).json()['purged'] == 1
    assert c.get('/api/image/trash').json()['entries'] == []
    assert list((runtime.paths.output / '.trash').iterdir()) == [
        runtime.paths.output / '.trash' / 'index.json'
    ]


def test_the_completeness_board_counts_needed_combinations(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    runtime.gpu.admit = lambda kind: None

    board = c.get(f'/api/works/{wid}/image/board').json()
    expressions = [e['id'] for e in board['expressions']]
    character = board['characters'][0]
    outfits = [o['id'] for o in character['outfits']]
    assert character['id'] == 'C001' and character['required'] == len(outfits) * len(expressions)
    assert {cell['state'] for cell in character['cells'].values()} == {'missing'}

    c.post(
        f'/api/works/{wid}/image/jobs',
        json={'targets': [{'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}]},
    )
    assert c.get(f'/api/works/{wid}/image/board').json()['characters'][0]['cells']['o01/smile']['queued'] == 1
    for job in list(runtime.jobs):
        job['status'] = 'running'
        runtime.run_job(job)
    cell = c.get(f'/api/works/{wid}/image/board').json()['characters'][0]['cells']['o01/smile']
    assert cell == {'state': 'generated', 'images': 1, 'queued': 0}

    path = c.get('/api/image/gallery', params={'work': wid}).json()['results'][0]['path']
    c.post('/api/image/gallery/review', json={'verdict': 'pass', 'items': [{'path': path}]})
    board = c.get(f'/api/works/{wid}/image/board').json()
    assert board['characters'][0]['cells']['o01/smile']['state'] == 'adopted' and board['adopted'] == 1

    others = [f'o01/{e}' for e in expressions if e != 'smile']
    board = c.put(
        f'/api/works/{wid}/image/board/exclude',
        json={'character_id': 'C001', 'combos': others[:1], 'excluded': True},
    ).json()
    assert board['characters'][0]['cells'][others[0]]['state'] == 'excluded'
    assert board['characters'][0]['required'] == len(outfits) * len(expressions) - 1
    plan = c.post('/api/image/gallery/export/plan', json={'filters': {'work': wid}}).json()
    assert f'{wid}/C001/{others[0]}' not in plan['missing'] and f'{wid}/C001/{others[1]}' in plan['missing']
    assert f'{wid}/C001/o01/smile' not in plan['missing'] and plan['count'] == 1

    board = c.put(
        f'/api/works/{wid}/image/board/exclude',
        json={'character_id': 'C001', 'combos': others[:1], 'excluded': False},
    ).json()
    assert board['characters'][0]['cells'][others[0]]['state'] == 'missing'
    bad = c.put(f'/api/works/{wid}/image/board/exclude', json={'character_id': 'C001', 'combos': ['../x']})
    assert bad.status_code == 400


def test_a_lab_result_comes_into_the_gallery_as_a_combination(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    c.post('/api/image/lab', json={'positive': '1girl, smile', 'count': 1})
    job = runtime.jobs[0]
    job['status'] = 'running'
    runtime.run_job(job)
    (run,) = c.get('/api/image/lab/runs').json()['runs']
    lab_path = run['cells'][0]['path']

    combo = {'work_id': wid, 'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    imported = c.post('/api/image/lab/import', json={'path': lab_path, **combo}).json()
    assert imported['path'] == f'{wid}/C001/images/o01/smile/001.png'
    detail = c.get('/api/image/gallery/detail', params={'path': imported['path']}).json()
    record = detail['record']
    assert record['expression_id'] == 'smile' and record['imported_from'] == lab_path and 'kind' not in record
    assert (runtime.paths.output / lab_path).is_file()  # the lab copy stays

    c.post('/api/image/gallery/review', json={'verdict': 'pass', 'items': [{'path': imported['path']}]})
    plan = c.post('/api/image/gallery/export/plan', json={'filters': {'work': wid}}).json()
    assert plan['count'] == 1 and list(plan['files']) == ['C001/o01/smile.png']

    second = c.post('/api/image/lab/import', json={'path': lab_path, **combo}).json()
    assert second['path'].endswith('/002.png')
    for bad in (
        {'path': imported['path'], **combo},  # not a lab result
        {'path': lab_path, **combo, 'outfit_id': 'nope'},
        {'path': lab_path, **combo, 'expression_id': 'nope'},
        {'path': '../x.png', **combo},
    ):
        assert c.post('/api/image/lab/import', json=bad).status_code == 400
