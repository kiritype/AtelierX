"""Manual, isolated style exploration. Reading a session never spends generation budget.

The frozen protocol and recipes live apart from queue state. Only explicit generate/retry
commands admit jobs; pair selection and votes operate on existing images.
"""

import copy
import math
import random
import re
import secrets
import uuid
from collections import Counter
from itertools import combinations
from urllib.parse import unquote

from ..core import revisions
from ..core.i18n import AppError, Msg
from . import library
from .comments import strip_text
from .internet.pixai import MODELS as PIXAI_MODELS
from .util import atomic_json, now, read_json, state_file
from .workflow import validate_settings

MAX_BATCH = 16
MAX_BUDGET = 200
DEFAULT_RULES = {
    'artist_min': 1,
    'artist_max': 3,
    'artist_low': 0.8,
    'artist_high': 1.2,
    'artist_step': 0.1,
    'lora_min': 0,
    'lora_max': 2,
    'lora_low': 0.4,
    'lora_high': 1.0,
    'lora_step': 0.1,
}
ID = re.compile(r'^[a-f0-9]{32}$')
UNFINISHED = ('queued', 'running', 'cancelling')


def invalid(detail):
    raise ValueError(
        Msg('server.explorer.invalid', 'Check the exploration settings: {detail}', detail=detail)
    )


def integer(value, low, high, detail):
    if type(value) is not int or not low <= value <= high:
        invalid(detail)
    return value


def text(value, detail, limit=30000):
    if not isinstance(value, str) or len(value) > limit:
        invalid(detail)
    return strip_text(value).strip()


def joined(*values):
    return ', '.join(value for value in values if value)


def replay(doc):
    scores = {
        candidate['id']: {'elo': 1000.0, 'matches': 0, 'wins': 0, 'draws': 0, 'rejected': 0}
        for candidate in doc['candidates']
    }
    for vote in doc['votes']:
        if vote.get('undone') or vote['result'] == 'skip':
            continue
        a, b = scores[vote['a']], scores[vote['b']]
        if vote['result'] == 'neither':
            a['rejected'] += 1
            b['rejected'] += 1
            continue
        outcome = {'a': 1.0, 'b': 0.0, 'tie': 0.5}[vote['result']]
        expected = 1 / (1 + 10 ** ((b['elo'] - a['elo']) / 400))
        delta = 24 * (outcome - expected)
        a['elo'] += delta
        b['elo'] -= delta
        a['matches'] += 1
        b['matches'] += 1
        if outcome == 0.5:
            a['draws'] += 1
            b['draws'] += 1
        else:
            (a if outcome else b)['wins'] += 1
    return scores


