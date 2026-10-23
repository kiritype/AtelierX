"""Automatic rounds and refinement use a local queue; no external generation requests."""

import copy
import random

import pytest

from atelierx.image.style_flow import neighbours, readiness, spent
from atelierx.image.style_search import StyleSearch, random_candidate, signature
from atelierx.image.util import atomic_json
from test_single_generation import _setup
from test_style_search import action, create, session

OWNER = 'screen-owner-00000001'


def test_progress_between_generation_and_resume_is_not_an_edit_conflict(unlocked):
    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    s = action(unlocked, s, 'propose', count=3)
    prepared = s
    s = action(unlocked, s, 'generate')
    job = rt.queue.get(s['candidates'][0]['attempts'][0]['id'])
    rt.queue.update(job, status='running', sent=True, prompt_id='remote-id')
    rt.style_search.capture(job)
    # Use exactly the response from generate, before the worker persisted progress.
    resumed = action(unlocked, s, 'resume', owner=OWNER)
    assert len(resumed['candidates']) == 3 and not resumed['flow']['paused']
    duplicate = unlocked.post('/api/image/explore/sessions/' + s['id'], json={
        'action': 'generate', 'revision': prepared['revision'],
    })
    assert duplicate.status_code == 409
    assert len(rt.style_search.get(s['id'])['candidates']) == 3


