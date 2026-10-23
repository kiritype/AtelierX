import copy
import random

import pytest

from atelierx.image import library
from atelierx.image.style_search import (
    StyleSearch,
    artist_prompt,
    propose,
    random_candidate,
    ranking,
    valid_config,
    validate_rules,
)
from atelierx.image.tags import TagIndex
from test_single_generation import _png, _setup


def pool(*names):
    return [{'name': name, 'mode': 'candidate'} for name in names]


def session():
    pools = {'artists': pool('a', 'b', 'c', 'd'), 'models': pool('model'), 'loras': pool('l1', 'l2')}
    return {
        'pools': pools,
        'rules': validate_rules({}, pools, 'comfyui'),
        'candidates': [],
        'events': [],
        'rng': random.Random(72).getstate(),
    }


def test_distribution_fixed_items_and_weight_grid():
    s = session()
    s['pools']['artists'][0]['mode'] = 'always'
    rng = random.Random(8)
    counts = set()
    for _ in range(400):
        config = random_candidate(rng, s)
        assert valid_config(config, s)
        assert 'a' in [x['name'] for x in config['artists']]
        counts.add(len(config['artists']))
    assert counts == {1, 2, 3}
    assert validate_rules({}, {'artists': [], 'models': pool('m'), 'loras': []}, 'novelai')['artist_max'] == 0
    with pytest.raises(ValueError):
        validate_rules({'artist_min': 2}, {'artists': pool('a'), 'models': pool('m'), 'loras': []}, 'comfyui')
    for rule in [{'artist_step': 0}, {'artist_high': float('inf')}, {'lora_max': 17}]:
        with pytest.raises(ValueError):
            validate_rules(rule, s['pools'], 'comfyui')


def test_elo_undo_and_bad_do_not_count_as_scored_comparisons():
    s = session()
    s['candidates'] = [{'id': 'a'}, {'id': 'b'}]
    s['events'] = [{'pair': ['a', 'b'], 'choice': 'a'}]
    assert ranking(s)['a'] == {'score': 1012, 'count': 1, 'wins': 1, 'bad': 0}
    s['events'] += [{'pair': ['b', 'a'], 'choice': 'bad'}, {'pair': ['a', 'b'], 'choice': 'skip'}]
    assert ranking(s)['a'] == {'score': 1012, 'count': 1, 'wins': 1, 'bad': 1}
    s['events'][0]['undone'] = True
    assert ranking(s)['a'] == {'score': 1000, 'count': 0, 'wins': 0, 'bad': 1}


def test_seed_replay_unique_exhaustion_and_parent_ratios():
    s = session()
    first, _ = propose(s, 10)
    repeat, _ = propose(s, 10)
    assert [c['config'] for c in first] == [c['config'] for c in repeat]
    s['candidates'] = first
    for c in first:
        c['status'] = 'done'
    s['events'] = [{'pair': [first[0]['id'], first[i]['id']], 'choice': 'a'} for i in (1, 2, 3)]
    next_, _ = propose(s, 10)
    assert sum(c['parent_id'] is not None for c in next_) == 7
    assert sum('weight' in c['change'] for c in next_) == 4
    assert all(valid_config(c['config'], s) for c in next_)
    s['pools'] = {'artists': [], 'loras': [], 'models': pool('model')}
    s['rules'] = validate_rules({}, s['pools'], 'comfyui')
    s['candidates'] = []
    s['events'] = []
    only, _ = propose(s, 10)
    assert len(only) == 1


def test_artist_lookup_pages_cover_entire_dictionary_and_prompt_escaping(tmp_path):
    p = tmp_path / 'tags.csv'
    p.write_text('\n'.join(f'artist_{i},1,{i},' for i in range(130)) + '\nother,0,999,', encoding='utf-8')
    index = TagIndex([p])
    assert len([n for n in index._by_count if index.tags[n][0] == '1']) == 130
    assert artist_prompt({'artists': [{'name': 'a_(b)', 'weight': 1.1}]}, 'comfyui') == '(a_\\(b\\):1.1)'