class StyleExplorer:
    def __init__(self, runtime):
        self.rt = runtime
        self.folder = state_file(runtime.paths, 'explorer')
        self.lock = runtime.lock

    def capabilities(self):
        return {
            'services': [
                {
                    'id': 'comfyui',
                    'name': 'ComfyUI',
                    'enabled': True,
                    'families': [
                        {'id': 'anima', 'name': 'Anima', 'enabled': True},
                        {'id': 'sdxl', 'name': 'SDXL', 'enabled': True},
                        {
                            'id': 'moss',
                            'name': 'MOSS-Image',
                            'enabled': False,
                            'reason': Msg(
                                'server.explorer.moss_unsupported',
                                'MOSS-Image is not supported in style exploration. Choose Anima or SDXL.',
                            ),
                        },
                    ],
                },
                {
                    'id': 'novelai',
                    'name': 'NovelAI',
                    'enabled': True,
                    'families': [{'id': 'novelai', 'name': 'NovelAI', 'enabled': True}],
                },
                {
                    'id': 'pixai',
                    'name': 'PixAI',
                    'enabled': True,
                    'families': [{'id': 'pixai', 'name': 'PixAI', 'enabled': True}],
                },
            ],
            'max_batch': MAX_BATCH,
            'max_budget': MAX_BUDGET,
            'defaults': {'count': 8, 'budget': 30, **DEFAULT_RULES},
        }

    def _path(self, ident):
        if not isinstance(ident, str) or not ID.fullmatch(ident):
            raise AppError(Msg('server.explorer.not_found', 'Exploration session not found.'), 404)
        return self.folder / f'{ident}.json'

    def _load(self, ident):
        doc = read_json(self._path(ident))
        if not isinstance(doc, dict):
            raise AppError(Msg('server.explorer.not_found', 'Exploration session not found.'), 404)
        return doc

    def _save(self, doc):
        atomic_json(self._path(doc['id']), doc)

    def _request(self, body):
        if not isinstance(body, dict):
            invalid('request must be an object')
        request = body.get('request_id')
        if not isinstance(request, str) or not 1 <= len(request) <= 200:
            invalid('request_id')
        return request

    def _change(self, doc, body, action, required=True):
        if not isinstance(body, dict):
            invalid('request must be an object')
        request = self._request(body) if required or body.get('request_id') is not None else None
        fingerprint = revisions.of({'action': action, **{k: v for k, v in body.items() if k != 'revision'}})
        old = doc['_requests'].get(request) if request else None
        if old:
            if old['fingerprint'] != fingerprint:
                raise AppError(
                    Msg('server.explorer.request_conflict', 'This request ID was already used.'), 409
                )
            return False
        revisions.check(body.get('revision'), doc['revision'])
        if request:
            doc['_requests'][request] = {'fingerprint': fingerprint}
        doc['revision'] += 1
        return True

    def _catalog(self):
        catalog = self.rt.catalog()
        if not catalog.get('connected'):
            invalid(str(catalog.get('error') or 'ComfyUI is disconnected'))
        return catalog

    def _validate_settings(self, service, family, settings, catalog=None):
        if service == 'comfyui':
            catalog = catalog or self._catalog()
            settings = validate_settings({**settings, 'family': family}, catalog)
            # Model family is authoritative, from catalog metadata or the registered model profile.
            known = (catalog.get('families') or {}).get('models', {}).get(settings['model'])
            if known is None:
                entry = (catalog.get('model_entries') or {}).get(settings['model']) or {}
                kind = (
                    'checkpoints' if entry.get('loader') == 'CheckpointLoaderSimple' else 'diffusion_models'
                )
                known = self.rt.models.detect(kind, entry.get('filename') or settings['model'])[0]
            if known != family:
                raise ValueError(
                    Msg(
                        'server.explorer.model_family',
                        'The model family is unknown or does not match this session. Set its family in Settings → Image → Models, then create a new session.',
                    )
                )
            for lora in settings.get('loras') or []:
                known = (catalog.get('families') or {}).get('loras', {}).get(lora['name'])
                if known != family:
                    raise ValueError(
                        Msg(
                            'server.explorer.lora_family',
                            'The LoRA family is unknown or does not match this session. Set its family in Settings → Image → Models, then create a new session.',
                        )
                    )
            return settings
        if service == 'novelai' and settings.get('loras'):
            invalid('NovelAI does not support LoRAs')
        if service == 'pixai' and str(settings.get('model') or PIXAI_MODELS[0]['id']) not in {
            m['id'] for m in PIXAI_MODELS
        }:
            raise ValueError(
                Msg(
                    'server.explorer.pixai_model_kind',
                    'This PixAI model kind is unknown. Choose one of the listed PixAI models.',
                )
            )
        return self.rt.services[service].validate_settings(settings)

    def _config(self, body):
        self._request(body)
        service = body.get('service', 'comfyui')
        family = body.get('family') or ('anima' if service == 'comfyui' else service)
        if family == 'moss' or service == 'moss':
            raise ValueError(
                Msg(
                    'server.explorer.moss_unsupported',
                    'MOSS-Image is not supported in style exploration. Choose Anima or SDXL.',
                )
            )
        if service not in ('comfyui', 'novelai', 'pixai') or family not in (
            ('anima', 'sdxl') if service == 'comfyui' else (service,)
        ):
            invalid('unsupported service or model family')
        positive = text(body.get('positive', ''), 'positive prompt')
        if not positive:
            invalid('enter a positive prompt')
        negative = text(body.get('negative', ''), 'negative prompt')
        raw = body.get('settings') or {}
        if not isinstance(raw, dict):
            invalid('settings')
        raw = copy.deepcopy(raw)
        if isinstance(raw.get('loras'), list):
            raw['loras'] = [
                x for x in raw['loras'] if not isinstance(x, dict) or x.get('enabled') is not False
            ]
        seed = body.get('seed', raw.get('seed', -1))
        integer(seed, -1, 2**31 - 1 if service == 'pixai' else 2**32 - 1, 'seed')
        if seed == -1:
            seed = secrets.randbelow(2**31 if service == 'pixai' else 2**32)
        raw['seed'] = seed
        models = body.get('models') or ([raw['model']] if raw.get('model') else [])
        if (
            not isinstance(models, list)
            or len(models) > 100
            or any(not isinstance(x, str) or not x for x in models)
        ):
            invalid('models')
        if len(set(models)) != len(models):
            invalid('duplicate models')
        if models and not raw.get('model'):
            raw['model'] = models[0]
        catalog = self._catalog() if service == 'comfyui' else None
        checked = self._validate_settings(service, family, raw, catalog)
        if not models:
            models = [checked['model']]
        models = [
            self._validate_settings(service, family, {**checked, 'model': model}, catalog)['model']
            for model in models
        ]
        if len(set(models)) != len(models):
            invalid('duplicate models after resolving catalog names')
        artists = body.get('artists') or []
        if not isinstance(artists, list) or len(artists) > 10000:
            invalid('artists')
        picked, seen = [], set()
        for item in artists:
            if not isinstance(item, dict) or item.get('mode', 'candidate') not in (
                'always',
                'candidate',
                'exclude',
            ):
                invalid('artist mode')
            name = text(item.get('name'), 'artist name', 500)
            if not name or name in seen:
                invalid('empty or duplicate artist')
            seen.add(name)
            picked.append({'name': name, 'mode': item.get('mode', 'candidate')})
        supplied_rules = body.get('rules') or {}
        if not isinstance(supplied_rules, dict):
            invalid('rules')
        rules = {**DEFAULT_RULES, **supplied_rules}
        if set(rules) != set(DEFAULT_RULES):
            invalid('unknown rule')
        loras = checked.get('loras') or []
        lora_names = [x.get('name') if service == 'comfyui' else x.get('id') for x in loras]
        if len(set(lora_names)) != len(lora_names):
            invalid('duplicate LoRAs')
        for kind, size, required in (
            (
                'artist',
                sum(x['mode'] != 'exclude' for x in picked),
                sum(x['mode'] == 'always' for x in picked),
            ),
            ('lora', len(loras), 0),
        ):
            for edge in ('min', 'max'):
                key = f'{kind}_{edge}'
                if key not in supplied_rules:
                    rules[key] = min(rules[key], size)
                integer(rules[key], 0, size, key)
            if rules[f'{kind}_min'] > rules[f'{kind}_max'] or required > rules[f'{kind}_max']:
                invalid(f'{kind} count / always included')
            low, high, step = (rules[f'{kind}_{key}'] for key in ('low', 'high', 'step'))
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in (low, high, step)):
                invalid(f'{kind} weight range')
            maximum = 1 if kind == 'lora' and service == 'pixai' else 10
            if not 0 <= low <= high <= maximum or step <= 0 or (high - low) / step > 10000:
                invalid(f'{kind} weight range')
        if rules['lora_max'] > (5 if service == 'pixai' else 16):
            invalid('LoRA count limit')
        return {
            'name': text(body.get('name') or 'Style exploration', 'name', 200),
            'service': service,
            'family': family,
            'positive': positive,
            'negative': negative,
            'seed': seed,
            'settings': checked,
            'models': models,
            'artists': picked,
            'rules': rules,
            'budget': integer(body.get('budget', 30), 1, MAX_BUDGET, 'budget'),
        }

    def create(self, body):
        with self.lock:
            request = self._request(body)
            digest = revisions.of(body)
            for path in self.folder.glob('*.json') if self.folder.exists() else []:
                old = read_json(path, {})
                if old.get('_create_request') == request:
                    if old['_create_fingerprint'] != digest:
                        raise AppError(
                            Msg('server.explorer.request_conflict', 'This request ID was already used.'), 409
                        )
                    return self._public(old)
            config = self._config(body)
            doc = {
                'schema_version': 1,
                'id': uuid.uuid4().hex,
                'name': config['name'],
                'service': config['service'],
                'family': config['family'],
                'created_at': now(),
                'revision': 1,
                'config': config,
                'budget': config['budget'],
                'used': 0,
                'candidates': [],
                'pair': None,
                'votes': [],
                '_requests': {},
                '_create_request': request,
                '_create_fingerprint': digest,
            }
            self._save(doc)
            return self._public(doc)

    def list(self):
        with self.lock:
            docs = (
                [read_json(path, {}) for path in self.folder.glob('*.json')] if self.folder.exists() else []
            )
            return {
                'sessions': [
                    {
                        key: doc[key]
                        for key in (
                            'id',
                            'name',
                            'service',
                            'family',
                            'created_at',
                            'revision',
                            'budget',
                            'used',
                        )
                    }
                    | {
                        'candidate_count': len(doc['candidates']),
                        'vote_count': sum(not v.get('undone') for v in doc['votes']),
                    }
                    for doc in sorted(docs, key=lambda x: x['created_at'], reverse=True)
                ]
            }

    def get(self, ident):
        with self.lock:
            return self._public(self._load(ident))

    def _candidate_view(self, candidate):
        result = {k: copy.deepcopy(v) for k, v in candidate.items() if not k.startswith('_')}
        job = next((j for j in self.rt.queue.jobs if j['id'] == candidate.get('job_id')), None)
        if job:
            for key in ('status', 'image_url', 'error'):
                if key in job:
                    result[key] = copy.deepcopy(job[key])
        # Recover a result saved immediately before a crash interrupted the queue update.
        if not result.get('image_url') and candidate.get('_session'):
            relative = f'_explorer/{candidate["_session"]}/{candidate["job_id"]}.png'
            path = self.rt.gallery.safe_path(relative)
            if path.is_file():
                record = read_json(path.with_suffix('.json'), {})
                if (
                    record.get('explorer_candidate') == candidate['id']
                    and record.get('explorer_session') == candidate['_session']
                ):
                    result['image_url'] = self.rt.gallery.url(relative)
        if result.get('image_url'):
            relative = unquote(result['image_url'].removeprefix('/api/image/files/'))
            if self.rt.gallery.safe_path(relative).is_file():
                result.update(path=relative, status='done')
                result.pop('image_missing', None)
            else:
                result.update(
                    status='failed',
                    image_url=None,
                    path=None,
                    image_missing=True,
                    error=Msg(
                        'server.explorer.image_missing',
                        'The candidate image is missing. Retry it explicitly to generate another image.',
                    ),
                )
        elif not job and result['status'] in UNFINISHED:
            result['status'] = 'interrupted'
        return result

    def _public(self, doc):
        result = {
            k: copy.deepcopy(v) for k, v in doc.items() if not k.startswith('_') and k != 'schema_version'
        }
        scores = replay(doc)
        result['candidates'] = [{**self._candidate_view(c), **scores[c['id']]} for c in doc['candidates']]
        result['votes'] = [v for v in result['votes'] if not v.get('undone')]
        result['candidate_count'] = len(result['candidates'])
        result['vote_count'] = len(result['votes'])
        result['ranking'] = sorted(result['candidates'], key=lambda c: -c['elo'])
        return result

    def _recipe(self, config, rng):
        rules = config['rules']
        always = [x['name'] for x in config['artists'] if x['mode'] == 'always']
        choices = [x['name'] for x in config['artists'] if x['mode'] == 'candidate']
        count = rng.randint(max(len(always), rules['artist_min']), rules['artist_max'])
        names = sorted(always + rng.sample(choices, count - len(always)))

        def weight(kind):
            low, high, step = (rules[f'{kind}_{key}'] for key in ('low', 'high', 'step'))
            return round(low + rng.randint(0, math.floor((high - low) / step + 1e-8)) * step, 8)

        artists = [{'name': name, 'weight': weight('artist')} for name in names]
        pool = config['settings'].get('loras') or []
        loras = []
        for item in rng.sample(pool, rng.randint(rules['lora_min'], rules['lora_max'])):
            value = weight('lora')
            loras.append(
                {
                    **item,
                    **(
                        {'strength_model': value, 'strength_clip': value}
                        if config['service'] == 'comfyui'
                        else {'weight': value}
                    ),
                }
            )
        loras.sort(key=lambda x: x.get('name') or x.get('id'))
        settings = {**copy.deepcopy(config['settings']), 'model': rng.choice(config['models'])}
        if config['service'] != 'novelai':
            settings['loras'] = loras
        tags = ', '.join(
            x['name']
            if x['weight'] == 1
            else (
                f'{x["weight"]:g}::{x["name"]}::'
                if config['service'] == 'novelai'
                else f'({x["name"]}:{x["weight"]:g})'
            )
            for x in artists
        )
        return {'settings': settings, 'artists': artists, 'style_positive': tags, 'style_negative': ''}

    def _resume(self, doc, candidate, job=None):
        if not self.rt.services[doc['service']].resumable:
            return None
        if job:
            error = job.get('error')
            key = error.get('key') if isinstance(error, dict) else getattr(error, 'key', None)
            if key in ('server.pixai.task_failed', 'server.pixai.expired', 'server.pixai.no_image'):
                return None
            if job.get('resume'):
                return job['resume']
            if job.get('prompt_id') and job['status'] != 'done':
                # An interrupted status/download check is not permission to send another paid task.
                return job['prompt_id']
        return candidate.get('_resume')

    def _admit(self, doc, candidates, retry=None):
        if doc['used'] + len(candidates) > doc['budget']:
            raise ValueError(
                Msg('server.explorer.budget', 'This action would exceed the session generation budget.')
            )
        if doc['service'] != 'comfyui':
            limit = self.rt.service_config.limit()
            if limit and len(candidates) > limit:
                raise ValueError(
                    Msg(
                        'server.image.services.over_limit',
                        'Up to {limit} images per run for an internet service (requested {n}).',
                        limit=limit,
                        n=len(candidates),
                    )
                )
        self.rt.queue.check_room(len(candidates))
        jobs = []
        for candidate in candidates:
            resume = self._resume(doc, candidate, retry) if retry or candidate.get('_resume') else None
            if resume:
                candidate['_resume'] = resume
            else:
                candidate.pop('_resume', None)
            job_id = uuid.uuid4().hex
            candidate.update(job_id=job_id, status='queued')
            candidate.pop('error', None)
            for key in ('image_missing', 'image_url', 'path'):
                candidate.pop(key, None)
            jobs.append(
                {
                    'id': job_id,
                    'kind': 'style_explorer',
                    'service': doc['service'],
                    'status': 'queued',
                    'created_at': now(),
                    'seed': candidate['seed'],
                    'review_requested': False,
                    'explorer_session': doc['id'],
                    'explorer_candidate': candidate['id'],
                    **({'resume': resume} if resume else {}),
                    'snapshot': {
                        'kind': 'style_explorer',
                        'service': doc['service'],
                        'explorer_session': doc['id'],
                        'explorer_candidate': candidate['id'],
                        'positive': candidate['positive'],
                        'negative': candidate['negative'],
                        'settings': copy.deepcopy(candidate['settings']),
                        'explorer_recipe': {
                            key: copy.deepcopy(candidate[key]) for key in ('artists', 'style_positive')
                        },
                    },
                }
            )
        doc['used'] += len(jobs)
        self.rt.queue.add(jobs, before_save=lambda _: self._save(doc))

    def generate(self, ident, body):
        with self.lock:
            doc = self._load(ident)
            if not self._change(doc, body, 'generate'):
                return self._public(doc)
            count = integer(body.get('count', 8), 1, MAX_BATCH, 'count')
            if doc['used'] + count > doc['budget']:
                raise ValueError(
                    Msg('server.explorer.budget', 'This action would exceed the session generation budget.')
                )
            config = doc['config']
            seen = {c['_signature'] for c in doc['candidates']}
            selected = []
            rng = random.Random(secrets.randbits(128))
            catalog = self._catalog() if doc['service'] == 'comfyui' else None
            for _ in range(max(1000, count * 100)):
                recipe = self._recipe(config, rng)
                signature = revisions.of(recipe)
                if signature in seen:
                    continue
                seen.add(signature)
                recipe['settings'] = self._validate_settings(
                    doc['service'], doc['family'], recipe['settings'], catalog
                )
                positive = joined(config['positive'], recipe['style_positive'])
                text(positive, 'combined positive prompt')
                selected.append(
                    {
                        'id': uuid.uuid4().hex,
                        '_session': doc['id'],
                        'index': len(doc['candidates']) + len(selected) + 1,
                        'positive': positive,
                        'negative': config['negative'],
                        'seed': config['seed'],
                        'status': 'queued',
                        '_signature': signature,
                        **recipe,
                    }
                )
                if len(selected) == count:
                    break
            if len(selected) != count:
                raise ValueError(
                    Msg('server.explorer.exhausted', 'There are not enough unique recipes for this batch.')
                )
            doc['candidates'].extend(selected)
            self._admit(doc, selected)
            return self._public(doc)

    def pair(self, ident, body):
        with self.lock:
            doc = self._load(ident)
            if not isinstance(body, dict):
                invalid('request must be an object')
            revisions.check(body.get('revision'), doc['revision'])
            visible = {c['id']: c for c in self._public(doc)['candidates'] if c['status'] == 'done'}
            invalidated = False
            if doc['pair']:
                if {doc['pair']['a'], doc['pair']['b']} <= visible.keys():
                    return self._public(doc)
                doc['pair'] = None
                invalidated = True
            used = {frozenset((v['a'], v['b'])) for v in doc['votes'] if not v.get('undone')}
            pairs = [p for p in combinations(visible, 2) if frozenset(p) not in used]
            if not pairs:
                if invalidated:
                    doc['revision'] += 1
                    self._save(doc)
                return self._public(doc)
            scores = replay(doc)
            coverage = Counter(
                x for vote in doc['votes'] if not vote.get('undone') for x in (vote['a'], vote['b'])
            )
            pairs.sort(
                key=lambda p: (
                    max(coverage[p[0]], coverage[p[1]]),
                    coverage[p[0]] + coverage[p[1]],
                    abs(scores[p[0]]['elo'] - scores[p[1]]['elo']),
                    p,
                )
            )
            a, b = pairs[0]
            sides = Counter(v['a'] for v in doc['votes'] if not v.get('undone'))
            if sides[a] > sides[b]:
                a, b = b, a
            doc['pair'] = {'id': uuid.uuid4().hex, 'a': a, 'b': b}
            doc['revision'] += 1
            self._save(doc)
            return self._public(doc)

    def vote(self, ident, body):
        with self.lock:
            doc = self._load(ident)
            if not self._change(doc, body, 'vote'):
                return self._public(doc)
            pair = doc['pair']
            if not pair or pair['id'] != body.get('pair_id'):
                invalid('the displayed pair has changed')
            if body.get('result') not in ('a', 'b', 'tie', 'neither', 'skip'):
                invalid('vote result')
            ready = {c['id'] for c in self._public(doc)['candidates'] if c['status'] == 'done'}
            if body['result'] != 'skip' and not {pair['a'], pair['b']} <= ready:
                invalid('both images must still exist')
            doc['votes'].append(
                {
                    'id': uuid.uuid4().hex,
                    'pair_id': pair['id'],
                    'a': pair['a'],
                    'b': pair['b'],
                    'result': body['result'],
                    'created_at': now(),
                }
            )
            doc['pair'] = None
            self._save(doc)
            return self._public(doc)

    def undo(self, ident, body):
        with self.lock:
            doc = self._load(ident)
            if not self._change(doc, body, 'undo'):
                return self._public(doc)
            vote = next((v for v in reversed(doc['votes']) if not v.get('undone')), None)
            if vote is None:
                invalid('no vote to undo')
            vote['undone'] = True
            ready = {c['id'] for c in self._public(doc)['candidates'] if c['status'] == 'done'}
            doc['pair'] = (
                {'id': vote['pair_id'], 'a': vote['a'], 'b': vote['b']}
                if {vote['a'], vote['b']} <= ready
                else None
            )
            self._save(doc)
            return self._public(doc)

    def cancel(self, ident, body):
        with self.lock:
            doc = self._load(ident)
            if not self._change(doc, body, 'cancel', required=False):
                return self._public(doc)
            for job in list(self.rt.queue.jobs):
                if job.get('explorer_session') == ident and job['status'] in UNFINISHED:
                    self.rt.queue.cancel(job['id'])
            self._save(doc)
            self.reconcile(ident)
            return self._public(self._load(ident))

    def retry(self, ident, body):
        with self.lock:
            doc = self._load(ident)
            if not self._change(doc, body, 'retry'):
                return self._public(doc)
            candidate = next((c for c in doc['candidates'] if c['id'] == body.get('candidate_id')), None)
            if candidate is None or self._candidate_view(candidate)['status'] not in (
                'failed',
                'cancelled',
                'interrupted',
            ):
                invalid('choose a failed, cancelled or interrupted candidate')
            if self._candidate_view(candidate).get('image_missing') and any(
                not v.get('undone') and v['result'] != 'skip' and candidate['id'] in (v['a'], v['b'])
                for v in doc['votes']
            ):
                raise ValueError(
                    Msg(
                        'server.explorer.rated_missing',
                        'This image already has ratings. Undo its ratings or start a new session before regenerating.',
                    )
                )
            self._validate_settings(doc['service'], doc['family'], candidate['settings'])
            old = next((j for j in self.rt.queue.jobs if j['id'] == candidate.get('job_id')), None)
            self._admit(doc, [candidate], retry=old)
            return self._public(doc)

    def preset(self, ident, body):
        with self.lock:
            doc = self._load(ident)
            fresh = self._change(doc, body, 'preset')
            if not fresh:
                preset_id = doc['_requests'][body['request_id']]['preset_id']
                return {'session': self._public(doc), 'preset_id': preset_id}
            candidate = next((c for c in doc['candidates'] if c['id'] == body.get('candidate_id')), None)
            if candidate is None or self._candidate_view(candidate)['status'] != 'done':
                invalid('choose a candidate with an existing image')
            name = text(body.get('name', ''), 'preset name', 200)
            if not name:
                invalid('preset name')
            # A retry after a crash between the two file writes addresses the same fresh preset.
            preset_id = str(uuid.uuid5(uuid.UUID(doc['id']), body['request_id']))
            settings = {k: copy.deepcopy(v) for k, v in candidate['settings'].items() if k != 'seed'}
            library.save_preset(
                self.rt.paths,
                preset_id,
                {
                    'name': name,
                    'service': doc['service'],
                    'family': doc['family'],
                    'settings': settings,
                    'artist': {
                        'positive': candidate['style_positive'],
                        'negative': candidate.get('style_negative', ''),
                    },
                    'common': [],
                },
            )
            candidate['preset_id'] = preset_id
            doc['_requests'][body['request_id']]['preset_id'] = preset_id
            self._save(doc)
            return {'session': self._public(doc), 'preset_id': preset_id}

    def reconcile(self, ident=None):
        """Keep terminal queue outcomes before clearing jobs; generation completion also calls this."""
        with self.lock:
            paths = (
                [self._path(ident)]
                if ident
                else (list(self.folder.glob('*.json')) if self.folder.exists() else [])
            )
            for path in paths:
                doc = read_json(path)
                if not doc:
                    continue
                changed = False
                for candidate in doc['candidates']:
                    job = next((j for j in self.rt.queue.jobs if j['id'] == candidate.get('job_id')), None)
                    resume = self._resume(doc, candidate, job)
                    if job and job['status'] == 'done':
                        resume = None
                    if resume != candidate.get('_resume'):
                        if resume:
                            candidate['_resume'] = resume
                        else:
                            candidate.pop('_resume', None)
                        changed = True
                    view = self._candidate_view(candidate)
                    for key in ('status', 'image_url', 'path', 'error', 'image_missing'):
                        if key in view and candidate.get(key) != view[key]:
                            candidate[key] = view[key]
                            changed = True
                if changed:
                    self._save(doc)
