"""Persistent style pools, independent sessions and preference search. No network in the search engine."""

import copy
import json
import math
import random
import secrets
import uuid
from collections import Counter
from urllib.parse import unquote

import httpx

from ..core import revisions
from ..core.i18n import Msg, message_of, wire
from . import library
from .job_queue import MAX_QUEUED
from .style_flow import StyleFlowMixin, parents, readiness
from .util import atomic_json, now, read_json
from .workflow import validate_settings

DEFAULT_SCENE = '1girl, adult woman, short black hair, blue eyes, white shirt, blue jacket, black pants, standing, upper body, front view, simple gray background'
DEFAULT_RULES = {
    'artist_min': 1,
    'artist_max': 3,
    'lora_min': 0,
    'lora_max': 2,
    'artist_low': 0.8,
    'artist_high': 1.2,
    'artist_step': 0.1,
    'lora_low': 0.4,
    'lora_high': 1.0,
    'lora_step': 0.1,
    'split_clip': False,
    'clip_low': 0.4,
    'clip_high': 1.0,
    'clip_step': 0.1,
}


def invalid(detail):
    raise ValueError(Msg('server.explore.invalid', 'Check the exploration settings: {detail}', detail=detail))


def clean_pool(items):
    if not isinstance(items, list) or len(items) > 100000:
        invalid('pool')
    out = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            invalid('pool item')
        name = item['name'].strip()
        mode = item.get('mode', 'candidate')
        if not name or len(name) > 500 or mode not in ('always', 'candidate', 'exclude'):
            invalid('pool item')
        out.setdefault(name, {'name': name, 'mode': mode})
    return list(out.values())


def validate_rules(rules, pools, service):
    if not isinstance(rules, dict):
        invalid('rules')
    value = {**DEFAULT_RULES, **rules}
    if type(value['split_clip']) is not bool:
        invalid('split CLIP')
    for kind, plural in [('artist', 'artists'), ('lora', 'loras')]:
        pool = [x for x in pools[plural] if x['mode'] != 'exclude']
        required = sum(x['mode'] == 'always' for x in pool)
        # Only unspecified defaults adapt to a small pool.
        for edge in ('min', 'max'):
            key = kind + '_' + edge
            if key not in rules:
                value[key] = min(value[key], len(pool))
            if type(value[key]) is not int or value[key] < 0:
                invalid(key)
        if not required <= value[kind + '_max'] <= len(pool) or value[kind + '_min'] > value[kind + '_max']:
            invalid(kind + ' count / always included')
        if kind == 'lora' and value['lora_max'] > 16:
            invalid('LoRA maximum 16 (backend limit)')
        if service == 'novelai' and kind == 'lora' and value['lora_max']:
            invalid('NovelAI has no LoRA')
    for kind in ('artist', 'lora', 'clip'):
        low, high, step = (value[kind + '_' + k] for k in ('low', 'high', 'step'))
        if any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in (low, high, step)
        ):
            invalid(kind + ' weights')
        if low > high or step <= 0 or (kind != 'artist' and (low < -10 or high > 10)):
            invalid(kind + ' range')
    return value


def weights(rules, kind):
    low, high, step = (rules[kind + '_' + k] for k in ('low', 'high', 'step'))
    return low, max(0, math.floor((high - low) / step + 1e-8)), step


def choose(rng, pool, low, high):
    fixed = [x['name'] for x in pool if x['mode'] == 'always']
    choices = [x['name'] for x in pool if x['mode'] == 'candidate']
    count = rng.randint(max(low, len(fixed)), high)
    return sorted(fixed + rng.sample(choices, count - len(fixed)))