def test_real_edits_and_wrong_pairs_still_conflict(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    action(unlocked, s, 'automatic', enabled=True, limit=9, count=3)
    conflict = unlocked.post('/api/image/explore/sessions/' + s['id'], json={
        'action': 'automatic', 'revision': s['revision'], 'enabled': False, 'limit': 30, 'count': 3,
    })
    assert conflict.status_code == 409
    current = rt.style_search.get(s['id'])
    wrong_pair = unlocked.post('/api/image/explore/sessions/' + s['id'], json={
        'action': 'evaluate', 'revision': current['revision'], 'choice': 'a',
        'pair': list(reversed(current['pair'])),
    })
    assert wrong_pair.status_code == 409
    assert not rt.style_search.get(s['id'])['events']


def ready_session(client, rt, count=3):
    s = create(client, rt)
    s['rng'] = random.Random(72).getstate()
    s = persist(rt, s)
    s = action(client, s, 'propose', count=count)
    s = action(client, s, 'generate')
    # Store local images and finish queued jobs without invoking a provider.
    for i, c in enumerate(s['candidates']):
        path = rt.gallery.safe_path(f'_lab/{s["id"]}/{i}.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'local-test-image')
        rt.queue.update(
            rt.queue.get(c['attempts'][0]['id']),
            status='done',
            sent=True,
            image_url=f'/api/image/files/_lab/{s["id"]}/{i}.png',
        )
    return rt.style_search.get(s['id'])


def cover(s, tie=False):
    ids = [c['id'] for c in s['candidates']]
    s['events'] = [
        {'pair': [ids[a], ids[b]], 'choice': 'tie' if tie else 'a'}
        for a, b in [(0, 1), (1, 2), (2, 0), (0, 1), (1, 2), (2, 0)]
    ]
    s['pair'] = None
    return s


def persist(rt, s):
    s = copy.deepcopy(s)
    for key in ('revision', 'scores'):
        s.pop(key, None)
    for key in ('used', 'owner', 'readiness'):
        s['flow'].pop(key, None)
    atomic_json(rt.style_search.path(s['id']), s)
    return rt.style_search.get(s['id'])


def test_coverage_requires_distinct_opponents_and_previous_benchmark(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    ids = [c['id'] for c in s['candidates']]
    s['events'] = [{'pair': ids[:2], 'choice': 'a'}] * 4
    assert not readiness(s)['ready']
    s = cover(s)
    assert readiness(s)['ready']
    s['events'][-1]['choice'] = 'bad'
    s['events'][-2]['choice'] = 'skip'
    assert not readiness(s)['ready']
    s = cover(s, tie=True)
    assert readiness(s)['reason'] == 'no_parent'
    s = cover(s)
    old = copy.deepcopy(s['candidates'][0])
    old['id'] = 'old-benchmark'
    s['candidates'].append(old)
    s['rounds'][-1]['benchmarks'] = [old['id']]
    assert not readiness(s)['ready']
    for ident in ids:
        s['events'].append({'pair': [ident, old['id']], 'choice': 'tie'})
    assert readiness(s)['ready']


def test_owner_resume_expiry_and_restart_never_silently_restart(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert not s['flow']['paused'] and s['pair']
    other = unlocked.post(
        '/api/image/explore/sessions/' + s['id'],
        json={'revision': s['revision'], 'action': 'resume', 'owner': OWNER + '-other'},
    )
    assert other.status_code == 409
    clock = rt.style_search.clock()
    rt.style_search.clock = lambda: clock + 20
    s = action(unlocked, s, 'heartbeat', owner=OWNER)
    assert s['flow']['paused'] and s['flow']['owner'] is None
    s = action(unlocked, s, 'resume', owner=OWNER)
    fresh = StyleSearch(rt)
    restored = fresh.get(s['id'])
    assert restored['flow']['paused'] and restored['flow']['owner'] is None
    s = action(unlocked, rt.style_search.get(s['id']), 'leave', owner=OWNER)
    assert s['flow']['paused']


def test_paused_comparisons_appear_without_claiming_owner_or_generating(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    assert s['pair'] and s['flow']['paused'] and s['flow']['owner'] is None
    initial_pair = s['pair']
    s = action(unlocked, s, 'heartbeat', owner=OWNER)
    assert s['pair'] == initial_pair
    s = action(unlocked, s, 'evaluate', choice='a')
    assert s['pair'] and len(s['events']) == 1
    assert s['flow']['paused'] and s['flow']['owner'] is None
    assert len(s['rounds']) == 1 and len(s['candidates']) == 3 and spent(s) == 3
    # A completed refinement must also be presented while awaiting resume.
    ids = [c['id'] for c in s['candidates']]
    s = action(unlocked, s, 'refine', candidate=ids[0], target='artist')
    s['pair'] = None
    s['refinement'].update(base=ids[0], pending=ids[1])
    s = persist(rt, s)
    assert set(s['pair']) == set(ids[:2])
    assert s['flow']['paused'] and s['flow']['owner'] is None and spent(s) == 3


def test_auto_round_is_idempotent_and_never_partially_spends_budget(unlocked):
    _, rt = _setup(unlocked)
    s = persist(rt, cover(ready_session(unlocked, rt)))
    s = action(unlocked, s, 'automatic', enabled=True, limit=5, count=3)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert len(s['rounds']) == 1 and s['flow']['paused'] and spent(s) == 3
    assert s['flow']['reason'] == 'limit_remaining' and 'flow_error' not in s
    s = action(unlocked, s, 'automatic', enabled=True, limit=6, count=3)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert len(s['rounds']) == 2 and spent(s) == 6
    assert s['rounds'][-1]['benchmarks']
    for _ in range(3):
        s = action(unlocked, s, 'heartbeat', owner=OWNER)
    assert len(s['candidates']) == 6 and len(s['rounds']) == 2
    # Undo a determining vote after automatic admission: retain images/history, cancel unsent work.
    s = action(unlocked, s, 'undo')
    assert s['flow']['paused'] and spent(s) == 3
    assert len(s['candidates']) == 6 and len(s['invalidated_rounds']) == 1
    assert all(c['status'] == 'cancelled' for c in s['candidates'][3:])


def test_limit_completion_is_not_an_error_and_survives_resume_and_restart(unlocked):
    _, rt = _setup(unlocked)
    s = persist(rt, cover(ready_session(unlocked, rt)))
    s = action(unlocked, s, 'automatic', enabled=True, limit=3, count=3)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert s['flow']['reason'] == 'limit_reached' and 'flow_error' not in s
    s = action(unlocked, s, 'leave', owner=OWNER)
    restored = StyleSearch(rt).get(s['id'])
    assert restored['flow']['reason'] == 'limit_reached' and restored['flow']['paused']
    # Upgrade a session saved by the previous version with a budget error.
    s['flow']['reason'] = 'blocked'
    s['flow_error'] = {'key': 'server.explore.budget', 'text': 'budget'}
    s = persist(rt, s)
    assert s['flow']['reason'] == 'limit_reached' and 'flow_error' not in s
    s = action(unlocked, s, 'automatic', enabled=True, limit=6, count=3)
    assert s['flow']['paused'] and s['flow']['reason'] == 'resume'
    assert len(s['candidates']) == 3
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert len(s['candidates']) == 6


def test_attempt_budget_refunds_only_definite_unsent_attempts_and_retry_preflight(unlocked, monkeypatch):
    _, rt = _setup(unlocked)
    s = create(unlocked, rt)
    s = action(unlocked, action(unlocked, s, 'propose', count=2), 'generate')
    a, b = [rt.queue.get(c['attempts'][0]['id']) for c in s['candidates']]
    rt.queue.update(a, status='failed')
    rt.queue.update(b, status='failed', sent=True, result_uncertain=True)
    s = rt.style_search.get(s['id'])
    assert spent(s) == 1
    monkeypatch.setattr(rt.queue, 'check_room', lambda count: (_ for _ in ()).throw(ValueError('full')))
    response = unlocked.post(
        '/api/image/explore/sessions/' + s['id'],
        json={'revision': s['revision'], 'action': 'retry', 'confirmed_unknown': True},
    )
    assert response.status_code == 400
    assert [len(c['attempts']) for c in rt.style_search.get(s['id'])['candidates']] == [1, 1]


def test_refinement_changes_always_weights_but_preserves_membership_order_model():
    s = session()
    for plural in ('artists', 'loras'):
        s['pools'][plural][0]['mode'] = 'always'
    c = random_candidate(random.Random(10), s)
    changes = list(neighbours(s, c, 'all'))
    assert changes
    assert any(x['artists'][0]['weight'] != c['artists'][0]['weight'] for x, _ in changes)
    for changed, _ in changes:
        assert changed['model'] == c['model']
        for plural in ('artists', 'loras'):
            assert [x['name'] for x in changed[plural]] == [x['name'] for x in c[plural]]
        assert sum(a != b for plural in ('artists', 'loras') for a, b in zip(changed[plural], c[plural])) == 1
        assert all(x['weight'] == x['clip'] for x in changed['loras'])


def test_refinement_reuses_images_tracks_base_skip_undo_and_stops(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    base = s['candidates'][0]
    variants = list(neighbours(s, base['config'], 'artist'))
    # Use a cached neighbour, preserving all other pool/session details.
    s['candidates'][1]['config'] = variants[0][0]
    s = persist(rt, s)
    s = action(unlocked, s, 'refine', candidate=base['id'], target='artist')
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert set(s['pair']) == {base['id'], s['candidates'][1]['id']} and spent(s) == 3
    s = action(unlocked, s, 'evaluate', choice='skip')
    s = action(unlocked, s, 'heartbeat', owner=OWNER)
    assert s['pair'] and not s['refinement']['seen']
    s = action(unlocked, s, 'evaluate', choice='ab'[s['pair'].index(s['candidates'][1]['id'])])
    assert s['refinement']['base'] == s['candidates'][1]['id']
    s = action(unlocked, s, 'undo')
    assert s['refinement']['base'] == base['id'] and s['flow']['paused']
    s['pair'] = None
    s['refinement']['pending'] = None
    s['refinement']['seen'] = [[base['id'], signature(config)] for config, _ in variants]
    s = persist(rt, s)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert s['flow']['reason'] == 'no_improvement' and s['flow']['paused']


@pytest.mark.parametrize('tie,count,reason', [(True, 3, 'no_parent'), (False, 2, 'too_few')])
def test_no_parent_and_two_candidates_pause(unlocked, tie, count, reason):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt, count)
    if tie:
        s = cover(s, tie=True)
    s = persist(rt, s)
    s = action(unlocked, s, 'resume', owner=OWNER)
    assert s['flow']['paused'] and s['flow']['reason'] == reason
    assert len(s['candidates']) == count


def test_missing_benchmark_cannot_satisfy_later_round_and_editing_holds_owner(unlocked):
    _, rt = _setup(unlocked)
    s = cover(ready_session(unlocked, rt))
    s['rounds'][-1]['benchmarks'] = ['missing-old-image']
    assert readiness(s)['reason'] == 'missing'
    s['rounds'][-1]['benchmarks'] = []
    s = persist(rt, s)
    s = action(unlocked, s, 'automatic', enabled=False, limit=30, count=3)
    s = action(unlocked, s, 'resume', owner=OWNER)
    s = action(unlocked, s, 'automatic', enabled=True, limit=30, count=3)
    s = action(unlocked, s, 'heartbeat', owner=OWNER + '-other')
    assert len(s['rounds']) == 1
    s = action(unlocked, s, 'heartbeat', owner=OWNER, hold=True)
    assert s['flow']['paused'] and len(s['rounds']) == 1


@pytest.mark.parametrize('sent', [False, True])
def test_undo_refinement_cancels_unsent_successor_and_keeps_sent_work(unlocked, sent):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    s['candidates'][0]['config']['artists'] = [{'name': 'a', 'weight': 1.0}]
    s['candidates'][2]['config']['artists'] = [{'name': 'b', 'weight': 1.0}]
    base = s['candidates'][0]
    variants = list(neighbours(s, base['config'], 'artist'))
    s['candidates'][1]['config'] = variants[0][0]
    s = persist(rt, s)
    s = action(unlocked, s, 'refine', candidate=base['id'], target='artist')
    s = action(unlocked, s, 'resume', owner=OWNER)
    s = action(unlocked, s, 'evaluate', choice='tie')
    s = action(unlocked, s, 'heartbeat', owner=OWNER)
    derived = s['candidates'][-1]
    assert derived.get('origin_event') == len(s['events'])
    job = rt.queue.get(derived['attempts'][-1]['id'])
    rt.queue.update(job, status='running' if sent else 'queued', sent=sent)
    s = action(unlocked, rt.style_search.get(s['id']), 'undo')
    assert s['candidates'][-1]['status'] == ('running' if sent else 'cancelled')
    assert spent(s) == (4 if sent else 3)
    assert s['flow']['paused'] and s['refinement']['base'] == base['id']


def test_common_failure_pauses_auto_and_refinement_bad_requires_base_choice(unlocked):
    _, rt = _setup(unlocked)
    s = ready_session(unlocked, rt)
    s = action(unlocked, s, 'resume', owner=OWNER)
    job = rt.queue.get(s['candidates'][0]['attempts'][0]['id'])
    rt.style_search.failed(job, ConnectionError('connection lost'))
    s = rt.style_search.get(s['id'])
    assert s['flow']['paused'] and s['flow']['reason'] == 'blocked'
    base = s['candidates'][0]
    s['candidates'][1]['config'] = next(neighbours(s, base['config'], 'artist'))[0]
    s = persist(rt, s)
    s = action(unlocked, s, 'refine', candidate=base['id'], target='artist')
    s = action(unlocked, s, 'resume', owner=OWNER)
    s = action(unlocked, s, 'evaluate', choice='bad')
    assert s['flow']['reason'] == 'choose_base' and s['flow']['paused']
    s = action(unlocked, s, 'leave', owner=OWNER)
    assert s['flow']['reason'] == 'choose_base'
    response = unlocked.post(
        '/api/image/explore/sessions/' + s['id'],
        json={'action': 'resume', 'revision': s['revision'], 'owner': OWNER},
    )
    assert response.status_code == 400


def test_split_lora_refinement_moves_one_component_on_user_grid():
    s = session()
    s['rules'].update(split_clip=True, lora_min=1, lora_max=1, lora_step=0.2, clip_step=0.2)
    s['pools']['loras'][0]['mode'] = 'always'
    c = random_candidate(random.Random(2), s)
    variants = list(neighbours(s, c, 'lora'))
    assert variants
    for changed, _ in variants:
        before, after = c['loras'][0], changed['loras'][0]
        assert changed['artists'] == c['artists'] and before['name'] == after['name']
        diffs = [abs(after[k] - before[k]) for k in ('weight', 'clip')]
        assert sum(d > 1e-6 for d in diffs) == 1 and sum(diffs) == pytest.approx(0.2)
