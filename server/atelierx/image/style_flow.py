"""Style builder progression, request accounting and single-screen automatic admission."""

import copy
import random
import time
import uuid

from ..core.i18n import AppError, Msg, message_of, wire
from .util import atomic_json

ACTIVE = ('queued', 'running', 'cancelling')
SCORED = ('a', 'b', 'tie')
LEASE_SECONDS = 12


def resume_reason(session):
    if session['flow'].get('reason') in ('limit_reached', 'limit_remaining'):
        return session['flow']['reason']
    return (
        'choose_base'
        if session.get('refinement', {}).get('needs_base') and session['flow']['mode'] == 'refine'
        else 'resume'
    )


def available(session):
    return [
        c
        for c in session['candidates']
        if c['status'] == 'done' and c.get('image_url') and not c.get('image_missing')
    ]


def parents(session):
    from .style_search import ranking, valid_config

    scores = ranking(session)
    return [
        c
        for c in available(session)
        if valid_config(c['config'], session)
        and scores[c['id']]['count'] >= 3
        and scores[c['id']]['wins'] >= 1
        and (
            c.get('include_parent')
            or not (scores[c['id']]['bad'] >= 2 and scores[c['id']]['bad'] >= scores[c['id']]['wins'])
        )
    ]


def readiness(session):
    from .style_search import ranking

    current = session['rounds'][-1] if session['rounds'] else {'ids': []}
    ids = set(current['ids'])
    done = available(session)
    new = [c for c in done if c['id'] in ids]
    scores = ranking(session)
    opponents = {c['id']: set() for c in done}
    for e in session['events']:
        if e.get('undone') or e['choice'] not in SCORED:
            continue
        a, b = e['pair']
        if a in opponents and b in opponents:
            opponents[a].add(b)
            opponents[b].add(a)
    old = set(current.get('benchmarks', [])) & set(opponents)
    covered = {
        c['id']: scores[c['id']]['count'] >= 3
        and len(opponents[c['id']]) >= 2
        and (not old or bool(opponents[c['id']] & old))
        for c in new
    }
    reason = 'ready'
    if any(c['status'] in ACTIVE for c in session['candidates'] if c['id'] in ids):
        reason = 'generating'
    elif not new or len(done) < 3:
        reason = 'too_few'
    elif current.get('benchmarks') and not old:
        reason = 'missing'
    elif not all(covered.values()):
        reason = 'evaluating'
    elif not parents(session):
        reason = 'no_parent'
    return {
        'ready': reason == 'ready',
        'reason': reason,
        'covered': sum(covered.values()),
        'total': len(new),
        'opponents': {k: sorted(v) for k, v in opponents.items()},
    }


def spent(session, phase=None):
    return sum(
        bool(
            a.get('sent')
            or a.get('prompt_id')
            or a.get('result_uncertain')
            or a['status'] in ACTIVE
            or a['status'] == 'done'
            or (a['status'] == 'failed' and 'sent' not in a)
        )
        for c in session['candidates']
        if phase is None or c.get('phase', 'explore') == phase
        for a in c['attempts']
    )


def neighbours(session, config, target):
    """A deterministic coordinate walk; 'always' freezes membership, not refinement weights."""
    from .style_search import valid_config

    rules = session['rules']
    for kind, plural in [('artist', 'artists'), ('lora', 'loras')]:
        if target not in ('all', kind):
            continue
        for i, item in enumerate(config[plural]):
            for field in ['weight', 'clip'] if kind == 'lora' and rules['split_clip'] else ['weight']:
                step = rules[('clip' if field == 'clip' else kind) + '_step']
                for sign in (-1, 1):
                    changed = copy.deepcopy(config)
                    changed[plural][i][field] = round(item[field] + sign * step, 8)
                    if kind == 'lora' and not rules['split_clip']:
                        changed[plural][i]['clip'] = changed[plural][i]['weight']
                    if valid_config(changed, session) and changed != config:
                        yield (
                            changed,
                            f'{item["name"]}: {field} {item[field]:g} → {changed[plural][i][field]:g}',
                        )