def random_candidate(rng, session):
    pools, rules = session['pools'], session['rules']
    models = [x['name'] for x in pools['models'] if x['mode'] != 'exclude']
    forced = [x['name'] for x in pools['models'] if x['mode'] == 'always']
    if not models or len(forced) > 1:
        invalid('choose one model per candidate')
    candidate = {'model': rng.choice(forced or models), 'artists': [], 'loras': []}
    for kind, plural in [('artist', 'artists'), ('lora', 'loras')]:
        for name in choose(rng, pools[plural], rules[kind + '_min'], rules[kind + '_max']):
            low, count, step = weights(rules, kind)
            w = round(low + rng.randint(0, count) * step, 8)
            item = {'name': name, 'weight': w}
            if kind == 'lora':
                low, count, step = weights(rules, 'clip')
                item['clip'] = round(low + rng.randint(0, count) * step, 8) if rules['split_clip'] else w
            candidate[plural].append(item)
    return candidate


def signature(config):
    return json.dumps(config, sort_keys=True, separators=(',', ':'))


def ranking(session):
    scores = {c['id']: {'score': 1000.0, 'count': 0, 'wins': 0, 'bad': 0} for c in session['candidates']}
    for event in session['events']:
        if event.get('undone') or event['choice'] == 'skip':
            continue
        a, b = (scores[x] for x in event['pair'])
        if event['choice'] == 'bad':
            a['bad'] += 1
            b['bad'] += 1
            continue
        expected = 1 / (1 + 10 ** ((b['score'] - a['score']) / 400))
        outcome = {'a': 1, 'b': 0, 'tie': 0.5}[event['choice']]
        delta = 24 * (outcome - expected)
        a['score'] += delta
        b['score'] -= delta
        for score in (a, b):
            score['count'] += 1
        if outcome == 1:
            a['wins'] += 1
        if outcome == 0:
            b['wins'] += 1
    return scores


def valid_config(config, session):
    rules, pools = session['rules'], session['pools']
    models = {x['name'] for x in pools['models'] if x['mode'] != 'exclude'}
    forced_models = {x['name'] for x in pools['models'] if x['mode'] == 'always'}
    if config['model'] not in models or (forced_models and config['model'] not in forced_models):
        return False
    for kind, plural in [('artist', 'artists'), ('lora', 'loras')]:
        items = config[plural]
        allowed = {x['name'] for x in pools[plural] if x['mode'] != 'exclude'}
        required = {x['name'] for x in pools[plural] if x['mode'] == 'always'}
        names = {x['name'] for x in items}
        if not rules[kind + '_min'] <= len(items) <= rules[kind + '_max'] or len(names) != len(items):
            return False
        if not required <= names <= allowed:
            return False
        for x in items:
            low, count, step = weights(rules, kind)
            if not low - 1e-8 <= x['weight'] <= low + count * step + 1e-8:
                return False
            if abs((x['weight'] - low) / step - round((x['weight'] - low) / step)) > 1e-6:
                return False
            if kind == 'lora':
                if not rules['split_clip'] and x['clip'] != x['weight']:
                    return False
                if rules['split_clip']:
                    low, count, step = weights(rules, 'clip')
                    if not low - 1e-8 <= x['clip'] <= low + count * step + 1e-8:
                        return False
                    if abs((x['clip'] - low) / step - round((x['clip'] - low) / step)) > 1e-6:
                        return False
    return True