def create(client, rt):
    body = {
        'pools': {'artists': pool('a', 'b'), 'models': pool(rt.comfy.catalog()['models'][0]), 'loras': []},
        'settings': {'seed': 42},
    }
    response = client.post('/api/image/explore/sessions', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def action(client, s, op, **kwargs):
    if op == 'evaluate':
        kwargs.setdefault('pair', s['pair'])
    response = client.post(
        '/api/image/explore/sessions/' + s['id'], json={'revision': s['revision'], 'action': op, **kwargs}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_session_generation_evaluation_presets_restore_and_independent_pools(unlocked, monkeypatch):
    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    pools = unlocked.get('/api/image/explore/pools').json()
    response = unlocked.post(
        '/api/image/explore/pools',
        json={**pools, 'name': 'mine', 'kind': 'artists', 'items': pool('different')},
    )
    assert response.status_code == 200
    assert rt.style_search.get(s['id'])['pools']['artists'] == pool('a', 'b')
    s = action(unlocked, s, 'propose', count=2)
    s = action(unlocked, s, 'generate')
    service = rt.services['comfyui']
    monkeypatch.setattr(service, 'busy', lambda: False)
    monkeypatch.setattr(service, 'submit', lambda job: {'id': 'remote', 'record': {}})
    monkeypatch.setattr(service, 'poll', lambda job, request: {'image': _png()})
    for c in s['candidates']:
        job = rt.queue.get(c['attempts'][0]['id'])
        job['status'] = 'running'
        rt.run_job(job)
        assert job['status'] == 'done', job.get('error')
    s = unlocked.get('/api/image/explore/sessions/' + s['id']).json()
    s = action(unlocked, s, 'pair')
    assert s['pair']
    before = copy.deepcopy(s)
    s = action(unlocked, s, 'evaluate', choice='a')
    assert s['pair'] is None
    assert max(x['score'] for x in s['scores'].values()) == 1012
    s = action(unlocked, s, 'undo')
    assert s['pair'] == before['pair']
    assert all(x['score'] == 1000 for x in s['scores'].values())
    s = action(unlocked, s, 'save_presets', candidates=[s['candidates'][0]['id']], name='chosen')
    saved = library.presets(rt.paths)[0]
    assert saved['artist']['positive'] and not saved['artist']['negative']
    assert 'seed' not in saved['settings'] and s['positive'] not in str(saved)
    fresh = StyleSearch(rt)
    assert fresh.get(s['id'])['pair'] == s['pair']
    for c in s['candidates']:
        rt.remove_finished(c['attempts'][0]['id'])
    assert all(c['status'] == 'done' for c in fresh.get(s['id'])['candidates'])
    # A stale tab cannot overwrite the latest evaluations.
    assert (
        unlocked.post(
            '/api/image/explore/sessions/' + s['id'], json={'revision': before['revision'], 'action': 'undo'}
        ).status_code
        == 409
    )


def test_cancel_retry_keeps_seed_and_restart_never_submits(unlocked):
    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    s = action(unlocked, s, 'propose', count=1)
    s = action(unlocked, s, 'generate')
    s = action(unlocked, s, 'cancel')
    assert s['candidates'][0]['status'] == 'cancelled'
    s = action(unlocked, s, 'retry', candidates=[s['candidates'][0]['id']])
    c = s['candidates'][0]
    assert len(c['attempts']) == 2
    job = rt.queue.get(c['attempts'][-1]['id'])
    assert job['seed'] == 42
    rt.queue.load()
    restored = StyleSearch(rt).get(s['id'])
    assert restored['candidates'][0]['status'] == 'interrupted'
    assert not any(j['status'] == 'queued' for j in rt.queue.by_id().values())


def test_common_failure_stops_only_its_session_and_individual_failure_continues(unlocked, monkeypatch):
    from atelierx.core.i18n import Msg

    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    s = action(unlocked, s, 'propose', count=3)
    s = action(unlocked, s, 'generate')
    service = rt.services['comfyui']
    monkeypatch.setattr(service, 'busy', lambda: False)

    def fail(job):
        raise RuntimeError('invalid image for this candidate')

    monkeypatch.setattr(service, 'submit', fail)
    job = rt.queue.get(s['candidates'][0]['attempts'][0]['id'])
    job['status'] = 'running'
    rt.run_job(job)
    assert rt.queue.get(s['candidates'][1]['attempts'][0]['id'])['status'] == 'queued'

    def common(job):
        raise RuntimeError(Msg('server.image.services.no_answer', 'No answer'))

    monkeypatch.setattr(service, 'submit', common)
    job = rt.queue.get(s['candidates'][1]['attempts'][0]['id'])
    job['status'] = 'running'
    rt.run_job(job)
    s = rt.style_search.get(s['id'])
    assert s['candidates'][2]['status'] == 'interrupted'
    c = s['candidates'][1]
    assert c['attempts'][0]['result_uncertain']
    response = unlocked.post(
        '/api/image/explore/sessions/' + s['id'],
        json={'revision': s['revision'], 'action': 'retry', 'candidates': [c['id']]},
    )
    assert response.status_code == 400
    assert s['scores'][c['id']]['count'] == 0


def test_late_result_is_kept_and_missing_file_blocks_only_comparison(unlocked, monkeypatch):
    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    s = action(unlocked, s, 'propose', count=1)
    s = action(unlocked, s, 'generate')
    service = rt.services['comfyui']
    monkeypatch.setattr(service, 'busy', lambda: False)
    job = rt.queue.get(s['candidates'][0]['attempts'][0]['id'])

    def submit(job):
        job['status'] = 'cancelling'
        return {'id': 'late', 'record': {}}

    monkeypatch.setattr(service, 'submit', submit)
    monkeypatch.setattr(service, 'cancel', lambda job, sent: False)
    monkeypatch.setattr(service, 'poll', lambda job, sent: {'image': _png()})
    job['status'] = 'running'
    rt.run_job(job)
    s = rt.style_search.get(s['id'])
    assert s['candidates'][0]['status'] == 'done'
    from urllib.parse import unquote

    image = rt.gallery.safe_path(unquote(s['candidates'][0]['image_url'].removeprefix('/api/image/files/')))
    image.unlink()
    s = rt.style_search.get(s['id'])
    assert s['candidates'][0]['image_missing']
    assert s['candidates'][0]['status'] == 'done'


def test_nai_fixed_model_no_lora_and_no_network_required(unlocked):
    _setup(unlocked)
    response = unlocked.post(
        '/api/image/explore/sessions',
        json={
            'service': 'novelai',
            'pools': {'artists': pool('a'), 'models': pool('nai-diffusion-4-5-full'), 'loras': []},
        },
    )
    assert response.status_code == 200, response.text
    s = response.json()
    assert s['settings']['seed'] == 104729
    s = action(unlocked, s, 'propose', count=2)
    assert all(
        c['config']['model'] == 'nai-diffusion-4-5-full' and not c['config']['loras']
        for c in s['proposal']['candidates']
    )
    response = unlocked.post(
        '/api/image/explore/sessions/' + s['id'],
        json={
            'revision': s['revision'],
            'action': 'configure',
            'pools': {**s['pools'], 'models': pool('nai-diffusion-5-full')},
        },
    )
    assert response.status_code == 400


def test_partial_request_confirmation_and_asset_family_block(unlocked, monkeypatch):
    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    s = action(
        unlocked,
        s,
        'configure',
        pools={**s['pools'], 'artists': []},
        rules={'artist_min': 0, 'artist_max': 0},
    )
    s = action(unlocked, s, 'propose', count=10)
    assert len(s['proposal']['candidates']) == 1
    response = unlocked.post(
        '/api/image/explore/sessions/' + s['id'], json={'revision': s['revision'], 'action': 'generate'}
    )
    assert response.status_code == 400 and not rt.queue.jobs
    catalog = rt.catalog()
    catalog['families'] = {'models': {catalog['models'][0]: 'sdxl'}}
    monkeypatch.setattr(rt, 'catalog', lambda: catalog)
    response = unlocked.post(
        '/api/image/explore/sessions/' + s['id'],
        json={'revision': s['revision'], 'action': 'generate', 'allow_partial': True},
    )
    assert response.status_code == 400 and not rt.queue.jobs


def test_queue_retry_cannot_bypass_uncertain_result_confirmation_and_cleanup_keeps_cancel(unlocked):
    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    s = action(unlocked, s, 'propose', count=1)
    s = action(unlocked, s, 'generate')
    job = rt.queue.get(s['candidates'][0]['attempts'][0]['id'])
    rt.cancel(job['id'])
    response = unlocked.post('/api/image/jobs/' + job['id'] + '/retry', json={})
    assert response.status_code == 400
    assert response.json()['error']['key'] == 'server.explore.retry_panel'
    rt.remove_finished(job['id'])
    assert rt.style_search.get(s['id'])['candidates'][0]['status'] == 'cancelled'