class StyleFlowMixin:
    def init_flow(self):
        self.boot = uuid.uuid4().hex
        self.leases = {}
        self.clock = time.monotonic

    def normalize_flow(self, s):
        migrating = s.get('schema_version', 1) < 3
        s['schema_version'] = 3
        flow = s.setdefault(
            'flow',
            {
                'enabled': True,
                'limit': 30,
                'count': 10,
                'paused': True,
                'reason': 'resume',
                'mode': 'explore',
            },
        )
        flow.setdefault('optimize_limit', 10)
        for c in s['candidates']:
            c.setdefault('phase', 'refine' if 'origin_event' in c else 'explore')
        if migrating:
            flow.update(paused=True, reason='resume')
            if flow['mode'] == 'refine' and s.get('refinement') and not s['refinement'].get('automatic'):
                s['refinement']['upgrade_pending'] = True
        error = s.get('flow_error')
        if isinstance(error, dict) and error.get('key') == 'server.explore.budget':
            self.limit_pause(s)
        if flow['reason'] in ('limit_reached', 'limit_remaining'):
            count = 1 if flow['mode'] == 'refine' else flow['count']
            if spent(s, flow['mode']) + count <= self.phase_limit(s):
                flow['reason'] = 'resume'
        if flow.get('boot') != self.boot:
            flow.update(boot=self.boot, paused=True, reason=resume_reason(s))
        return s

    def owner_alive(self, ident):
        lease = self.leases.get(ident)
        return bool(lease and self.clock() - lease[1] < LEASE_SECONDS)

    def public_flow(self, s):
        f = s['flow']
        if not self.owner_alive(s['id']) and not f['paused']:
            f.update(paused=True, reason=resume_reason(s))
        return {
            **f,
            'used': spent(s),
            'explore_used': spent(s, 'explore'),
            'optimize_used': spent(s, 'refine'),
            'owner': self.leases.get(s['id'], [None])[0] if self.owner_alive(s['id']) else None,
            'readiness': readiness(s),
        }

    def phase_limit(self, s, phase=None):
        return s['flow']['optimize_limit' if (phase or s['flow']['mode']) == 'refine' else 'limit']

    def budget(self, s, count, phase=None):
        phase = phase or s['flow']['mode']
        if spent(s, phase) + count > self.phase_limit(s, phase):
            raise ValueError(Msg('server.explore.budget', 'The session generation limit would be exceeded.'))

    def limit_pause(self, s):
        s['flow'].update(
            paused=True,
            reason='limit_reached'
            if spent(s, s['flow']['mode']) >= self.phase_limit(s)
            else 'limit_remaining',
        )
        s.pop('flow_error', None)

    def before_submit(self, job):
        if not job.get('snapshot', {}).get('style_session'):
            return True
        with self.lock:
            if job['status'] == 'cancelling':
                return False
            # Persist BEFORE the remote call: uncertainty after a crash must consume its reservation.
            if job.get('service') == 'novelai':
                self.runtime.services['novelai'].key()
            elif job.get('service') == 'comfyui':
                self.runtime.services['comfyui'].graph(job)
            self.runtime.queue.update(job, sent=True)
            self.capture(job)
            return True

    def flow_action(self, s, body):
        from .style_search import invalid

        action, f = body['action'], s['flow']
        owner = body.get('owner')
        if action in ('heartbeat', 'resume', 'leave'):
            if not isinstance(owner, str) or not 16 <= len(owner) <= 80:
                invalid('screen owner')
            lease = self.leases.get(s['id'])
            if action == 'leave':
                if lease and lease[0] == owner:
                    self.leases.pop(s['id'], None)
                    f.update(paused=True, reason=resume_reason(s))
                return
            if action == 'resume':
                if f['mode'] == 'refine' and s['refinement'].get('needs_base'):
                    invalid('choose another refinement base or return to exploration')
                if self.owner_alive(s['id']) and lease[0] != owner:
                    raise AppError(
                        Msg('server.explore.owner', 'Another screen owns automatic progression.'), 409
                    )
                if s.get('refinement', {}).get('upgrade_pending'):
                    self.begin_optimization(s)
                    if f['reason'] == 'no_parent':
                        return
                self.leases[s['id']] = (owner, self.clock())
                f.update(paused=False, reason='evaluating')
            elif lease and lease[0] == owner and self.owner_alive(s['id']):
                self.leases[s['id']] = (owner, self.clock())
            else:
                if not self.owner_alive(s['id']):
                    f.update(paused=True, reason=resume_reason(s))
                return
            if action == 'heartbeat' and body.get('hold'):
                f.update(paused=True, reason='paused')
            self.advance(s)
        elif action == 'pause':
            f.update(paused=True, reason='paused')
        elif action == 'automatic':
            if type(body.get('enabled')) is not bool:
                invalid('automatic')
            limit, count = body.get('limit'), body.get('count', f['count'])
            optimize_limit = body.get('optimize_limit', f['optimize_limit'])
            if (
                type(limit) is not int
                or not 1 <= limit <= 5000
                or type(count) is not int
                or not 1 <= count <= 5000
                or type(optimize_limit) is not int
                or not 0 <= optimize_limit <= 5000
            ):
                invalid('limit/count (1–5000)')
            f.update(enabled=body['enabled'], limit=limit, count=count, optimize_limit=optimize_limit)
        elif action == 'optimize':
            if any(c['status'] in ACTIVE for c in s['candidates']):
                invalid('wait for generation')
            self.begin_optimization(s)
        elif action == 'refine':
            c = next((c for c in available(s) if c['id'] == body.get('candidate')), None)
            target = body.get('target', 'all')
            if (
                not c
                or target not in ('all', 'artist', 'lora')
                or (s['service'] == 'novelai' and target == 'lora')
            ):
                invalid('refinement candidate/target')
            f.update(mode='refine', paused=True, reason='resume')
            s['refinement'] = {'base': c['id'], 'target': target, 'seen': [], 'pending': None}
            s['pair'] = None
            s.pop('proposal', None)
        elif action == 'explore':
            f.update(mode='explore', paused=True, reason='resume')
            s['pair'] = None
            s.pop('proposal', None)
        elif action == 'refine_next':
            if f['mode'] != 'refine':
                invalid('refinement mode')
            self.refine_next(s)

    def present_comparison(self, s):
        """Present finished images independently of permission to generate more."""
        self.pair(s, False)
        # A submitted refinement may finish while automatic admission is disabled/paused.
        # Present its comparison without reserving another request.
        if s['flow']['mode'] == 'refine' and not s['pair'] and s['refinement']['pending']:
            ids = {c['id'] for c in available(s)}
            r = s['refinement']
            if r['base'] in ids and r['pending'] in ids:
                self.refine_pair(s, r['base'], r['pending'])

    def advance(self, s):
        from .style_search import propose

        f = s['flow']
        self.present_comparison(s)
        if not f['enabled'] or f['paused'] or not self.owner_alive(s['id']):
            if not f['paused']:
                f['reason'] = 'evaluating' if s['pair'] else readiness(s)['reason']
            return
        try:
            s.pop('flow_error', None)
            if f['mode'] == 'refine':
                self.refine_next(s)
                return
            self.pair(s, False)
            ready = readiness(s)
            f['reason'] = ready['reason']
            if not ready['ready']:
                if ready['reason'] in ('too_few', 'no_parent', 'missing'):
                    f['paused'] = True
                return
            if any(c['status'] in ACTIVE for c in s['candidates']):
                f['reason'] = 'generating'
                return
            if spent(s, 'explore') + f['count'] > f['limit']:
                if f['optimize_limit']:
                    self.begin_optimization(s)
                    if not f['paused']:
                        self.refine_next(s)
                else:
                    self.limit_pause(s)
                return
            self.budget(s, f['count'])
            self.check_assets(s)
            if not s.get('proposal'):
                candidates, rng = propose(s, f['count'])
                s['proposal'] = {'requested': f['count'], 'candidates': candidates, 'rng': rng}
            if len(s['proposal']['candidates']) < s['proposal']['requested']:
                f.update(paused=True, reason='partial')
                return
            self.enqueue_plan(s)
            f['reason'] = 'generating'
        except (ValueError, AppError) as exc:
            if getattr(message_of(exc), 'key', None) == 'server.explore.budget':
                self.limit_pause(s)
                return
            f.update(paused=True, reason='blocked')
            s['flow_error'] = wire(message_of(exc))

    def refine_next(self, s):
        from .style_search import signature

        r, f = s['refinement'], s['flow']
        if r.get('automatic') and r.get('rotate'):
            self.rotate_optimization(s)
            if f['paused']:
                return
        if r.get('needs_base'):
            f.update(paused=True, reason='choose_base')
            return
        by_id = {c['id']: c for c in s['candidates']}
        base = by_id[r['base']]
        if base not in available(s):
            f.update(paused=True, reason='missing')
            return
        if s['pair']:
            return
        if r['pending']:
            candidate = by_id[r['pending']]
        else:
            candidate = None
            from .style_optimize import suggestions

            options = (
                suggestions(s, base, r['target'])
                if r.get('automatic')
                else neighbours(s, base['config'], r['target'])
            )
            for config, desc in options:
                key = [r['base'], signature(config)]
                if key in r['seen']:
                    continue
                if (
                    r.get('automatic')
                    and sorted([signature(base['config']), signature(config)]) in r['compared']
                ):
                    continue
                candidate = next((c for c in s['candidates'] if signature(c['config']) == key[1]), None)
                if candidate is None:
                    self.budget(s, 1)
                    candidate = {
                        'id': uuid.uuid4().hex,
                        'config': config,
                        'parent_id': base['id'],
                        'origin_event': len(s['events']),
                        'change': desc,
                        'status': 'planned',
                        'attempts': [],
                        'phase': 'refine',
                    }
                    s['proposal'] = {
                        'requested': 1,
                        'candidates': [candidate],
                        'rng': s['rng'],
                        'refine': True,
                    }
                    self.enqueue_plan(s)
                r['pending'] = candidate['id']
                break
            if candidate is None:
                if r.get('automatic'):
                    r['groups'][r['cursor']]['done'] = True
                    r['rotate'] = True
                    self.rotate_optimization(s)
                    if not f['paused']:
                        self.refine_next(s)
                    return
                f.update(paused=True, reason='no_improvement')
                return
        if candidate in available(s):
            self.refine_pair(s, base['id'], candidate['id'])
            f['reason'] = 'evaluating'
        elif candidate['status'] in ACTIVE:
            f['reason'] = 'generating'
        else:
            f.update(paused=True, reason='missing')

    def refine_pair(self, s, base, candidate):
        from .style_search import _tuple

        rng = random.Random()
        rng.setstate(_tuple(s['rng']))
        s['pair'] = [base, candidate]
        rng.shuffle(s['pair'])
        s['rng'] = rng.getstate()

    def refine_vote(self, s, event):
        from .style_search import signature

        r = s['refinement']
        event['refinement_before'] = copy.deepcopy(r)
        if event['choice'] == 'skip':
            return
        if event['choice'] == 'bad':
            if r.get('automatic'):
                r['groups'][r['cursor']]['done'] = True
                r.update(rotate=True, pending=None)
                return
            r.update(needs_base=True, pending=None)
            s['flow'].update(paused=True, reason='choose_base')
            return
        other = next(x for x in event['pair'] if x != r['base'])
        c = next(c for c in s['candidates'] if c['id'] == other)
        r['seen'].append([r['base'], signature(c['config'])])
        winner = event['pair'][0 if event['choice'] == 'a' else 1] if event['choice'] != 'tie' else r['base']
        r.update(base=winner, pending=None)
        if r.get('automatic'):
            by_id = {c['id']: c for c in s['candidates']}
            r['compared'].append(sorted(signature(by_id[x]['config']) for x in event['pair']))
            r['groups'][r['cursor']]['base'] = winner
            r['rotate'] = True

    def begin_optimization(self, s):
        from .style_optimize import group_key
        from .style_search import ranking

        scores = ranking(s)
        groups, seen = [], set()
        for c in sorted(parents(s), key=lambda c: -scores[c['id']]['score']):
            key = group_key(c['config'])
            if key in seen:
                continue
            seen.add(key)
            groups.append({'base': c['id'], 'done': False})
            if len(groups) == 3:
                break
        if not groups:
            s['flow'].update(paused=True, reason='no_parent')
            return
        s['flow'].update(mode='refine', reason='evaluating')
        s['pair'] = None
        s.pop('proposal', None)
        s['refinement'] = {
            'base': groups[0]['base'],
            'target': 'all',
            'seen': [],
            'pending': None,
            'automatic': True,
            'groups': groups,
            'cursor': 0,
            'compared': [],
        }

    def rotate_optimization(self, s):
        r = s['refinement']
        for offset in range(1, len(r['groups']) + 1):
            index = (r['cursor'] + offset) % len(r['groups'])
            group = r['groups'][index]
            if not group['done']:
                r.update(cursor=index, base=group['base'], pending=None, rotate=False)
                return
        s['flow'].update(paused=True, reason='no_improvement')

    def undo_flow(self, s, index, event):
        s['flow'].update(paused=True, reason='paused')
        if event.get('refinement_before'):
            s['refinement'] = copy.deepcopy(event['refinement_before'])
            s['flow']['mode'] = 'refine'
        invalidated = {c['id'] for c in s['candidates'] if c.get('origin_event', -1) > index}
        for round_ in s['rounds']:
            if round_['start_event'] > index:
                round_['invalidated'] = True
                invalidated.update(round_['ids'])
        jobs = self.runtime.queue.by_id()
        for c in s['candidates']:
            if c['id'] in invalidated:
                for a in c['attempts']:
                    job = jobs.get(a['id'])
                    if job and not job.get('sent') and job['status'] in ACTIVE:
                        self.runtime.cancel(job['id'])
        s.pop('proposal', None)
        s.setdefault('invalidated_rounds', []).extend(r for r in s['rounds'] if r.get('invalidated'))
        s['rounds'] = [r for r in s['rounds'] if not r.get('invalidated')]
        atomic_json(self.path(s['id']), s)