def mutate(rng, parent, session, weight_only):
    # Group equivalent moves before sampling. A full artist dictionary must not produce
    # one deep copy and one full-pool validation per possible replacement.
    config, rules, pools = parent['config'], session['rules'], session['pools']
    groups = []
    for kind, plural in [('artist', 'artists'), ('lora', 'loras')]:
        required = {x['name'] for x in pools[plural] if x['mode'] == 'always'}
        existing = {x['name'] for x in config[plural]}
        choices = [x['name'] for x in pools[plural] if x['mode'] == 'candidate' and x['name'] not in existing]
        for i, item in enumerate(config[plural]):
            if item['name'] in required:
                continue
            if weight_only:
                for field in ['weight', 'clip'] if kind == 'lora' and rules['split_clip'] else ['weight']:
                    low, count, step = weights(rules, 'clip' if field == 'clip' else kind)
                    values = [round(item[field] + d * step, 8) for d in (-1, 1)]
                    values = [v for v in values if low - 1e-8 <= v <= low + count * step + 1e-8]
                    if values:
                        groups.append((kind, plural, i, field, values))
            else:
                if choices:
                    groups.append((kind, plural, i, 'replace', choices))
                if len(existing) > rules[kind + '_min']:
                    groups.append((kind, plural, i, 'remove', [None]))
        if not weight_only and choices and len(existing) < rules[kind + '_max']:
            groups.append((kind, plural, None, 'add', choices))
    if not weight_only and not any(x['mode'] == 'always' for x in pools['models']):
        choices = [
            x['name'] for x in pools['models'] if x['mode'] == 'candidate' and x['name'] != config['model']
        ]
        if choices:
            groups.append(('model', 'models', None, 'replace', choices))
    if not groups:
        return None, None
    offset = rng.randrange(sum(len(g[4]) for g in groups))
    for kind, plural, i, op, values in groups:
        if offset >= len(values):
            offset -= len(values)
            continue
        value = values[offset]
        changed = copy.deepcopy(config)
        if kind == 'model':
            changed['model'] = value
        elif op == 'replace':
            changed[plural][i]['name'] = value
        elif op == 'remove':
            changed[plural].pop(i)
        elif op == 'add':
            low, count, step = weights(rules, kind)
            w = round(low + rng.randint(0, count) * step, 8)
            item = {'name': value, 'weight': w}
            if kind == 'lora':
                cl, cc, cs = weights(rules, 'clip')
                item['clip'] = round(cl + rng.randint(0, cc) * cs, 8) if rules['split_clip'] else w
            changed[plural].append(item)
        else:
            changed[plural][i][op] = value
            if kind == 'lora' and not rules['split_clip']:
                changed[plural][i]['clip'] = value
        for key in ('artists', 'loras'):
            changed[key].sort(key=lambda x: x['name'])
        return (changed, kind + ' ' + op) if valid_config(changed, session) else (None, None)
    return None, None


def propose(session, count):
    if type(count) is not int or not 1 <= count <= MAX_QUEUED:
        invalid('candidate count (1–5000)')
    rng = random.Random()
    rng.setstate(_tuple(session['rng']))
    scores = ranking(session)
    parents = [
        c
        for c in session['candidates']
        if c['status'] == 'done'
        and not c.get('image_missing')
        and valid_config(c['config'], session)
        and scores[c['id']]['count'] >= 3
        and scores[c['id']]['wins'] >= 1
        and (
            c.get('include_parent')
            or not (scores[c['id']]['bad'] >= 2 and scores[c['id']]['bad'] >= scores[c['id']]['wins'])
        )
    ]
    rng.shuffle(parents)
    parents.sort(key=lambda c: -scores[c['id']]['score'])
    parents = parents[:3]
    mutation_count = count - math.floor(0.3 * count + 0.5)
    weight_count = math.ceil(mutation_count / 2)
    seen = {signature(c['config']) for c in session['candidates']}
    out = []
    for attempt in range(max(1000, count * 50)):
        if len(out) == count:
            break
        parent = None
        desc = 'random'
        if len(out) < mutation_count and parents:
            parent = rng.choice(parents)
            config, desc = mutate(rng, parent, session, len(out) < weight_count)
        else:
            config = None
        if config is None or attempt > count * 10:
            config = random_candidate(rng, session)
            parent = None
            desc = 'random'
        sig = signature(config)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(
            {
                'id': uuid.uuid4().hex,
                'config': config,
                'parent_id': parent['id'] if parent else None,
                'change': desc,
                'status': 'planned',
                'attempts': [],
            }
        )
    return out, rng.getstate()


def _tuple(value):
    return tuple(_tuple(x) if isinstance(x, (list, tuple)) else x for x in value)


def artist_prompt(config, service):
    def escaped(name):
        return name.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    return ', '.join(
        f'{x["weight"]:g}::{x["name"]}::'
        if service == 'novelai'
        else f'({escaped(x["name"])}:{x["weight"]:g})'
        for x in config['artists']
    )


