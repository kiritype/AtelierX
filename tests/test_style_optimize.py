"""Independent budgets and score-driven suggestions without external generation."""

import copy

from atelierx.image.style_flow import spent
from atelierx.image.style_optimize import group_key, suggestions
from test_single_generation import _setup
from test_style_flow import OWNER, cover, persist, ready_session
from test_style_search import action


def finish(rt, s, c):
    path = rt.gallery.safe_path(f'_lab/{s["id"]}/{c["id"]}.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'image')
    rt.queue.update(
        rt.queue.get(c['attempts'][-1]['id']),
        status='done',
        sent=True,
        image_url=f'/api/image/files/_lab/{s["id"]}/{c["id"]}.png',
    )


def test_exploration_transitions_and_optimization_has_its_own_limit(unlocked):
    _, rt = _setup(unlocked)
    s = persist(rt, cover(ready_session(unlocked, rt)))
    assert s['flow']['limit'] == 30 and s['flow']['optimize_limit'] == 10
    s = action(unlocked, s, 'automatic', enabled=True, limit=3, optimize_limit=1, count=3)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert s['flow']['mode'] == 'refine' and s['refinement']['automatic']
    assert len(s['rounds']) == 1 and len(s['candidates']) == 4
    assert spent(s, 'explore') == 3 and spent(s, 'refine') == 1
    roots = s['refinement']['groups']
    by_id = {c['id']: c for c in s['candidates']}
    assert len({group_key(by_id[g['base']]['config']) for g in roots}) == len(roots)
    finish(rt, s, s['candidates'][-1])
    s = rt.style_search.get(s['id'])
    assert s['pair']
    # Repeated heartbeat cannot reserve another optimization while evaluation is pending.
    for _ in range(3):
        s = action(unlocked, s, 'heartbeat', owner=OWNER)
    assert len(s['candidates']) == 4
    s = action(unlocked, s, 'evaluate', choice='tie')
    s = action(unlocked, s, 'heartbeat', owner=OWNER)
    assert s['flow']['paused'] and s['flow']['reason'] == 'limit_reached'
    assert 'flow_error' not in s and spent(s, 'explore') == 3 and spent(s, 'refine') == 1


def test_elo_target_uses_only_identical_compositions_and_user_grid(unlocked, monkeypatch):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    base = s['candidates'][0]
    base['config']['artists'] = [{'name': s['pools']['artists'][0]['name'], 'weight': 0.8}]
    base['config']['loras'] = []
    base['config']['model'] = s['pools']['models'][0]['name']
    samples = [base]
    for i, weight in enumerate([1.2, 1.1]):
        c = copy.deepcopy(base)
        c['id'] = f'sample-{i}'
        c['config']['artists'][0]['weight'] = weight
        samples.append(c)
    foreign = copy.deepcopy(base)
    foreign['id'] = 'foreign'
    foreign['config']['model'] = 'another-model'
    s['candidates'] = samples + [foreign]
    s['rules'].update(artist_low=0.8, artist_high=1.2, artist_step=0.1, artist_min=1)
    scores = {
        c['id']: {'score': value, 'count': 5} for c, value in zip(s['candidates'], [1000, 1400, 1300, 9000])
    }
    monkeypatch.setattr('atelierx.image.style_search.ranking', lambda _: scores)
    config, reason = next(suggestions(s, base))
    assert reason == 'elo weighted target'
    assert config['artists'][0]['weight'] == 1.1
    assert group_key(config) == group_key(base['config'])
    # An always-included artist keeps membership, while weights can still change.
    s['pools']['artists'][0]['mode'] = 'always'
    assert next(suggestions(s, base))[0]['artists'][0]['weight'] == 1.1


def test_legacy_phase_migration_pauses_and_does_not_double_charge(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    s['schema_version'] = 2
    s['flow'].pop('optimize_limit')
    s['flow'].update(paused=False, limit=40)
    for c in s['candidates']:
        c.pop('phase', None)
    s['candidates'][-1]['origin_event'] = 0
    s = persist(rt, s)
    assert s['schema_version'] == 3 and s['flow']['paused']
    assert s['flow']['limit'] == 40 and s['flow']['optimize_limit'] == 10
    assert s['flow']['explore_used'] == 2 and s['flow']['optimize_used'] == 1
    assert len(s['candidates']) == 3


def test_optimization_undo_restores_group_and_cancels_unsent_successor(unlocked):
    _, rt = _setup(unlocked)
    s = persist(rt, cover(ready_session(unlocked, rt)))
    s = action(unlocked, s, 'optimize')
    s = action(unlocked, s, 'resume', owner=OWNER)
    finish(rt, s, s['candidates'][-1])
    s = rt.style_search.get(s['id'])
    before = copy.deepcopy(s['refinement'])
    s = action(unlocked, s, 'evaluate', choice='a')
    s = action(unlocked, s, 'heartbeat', owner=OWNER)
    s = action(unlocked, s, 'undo')
    assert s['refinement'] == before and s['flow']['paused']
    assert spent(s, 'refine') == 1


def test_cached_optimization_is_free_and_bad_moves_to_next_group(unlocked):
    _, rt = _setup(unlocked)
    s = persist(rt, cover(ready_session(unlocked, rt)))
    s = action(unlocked, s, 'optimize')
    base = next(c for c in s['candidates'] if c['id'] == s['refinement']['base'])
    cached = copy.deepcopy(base)
    cached.update(id='cached-neighbour', config=next(suggestions(s, base))[0], phase='explore')
    cached['attempts'] = []
    s['candidates'].append(cached)
    s = persist(rt, s)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert 'cached-neighbour' in s['pair'] and spent(s, 'refine') == 0
    previous = s['refinement']['cursor']
    s = action(unlocked, s, 'evaluate', choice='bad')
    s = action(unlocked, s, 'heartbeat', owner=OWNER)
    assert s['refinement']['groups'][previous]['done']
    assert s['refinement']['cursor'] != previous or s['flow']['reason'] == 'no_improvement'


def test_retry_is_charged_to_original_phase(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    c = s['candidates'][0]
    rt.queue.update(rt.queue.get(c['attempts'][0]['id']), status='failed', sent=True)
    s = rt.style_search.get(s['id'])
    s['flow'].update(mode='refine', optimize_limit=0, limit=4)
    s['refinement'] = {'base': s['candidates'][1]['id'], 'target': 'all', 'seen': [], 'pending': None}
    s = persist(rt, s)
    s = action(unlocked, s, 'retry', candidates=[c['id']])
    assert spent(s, 'explore') == 4 and spent(s, 'refine') == 0
