def test_design_crud_revision_and_retired_outfit_ids(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    url = f'/api/works/{wid}/image/characters/C001'
    loaded = c.get(url).json()
    assert loaded['revision']
    design = loaded['design']
    design['outfits']['custom'] = {
        'name': '추가 의상',
        'slots': {'top': {'prompt': ['blue shirt']}},
        'negative': [],
    }
    saved = c.put(url, json={'design': design, 'base_revision': loaded['revision']})
    assert saved.status_code == 200
    assert saved.json()['design']['outfits']['custom']['name'] == '추가 의상'

    updated = saved.json()['design']
    revision = saved.json()['revision']
    updated['outfits']['custom']['name'] = '수정 의상'
    saved = c.put(url, json={'design': updated, 'base_revision': revision})
    assert saved.status_code == 200

    updated = saved.json()['design']
    revision = saved.json()['revision']
    del updated['outfits']['custom']
    updated['default_outfit'] = next(iter(updated['outfits']))
    removed = c.put(url, json={'design': updated, 'base_revision': revision})
    assert removed.status_code == 200
    assert 'custom' in removed.json()['design']['retired_outfit_ids']
    stale = c.put(url, json={'design': updated, 'base_revision': revision})
    assert stale.status_code == 409
    invalid = c.put(
        url,
        json={
            'design': {**removed.json()['design'], 'default_outfit': 'missing'},
            'base_revision': removed.json()['revision'],
        },
    )
    assert invalid.status_code == 400


def test_design_put_preserves_untouched_source_and_other_image_data(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    url = f'/api/works/{wid}/image/characters/C001'
    loaded = c.get(url).json()
    appearance_source = loaded['design']['appearance'].get('source')
    dataset_url = f'/api/works/{wid}/image/characters/C001/datasets'
    before = c.get(dataset_url).json()
    changed = loaded['design']
    changed['trigger'] = 'custom_trigger'
    saved = c.put(url, json={'design': changed, 'base_revision': loaded['revision']})
    assert saved.status_code == 200
    assert saved.json()['design']['appearance'].get('source') == appearance_source
    assert c.get(dataset_url).json() == before


def test_empty_design_create_delete_last_outfit_and_preserve_reference(unlocked):
    c = unlocked
    wid = c.post('/api/works', json={'name': '디자인 없는 작품'}).json()['id']
    c.post(f'/api/works/{wid}/folder', json={'path': '인물'})
    item = c.post(f'/api/works/{wid}/file', json={'path': '인물/테스트'}).json()
    c.put(
        f'/api/works/{wid}/file?path=인물/테스트.md',
        json={
            'meta': {'id': 'C101', 'kind': 'character'},
            'body': '## 외모\n짧은 머리\n',
            'base_hash': item['hash'],
        },
    )
    url = f'/api/works/{wid}/image/characters/C101'
    loaded = c.get(url).json()
    assert loaded['design'] is None and loaded['revision'] is None
    design = {
        'schema_version': 1,
        'appearance': {'prompt': ['1girl'], 'negative': []},
        'outfits': {
            'o01': {'name': '한 벌', 'slots': {'top': {'ref': 'work:foo', 'prompt': []}}, 'negative': []}
        },
        'default_outfit': 'o01',
    }
    created = c.put(url, json={'design': design, 'base_revision': None})
    assert created.status_code == 200
    assert created.json()['design']['outfits']['o01']['slots']['top']['ref'] == 'work:foo'
    design = created.json()['design']
    del design['outfits']['o01']
    design['default_outfit'] = None
    removed = c.put(url, json={'design': design, 'base_revision': created.json()['revision']})
    assert removed.status_code == 200
    assert removed.json()['design']['outfits'] == {}
    assert removed.json()['design']['default_outfit'] is None


def test_conversion_apply_refuses_a_newer_manual_design(unlocked):
    import time

    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    url = f'/api/works/{wid}/image/characters/C001'
    queued = c.post(f'{url}/convert', json={}).json()
    for _ in range(100):
        job = next(j for j in c.get('/api/jobs').json() if j['id'] == queued['id'])
        if job['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert job['status'] == 'done', job
    draft_id = job['result']['draft']
    draft = c.get(f'/api/works/{wid}/drafts/{draft_id}').json()
    assert draft['target']['base_design_revision']
    loaded = c.get(url).json()
    changed = loaded['design']
    changed['trigger'] = 'manual_change'
    assert c.put(url, json={'design': changed, 'base_revision': loaded['revision']}).status_code == 200
    assert c.post(f'/api/works/{wid}/drafts/{draft_id}/apply', json={}).status_code == 409

    queued = c.post(f'{url}/convert', json={}).json()
    for _ in range(100):
        job = next(j for j in c.get('/api/jobs').json() if j['id'] == queued['id'])
        if job['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert job['status'] == 'done', job
    fresh_id = job['result']['draft']
    rejected = c.post(
        f'/api/works/{wid}/drafts/{fresh_id}/apply', json={'design': {'outfits': [], 'appearance': {}}}
    )
    assert rejected.status_code == 400
    applied = c.post(f'/api/works/{wid}/drafts/{fresh_id}/apply', json={})
    assert applied.status_code == 200
    stored = c.get(f'/api/works/{wid}/drafts/{fresh_id}').json()
    assert stored['status'] == 'applied'
    assert stored['applied_design'] == applied.json()['design']
    assert c.post(f'/api/works/{wid}/drafts/{fresh_id}/apply', json={}).status_code == 409


def test_conversion_reconcile_keeps_user_added_outfits_and_never_reuses_removed_ids():
    from atelierx.image.designs import reconcile_conversion

    prior = {
        'appearance': {'prompt': ['custom'], 'negative': []},
        'outfits': {
            'o01': {
                'name': '기본',
                'slots': {},
                'negative': [],
                'source': {'section': 'outfit', 'heading': None},
            },
            'o02': {'name': '추가', 'slots': {}, 'negative': []},
        },
        'retired_outfit_ids': ['o03'],
        'default_outfit': 'o02',
        'trigger': 'keepme',
    }
    generated = {
        'appearance': {'prompt': ['converted'], 'negative': []},
        'outfits': {
            'o01': {
                'name': '기본',
                'slots': {},
                'negative': [],
                'source': {'section': 'outfit', 'heading': None},
            },
            'o02': {
                'name': '새 항목',
                'slots': {},
                'negative': [],
                'source': {'section': 'outfit', 'heading': '새 항목'},
            },
        },
        'default_outfit': 'o01',
    }
    merged = reconcile_conversion(prior, generated)
    assert merged['outfits']['o01']['name'] == '기본'
    assert merged['outfits']['o02']['name'] == '추가'
    assert merged['outfits']['o04']['name'] == '새 항목'
    assert merged['appearance']['prompt'] == ['converted']
    assert merged['default_outfit'] == 'o02'
    assert merged['trigger'] == 'keepme'