class StyleSearch(StyleFlowMixin):
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = runtime.lock
        self.root = runtime.paths.data / 'image' / 'style-search'
        self.init_flow()
        self.pool_path = self.root / 'pools.json'
        with runtime.queue.editing() as jobs:
            for job in jobs:
                if job.get('snapshot', {}).get('style_session') and job['status'] in (
                    'queued',
                    'running',
                    'cancelling',
                ):
                    job['status'] = 'interrupted'

    def path(self, ident):
        if not isinstance(ident, str) or len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
            invalid('session id')
        return self.root / 'sessions' / (ident + '.json')

    def pools(self):
        data = read_json(self.pool_path, {'schema_version': 1, 'items': []})
        return {**data, 'revision': revisions.of(data)}

    def save_pool(self, body):
        with self.lock:
            data = self.pools()
            revisions.check(body.get('revision'), data.pop('revision'))
            ident = body.get('id') or uuid.uuid4().hex
            if body.get('delete'):
                data['items'] = [x for x in data['items'] if x['id'] != ident]
            else:
                kind = body.get('kind')
                if kind not in ('artists', 'models', 'loras'):
                    invalid('pool kind')
                name = str(body.get('name') or '').strip()
                if not name or len(name) > 200:
                    invalid('pool name')
                item = {'id': ident, 'name': name, 'kind': kind, 'items': clean_pool(body.get('items'))}
                data['items'] = [x for x in data['items'] if x['id'] != ident] + [item]
            atomic_json(self.pool_path, data)
            return self.pools()

    def list(self):
        return [
            {
                'id': p.stem,
                'name': d.get('name'),
                'service': d.get('service'),
                'created_at': d.get('created_at'),
            }
            for p in sorted((self.root / 'sessions').glob('*.json'), reverse=True)
            if (d := read_json(p))
        ]

    def create(self, body):
        with self.lock:
            service = body.get('service', 'comfyui')
            family = body.get('family', 'anima')
            if service not in ('comfyui', 'novelai') or (
                service == 'comfyui' and family not in ('anima', 'sdxl')
            ):
                invalid('service/family')
            pools = {k: clean_pool(body.get('pools', {}).get(k, [])) for k in ('artists', 'models', 'loras')}
            settings = copy.deepcopy(body.get('settings') or {})
            settings.setdefault('seed', 104729)
            if type(settings['seed']) is not int or settings['seed'] < 0:
                invalid('fixed seed')
            if service == 'novelai':
                models = [x for x in pools['models'] if x['mode'] != 'exclude']
                if len(models) != 1:
                    invalid('one fixed NAI model')
            ident = uuid.uuid4().hex
            session = {
                'schema_version': 2,
                'id': ident,
                'name': str(body.get('name') or now())[:200],
                'created_at': now(),
                'service': service,
                'family': family,
                'settings': settings,
                'positive': body.get('positive', DEFAULT_SCENE),
                'negative': body.get('negative', 'extra people, duplicate'),
                'pools': pools,
                'rules': validate_rules(body.get('rules', {}), pools, service),
                'candidates': [],
                'events': [],
                'rounds': [],
                'pair': None,
                'rng': random.Random(secrets.randbits(64)).getstate(),
                'changes': [],
            }
            for field in ('positive', 'negative'):
                if not isinstance(session[field], str) or len(session[field]) > 30000:
                    invalid(field)
            model_names = [x['name'] for x in pools['models'] if x['mode'] != 'exclude']
            if not model_names or sum(x['mode'] == 'always' for x in pools['models']) > 1:
                invalid('choose one model per candidate')
            session['settings'] = self.settings_for(
                session, {'model': model_names[0], 'artists': [], 'loras': []}
            )
            self.check_assets(session)
            self.normalize_flow(session)
            atomic_json(self.path(ident), session)
            return self.get(ident)

    def load(self, ident):
        data = read_json(self.path(ident))
        if not data:
            invalid('session missing')
        return self.normalize_flow(data)

    def sync(self, session):
        jobs = self.runtime.queue.by_id()
        for c in session['candidates']:
            for attempt in c['attempts']:
                job = jobs.get(attempt['id'])
                if not job and attempt['status'] in ('queued', 'running', 'cancelling'):
                    attempt['status'] = 'interrupted'
                if job:
                    attempt.update(
                        {
                            k: wire(job[k])
                            for k in ('status', 'image_url', 'error', 'prompt_id', 'result_uncertain', 'sent')
                            if k in job
                        }
                    )
            if c['attempts']:
                latest = c['attempts'][-1]
                c['status'] = latest['status']
                if latest.get('image_url'):
                    c['image_url'] = latest['image_url']
                if c.get('image_url'):
                    try:
                        c['image_missing'] = not self.runtime.gallery.safe_path(
                            unquote(c['image_url'].removeprefix('/api/image/files/'))
                        ).is_file()
                    except ValueError:
                        c['image_missing'] = True
        return session

    def get(self, ident):
        with self.lock:
            session = self.sync(self.load(ident))
            self.present_comparison(session)
            flow = self.public_flow(session)
            atomic_json(self.path(ident), session)
            return {**session, 'flow': flow, 'scores': ranking(session), 'revision': revisions.of(session)}

    def check_assets(self, session):
        if session['service'] != 'comfyui':
            return
        catalog = self.runtime.catalog()
        if not catalog.get('connected'):
            invalid('ComfyUI connection')
        for kind in ('models', 'loras'):
            for item in session['pools'][kind]:
                if item['mode'] == 'exclude':
                    continue
                name = item['name']
                if name not in catalog.get(kind, []):
                    invalid('missing ' + kind + ': ' + name)
                family = catalog.get('families', {}).get(kind, {}).get(name)
                if family not in (None, session['family']):
                    invalid('incompatible ' + kind + ': ' + name)

    def settings_for(self, session, config, catalog=None):
        settings = {**session['settings'], 'model': config['model']}
        if session['service'] == 'comfyui':
            settings.update(
                family=session['family'],
                loras=[
                    {'name': x['name'], 'strength_model': x['weight'], 'strength_clip': x['clip']}
                    for x in config['loras']
                ],
            )
            catalog = catalog or self.runtime.catalog()
            if not catalog.get('connected'):
                invalid('ComfyUI connection')
            for kind, name in [('models', config['model'])] + [('loras', x['name']) for x in config['loras']]:
                if (catalog.get('families', {}).get(kind, {}) or {}).get(name) not in (
                    None,
                    session['family'],
                ):
                    invalid('model/LoRA family')
            return validate_settings(settings, catalog)
        return self.runtime.services['novelai'].validate_settings(settings)

    def job(self, session, candidate, catalog=None):
        settings = copy.deepcopy(candidate.get('execution_settings')) or self.settings_for(
            session, candidate['config'], catalog
        )
        if candidate.get('execution_settings'):
            self.settings_for({**session, 'settings': settings}, candidate['config'], catalog)
        candidate['execution_settings'] = copy.deepcopy(settings)
        prompt = ', '.join(
            x for x in [session['positive'], artist_prompt(candidate['config'], session['service'])] if x
        )
        if len(prompt) > 30000:
            invalid('prompt length')
        ident = uuid.uuid4().hex
        index = len(session['candidates']) + 1
        meta = {
            'kind': 'lab',
            'service': session['service'],
            'positive': prompt,
            'negative': session['negative'],
            'settings': settings,
            'run_created_at': now(),
            'lab_group': session['id'],
            'lab_index': index,
            'lab_row': 0,
            'lab_column': index,
            'style_session': session['id'],
            'style_candidate': candidate['id'],
        }
        return {
            'id': ident,
            'kind': 'lab',
            'service': session['service'],
            'status': 'queued',
            'sent': False,
            'created_at': now(),
            'seed': settings['seed'],
            'review_requested': False,
            'snapshot': meta,
            'lab_group': session['id'],
            'lab_index': index,
            'lab_row': 0,
            'lab_column': index,
            'title': session['name'],
        }

    def enqueue_plan(self, session):
        ident = session['id']
        plan = session['proposal']
        if session['service'] == 'novelai':
            self.runtime.services['novelai'].key()
        self.budget(session, len(plan['candidates']))
        limit = self.runtime.service_config.limit() if session['service'] == 'novelai' else 0
        if limit and len(plan['candidates']) > limit:
            invalid('internet generation limit: ' + str(limit))
        self.check_assets(session)
        self.runtime.queue.check_room(len(plan['candidates']))
        catalog = self.runtime.catalog() if session['service'] == 'comfyui' else None
        jobs = []
        for c in plan['candidates']:
            job = self.job(session, c, catalog)
            job['lab_index'] = len(session['candidates']) + len(jobs) + 1
            job['snapshot']['lab_index'] = job['lab_index']
            job['lab_column'] = job['lab_index']
            job['snapshot']['lab_column'] = job['lab_index']
            jobs.append(job)
        benchmarks = sorted(parents(session), key=lambda c: -ranking(session)[c['id']]['score'])[:3]
        for c, job in zip(plan['candidates'], jobs, strict=True):
            c.update(status='queued', attempts=[{'id': job['id'], 'status': 'queued', 'sent': False}])
            session['candidates'].append(c)
        if not plan.get('refine'):
            session['rounds'].append(
                {
                    'ids': [c['id'] for c in plan['candidates']],
                    'start_event': len(session['events']),
                    'benchmarks': [c['id'] for c in benchmarks],
                }
            )
        session['rng'] = plan['rng']
        session.pop('proposal')
        session['pair'] = None
        # Persist intent first. Missing jobs after a crash require manual reconciliation, never auto-send.
        atomic_json(self.path(ident), session)
        self.runtime.queue.add(jobs)

    def action(self, ident, body):
        with self.lock:
            session = self.sync(self.load(ident))
            # Runtime progress is not an edit conflict; compare against the persisted document before syncing.
            if body.get('action') not in ('heartbeat', 'leave'):
                revisions.check(body.get('revision'), revisions.of(self.load(ident)))
            action = body.get('action')
            if action in (
                'heartbeat',
                'resume',
                'leave',
                'pause',
                'automatic',
                'refine',
                'explore',
                'refine_next',
            ):
                self.flow_action(session, body)
            elif action == 'configure':
                pools = {
                    k: clean_pool(body.get('pools', session['pools'])[k])
                    for k in ('artists', 'models', 'loras')
                }
                rules = validate_rules(body.get('rules', session['rules']), pools, session['service'])
                if session['service'] == 'novelai' and pools['models'] != session['pools']['models']:
                    invalid('new session for model change')
                session['changes'].append({'at': now(), 'pools': session['pools'], 'rules': session['rules']})
                session.update(pools=pools, rules=rules)
                session['flow'].update(paused=True, reason='resume')
                session.pop('proposal', None)
            elif action == 'propose':
                self.check_assets(session)
                candidates, rng = propose(session, body.get('count', 10))
                session['proposal'] = {
                    'requested': body.get('count', 10),
                    'candidates': candidates,
                    'rng': rng,
                }
            elif action == 'generate':
                plan = session.get('proposal')
                if not plan:
                    invalid('prepare candidates first')
                if not plan['candidates']:
                    invalid('no unique candidates; change pool or range')
                if len(plan['candidates']) < plan['requested'] and not body.get('allow_partial'):
                    invalid('confirm partial generation')
                self.enqueue_plan(session)
            elif action == 'pair':
                self.pair(session, bool(body.get('extra')))
            elif action == 'evaluate':
                choice = body.get('choice')
                if choice not in ('a', 'b', 'tie', 'bad', 'skip') or not session['pair']:
                    invalid('evaluation')
                if choice != 'skip' and any(
                    c.get('image_missing') or c['status'] != 'done'
                    for c in session['candidates']
                    if c['id'] in session['pair']
                ):
                    invalid('image unavailable')
                event = {'pair': session['pair'], 'choice': choice, 'at': now()}
                if session['flow']['mode'] == 'refine':
                    self.refine_vote(session, event)
                session['events'].append(event)
                session['pair'] = None
                self.pair(session, False)
            elif action == 'undo':
                event = next((e for e in reversed(session['events']) if not e.get('undone')), None)
                if event:
                    self.undo_flow(session, session['events'].index(event), event)
                    event['undone'] = True
                    session['pair'] = event['pair']
            elif action == 'parent':
                c = next((c for c in session['candidates'] if c['id'] == body.get('candidate')), None)
                if c is None:
                    invalid('candidate')
                c['include_parent'] = bool(body.get('include'))
            elif action in ('cancel', 'retry'):
                selected = set(body.get('candidates', []))
                targets = [
                    c
                    for c in session['candidates']
                    if (not selected or c['id'] in selected)
                    and c['status'] in ('failed', 'cancelled', 'interrupted')
                ]
                if action == 'retry':
                    if session['service'] == 'novelai':
                        self.runtime.services['novelai'].key()
                    self.budget(session, len(targets))
                    self.runtime.queue.check_room(len(targets))
                    for c in targets:
                        previous = c['attempts'][-1]
                        if (previous.get('prompt_id') or previous.get('result_uncertain')) and not body.get(
                            'confirmed_unknown'
                        ):
                            invalid('check remote result before retry')
                        self.settings_for(session, c['config'])
                else:
                    session['flow'].update(paused=True, reason='paused')
                for c in session['candidates']:
                    if selected and c['id'] not in selected:
                        continue
                    if not c['attempts']:
                        continue
                    previous = c['attempts'][-1]
                    if action == 'cancel' and c['status'] in ('queued', 'running', 'cancelling'):
                        self.runtime.cancel(previous['id'])
                    elif action == 'retry' and c['status'] in ('failed', 'cancelled', 'interrupted'):
                        if (previous.get('prompt_id') or previous.get('result_uncertain')) and not body.get(
                            'confirmed_unknown'
                        ):
                            invalid('check remote result before retry')
                        job = self.job(session, c)
                        c['attempts'].append({'id': job['id'], 'status': 'queued', 'sent': False})
                        c['status'] = 'queued'
                        atomic_json(self.path(ident), session)
                        self.runtime.queue.add([job])
            elif action == 'save_presets':
                ids = []
                for c in session['candidates']:
                    if c['id'] not in body.get('candidates', []):
                        continue
                    config = c['config']
                    settings = copy.deepcopy(
                        c.get('execution_settings')
                        or {
                            **session['settings'],
                            'model': config['model'],
                            'loras': [
                                {'name': x['name'], 'strength_model': x['weight'], 'strength_clip': x['clip']}
                                for x in config['loras']
                            ],
                        }
                    )
                    settings.pop('seed', None)
                    for key in ('model_loader', 'model_filename'):
                        settings.pop(key, None)
                    preset_id = uuid.uuid4().hex
                    library.save_preset(
                        self.runtime.paths,
                        preset_id,
                        {
                            'name': str(body.get('name') or session['name']) + ' ' + str(len(ids) + 1),
                            'service': session['service'],
                            'family': session['family'],
                            'settings': settings,
                            'artist': {'positive': artist_prompt(config, session['service']), 'negative': ''},
                            'common': [],
                        },
                    )
                    ids.append(preset_id)
                session['saved_presets'] = ids
            elif action == 'delete':
                if any(c['status'] in ('queued', 'running', 'cancelling') for c in session['candidates']):
                    invalid('cancel active generation first')
                if body.get('delete_images'):
                    paths = [
                        item['path']
                        for item in self.runtime.gallery.snapshot_items()
                        if self.runtime.gallery.metadata(item['path']).get('style_session') == ident
                    ]
                    for start in range(0, len(paths), 1000):
                        self.runtime.trash.delete(paths[start : start + 1000])
                self.path(ident).unlink()
                return {'deleted': True}
            else:
                invalid('action')
            atomic_json(self.path(ident), session)
            return self.get(ident)

    def pair(self, session, extra):
        if session.get('flow', {}).get('mode') == 'refine':
            return
        if session['pair']:
            available = {
                c['id'] for c in session['candidates'] if c['status'] == 'done' and not c.get('image_missing')
            }
            if set(session['pair']) <= available:
                return
            session['pair'] = None
        done = [
            c
            for c in session['candidates']
            if c['status'] == 'done' and c.get('image_url') and not c.get('image_missing')
        ]
        if len(done) < 2:
            return
        round_ = session['rounds'][-1] if session['rounds'] else {'ids': [], 'start_event': 0}
        new = set(round_['ids'])
        events = [e for e in session['events'][round_['start_event'] :] if not e.get('undone')]
        if not extra and readiness(session)['ready']:
            return
        played = Counter(frozenset(e['pair']) for e in events)
        scores = ranking(session)
        rng = random.Random()
        rng.setstate(_tuple(session['rng']))
        if len(done) == 2 and played:
            return
        # Select an under-evaluated anchor first; never materialize O(N²) pairs for a large session.
        coverage = readiness(session)
        benchmarks = set(round_.get('benchmarks', []))
        anchors = [c['id'] for c in done if c['id'] in new]
        if not anchors:
            return
        rng.shuffle(anchors)
        anchor = min(
            anchors,
            key=lambda x: (
                scores[x]['count'] >= 3
                and len(coverage['opponents'].get(x, [])) >= 2
                and (not benchmarks or bool(set(coverage['opponents'].get(x, [])) & benchmarks)),
                scores[x]['count'],
            ),
        )
        opponents = [c['id'] for c in done if c['id'] != anchor and (anchor in new or c['id'] in new)]
        if not opponents:
            return
        rng.shuffle(opponents)
        opponent = min(
            opponents,
            key=lambda x: (
                bool(
                    benchmarks
                    and not (set(coverage['opponents'].get(anchor, [])) & benchmarks)
                    and x not in benchmarks
                ),
                x in coverage['opponents'].get(anchor, []),
                played[frozenset((anchor, x))],
                scores[x]['count'] >= 3,
                scores[x]['count'],
                abs(scores[anchor]['score'] - scores[x]['score']),
            ),
        )
        pair = (anchor, opponent)
        session['pair'] = list(pair)
        rng.shuffle(session['pair'])
        session['rng'] = rng.getstate()

    def failed(self, job, error):
        # Transport/authentication and missing assets affect every queued request; stop this session only.
        msg = message_of(error)
        key = getattr(msg, 'key', '')
        if key in (
            'server.image.services.no_answer',
            'server.worker.waited_more_than_30_minutes_for',
            'server.worker.result_too_long',
        ):
            job['result_uncertain'] = True
        text = str(error).lower()
        common = (
            key
            in (
                'server.image.services.no_key',
                'server.image.services.bad_key',
                'server.image.services.no_credit',
                'server.image.services.unreachable',
                'server.image.services.no_answer',
            )
            or isinstance(error, (httpx.TransportError, ConnectionError))
            or any(
                x in text
                for x in (
                    '401',
                    '403',
                    'unauthorized',
                    'connection',
                    'not found',
                    'missing model',
                    'available model',
                    'available lora',
                )
            )
        )
        if common:
            ident = job['snapshot']['style_session']
            with self.lock:
                session = self.load(ident)
                session['flow'].update(paused=True, reason='blocked')
                atomic_json(self.path(ident), session)
            for pending in self.runtime.queue.by_id().values():
                if (
                    pending.get('snapshot', {}).get('style_session') == ident
                    and pending['status'] == 'queued'
                ):
                    self.runtime.queue.update(pending, status='interrupted', error=msg)

    def capture(self, job):
        ident = (job.get('snapshot') or {}).get('style_session')
        if ident and self.path(ident).exists():
            with self.lock:
                session = self.sync(self.load(ident))
                atomic_json(self.path(ident), session)
