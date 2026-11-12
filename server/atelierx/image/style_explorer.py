"""Manual, isolated style exploration. Reading a session never spends generation budget.

The frozen protocol and recipes live apart from queue state. Only explicit generate/retry
commands admit jobs; pair selection and votes operate on existing images.
"""

import copy
import math
import random
import re
import secrets
import sys
import uuid
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from urllib.parse import unquote

from ..core import revisions
from ..core.i18n import AppError, Msg
from . import library
from .comments import strip_text
from .internet.pixai import MAX_LORAS as PIXAI_MAX_LORAS
from .internet.pixai import MODELS as PIXAI_MODELS
from .internet.pixai import VERSION_ID as PIXAI_VERSION_ID
from .util import atomic_json, now, read_json, state_file
from .workflow import validate_settings

MAX_BATCH = 16
MAX_BUDGET = 200
SCHEMA_VERSION = 3
READABLE_SCHEMAS = (1, 2, SCHEMA_VERSION)
COMFY_MAX_LORAS = 16
MAX_MATERIALS = 10000
MATERIAL_MODES = ('always', 'candidate', 'exclude')
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


def finite(value):
    return type(value) in (int, float) and abs(value) <= sys.float_info.max


def weight_range(low, high, step, maximum, detail, legacy=False):
    if not all(map(finite, (low, high, step))) or not 0 <= low <= high <= maximum or step <= 0:
        invalid(detail)
    if legacy:
        slots = (high - low) / step
    else:
        first, last, stride = (Fraction(str(x)) for x in (low, high, step))
        slots = (last - first) / stride
    if slots > 10000:
        invalid(detail)


def material_weight(raw, maximum):
    if not isinstance(raw, dict):
        invalid('material weight')
    mode = raw.get('mode')
    if mode == 'fixed':
        value = raw.get('value')
        if not finite(value) or not 0 <= value <= maximum:
            invalid('material fixed weight')
        return {'mode': mode, 'value': value}
    if mode == 'random':
        low, high, step = (raw.get(key) for key in ('low', 'high', 'step'))
        weight_range(low, high, step, maximum, 'material random weight range')
        include_high = raw.get('include_high', False)
        if not isinstance(include_high, bool):
            invalid('material random weight include_high')
        return {
            'mode': mode,
            'low': low,
            'high': high,
            'step': step,
            **({'include_high': True} if include_high else {}),
        }
    invalid('material weight mode')


def legacy_materials(config):
    """Project the v1 pools and their global random ranges onto individual rows."""
    rules = config['rules']
    random_weight = {
        kind: {'mode': 'random', **{key: rules[f'{kind}_{key}'] for key in ('low', 'high', 'step')}}
        for kind in ('artist', 'lora')
    }
    return [
        {**tag, 'kind': 'tag', 'role': 'style', 'weight': random_weight['artist']}
        for tag in config['artists']
    ] + [
        {
            'kind': 'lora',
            'name': lora.get('name') or lora['id'],
            'role': 'style',
            'mode': 'candidate',
            'weight': random_weight['lora'],
            **{key: lora[key] for key in ('id', 'trigger_words') if key in lora},
        }
        for lora in config['settings'].get('loras') or []
    ]


def upgrade(doc):
    version = doc.get('schema_version')
    if version not in READABLE_SCHEMAS:
        raise AppError(
            Msg('server.explorer.schema_version', 'This exploration session uses an unsupported format.'), 409
        )
    if version == 1:
        doc['config']['materials'] = legacy_materials(doc['config'])
    if version != SCHEMA_VERSION:
        doc['config']['artist_format'] = 'literal'
        doc['schema_version'] = SCHEMA_VERSION
    return doc


def resolved_weight(weight, rng, legacy):
    if weight['mode'] == 'fixed':
        return weight['value']
    low, high, step = (weight[key] for key in ('low', 'high', 'step'))
    if legacy:
        return round(low + rng.randint(0, math.floor((high - low) / step + 1e-8)) * step, 8)
    first, last, stride = (Fraction(str(x)) for x in (low, high, step))
    steps, remainder = divmod(last - first, stride)
    include_high = weight.get('include_high', False) and remainder != 0
    index = rng.randint(0, steps + include_high)
    return float(last if index > steps else first + index * stride)


def weighted_tag(name, value, service, legacy):
    if value == 1:
        return name
    weight = f'{value:g}' if legacy else format(Decimal(str(value)).normalize(), 'f')
    return f'{weight}::{name}::' if service == 'novelai' else f'({name}:{weight})'


def material_tag_name(row, artist_format):
    name = row['name']
    if artist_format != 'anima' or 'role' in row:
        return name
    name = re.sub(r'^(?:(?:@+|artist:)\s*)+', '', name.lower())
    name = ' '.join(name.replace('_', ' ').split())
    if not name:
        invalid('Anima artist name')
    return '@' + re.sub(r'(?<!\\)([()])', r'\\\1', name)


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
        return upgrade(doc)

    def _save(self, doc):
        atomic_json(self._path(doc['id']), upgrade(doc))

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

    def _materials(self, raw, service, family, settings, catalog, artist_format):
        if not isinstance(raw, list) or len(raw) > MAX_MATERIALS:
            invalid('materials')
        result = []
        comfy = []
        for item in raw:
            if not isinstance(item, dict) or item.get('kind') not in ('tag', 'lora'):
                invalid('material kind')
            kind = item['kind']
            mode = item.get('mode', 'candidate')
            if mode not in MATERIAL_MODES:
                invalid('material mode')
            name = item.get('name')
            if not isinstance(name, str) or len(name) > 500:
                invalid('material name')
            name = text(name, 'tag name', 500) if kind == 'tag' else name.strip()
            if not name:
                invalid('empty material name')

            pixai_lora = kind == 'lora' and service == 'pixai'
            row = {
                'kind': kind,
                'name': name,
                'mode': mode,
                'weight': material_weight(item.get('weight'), 1 if pixai_lora else 10),
            }
            if 'role' in item:
                if item['role'] not in ('style', 'character', 'other'):
                    invalid('material role')
                row['role'] = item['role']
            if pixai_lora:
                ident = item.get('id')
                if not isinstance(ident, str) or not PIXAI_VERSION_ID.fullmatch(ident):
                    raise ValueError(Msg('server.pixai.lora_id', 'A LoRA needs its PixAI version id.'))
                row['id'] = ident
            elif 'id' in item:
                invalid('material id')
            if kind == 'lora':
                if service == 'novelai':
                    invalid('NovelAI does not support LoRAs')
                if 'trigger_words' in item:
                    triggers = item['trigger_words']
                    if not isinstance(triggers, str) or len(triggers) > 500:
                        invalid('LoRA trigger words')
                    if triggers.strip():
                        row['trigger_words'] = triggers.strip()
                if service == 'comfyui' and mode != 'exclude':
                    comfy.append(row)
            result.append(row)

        # Validate and resolve the entire selectable pool, in groups the shared settings validator accepts.
        for start in range(0, len(comfy), COMFY_MAX_LORAS):
            rows = comfy[start : start + COMFY_MAX_LORAS]
            inputs = [{'name': row['name']} for row in rows]
            checked = self._validate_settings(service, family, {**settings, 'loras': inputs}, catalog)
            for row, lora in zip(rows, checked['loras'], strict=True):
                row['name'] = lora['name']
        keys = [
            (
                row['kind'],
                material_tag_name(row, artist_format) if row['kind'] == 'tag' else row.get('id', row['name']),
            )
            for row in result
        ]
        if len(set(keys)) != len(keys):
            invalid('duplicate materials')
        return result

    def _legacy_artists(self, raw):
        if not isinstance(raw, list) or len(raw) > MAX_MATERIALS:
            invalid('artists')
        picked, seen = [], set()
        for item in raw:
            if not isinstance(item, dict) or item.get('mode', 'candidate') not in MATERIAL_MODES:
                invalid('artist mode')
            name = text(item.get('name'), 'artist name', 500)
            if not name or name in seen:
                invalid('empty or duplicate artist')
            seen.add(name)
            picked.append({'name': name, 'mode': item.get('mode', 'candidate')})
        return picked

    def _rules(self, supplied, materials, service, legacy):
        if not isinstance(supplied, dict):
            invalid('rules')
        if supplied.keys() - DEFAULT_RULES.keys():
            invalid('unknown rule')
        rules = {
            **DEFAULT_RULES,
            **{key: value for key, value in supplied.items() if legacy or key.endswith(('_min', '_max'))},
        }
        for kind, prefix in (('tag', 'artist'), ('lora', 'lora')):
            pool = [row for row in materials if row['kind'] == kind and row['mode'] != 'exclude']
            required = sum(row['mode'] == 'always' for row in pool)
            for edge in ('min', 'max'):
                key = f'{prefix}_{edge}'
                if key not in supplied:
                    rules[key] = min(rules[key], len(pool))
                    if edge == 'max' and not legacy:
                        rules[key] = max(rules[key], required)
                integer(rules[key], 0, len(pool), key)
            if rules[f'{prefix}_min'] > rules[f'{prefix}_max'] or required > rules[f'{prefix}_max']:
                invalid(f'{prefix} count / always included')
            if legacy:
                low, high, step = (rules[f'{prefix}_{key}'] for key in ('low', 'high', 'step'))
                maximum = 1 if kind == 'lora' and service == 'pixai' else 10
                weight_range(low, high, step, maximum, f'{prefix} weight range', legacy=True)
        if rules['lora_max'] > {'comfyui': COMFY_MAX_LORAS, 'pixai': PIXAI_MAX_LORAS, 'novelai': 0}[service]:
            invalid('LoRA count limit')
        return rules

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
        legacy = 'materials' not in body
        artist_format = 'anima' if service == 'comfyui' and family == 'anima' and not legacy else 'literal'
        if not legacy:
            raw['loras'] = []
        elif isinstance(raw.get('loras'), list):
            raw['loras'] = [
                x for x in raw['loras'] if not isinstance(x, dict) or x.get('enabled') is not False
            ]
        seed = body.get('seed', raw.get('seed', -1))
        integer(seed, -1, 2**31 - 1 if service == 'pixai' else 2**32 - 1, 'seed')
        if seed == -1:
            seed = secrets.randbelow(2**31 if service == 'pixai' else 2**32)
        raw['seed'] = seed
        models = body.get('models')
        if models is None:
            models = []
        if (
            not isinstance(models, list)
            or len(models) > 100
            or any(not isinstance(x, str) or not x for x in models)
        ):
            invalid('models')
        if len(set(models)) != len(models):
            invalid('duplicate models')
        if models and (service != 'novelai' or not raw.get('model')):
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
        supplied_rules = body.get('rules') or {}
        if not isinstance(supplied_rules, dict):
            invalid('rules')
        compatibility = {}
        if legacy:
            artists = self._legacy_artists(body.get('artists') or [])
            compatibility['artists'] = artists
            lora_names = [x.get('id', x.get('name')) for x in checked.get('loras') or []]
            if len(set(lora_names)) != len(lora_names):
                invalid('duplicate LoRAs')
            materials = legacy_materials(
                {'artists': artists, 'settings': checked, 'rules': {**DEFAULT_RULES, **supplied_rules}}
            )
        else:
            checked.pop('loras', None)
            materials = self._materials(body['materials'], service, family, checked, catalog, artist_format)
        rules = self._rules(supplied_rules, materials, service, legacy)
        return {
            'name': text(body.get('name') or 'Style exploration', 'name', 200),
            'service': service,
            'family': family,
            'positive': positive,
            'negative': negative,
            'seed': seed,
            'settings': checked,
            'models': models,
            'materials': materials,
            'artist_format': artist_format,
            **compatibility,
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
                    return self._public(upgrade(old))
            config = self._config(body)
            doc = {
                'schema_version': SCHEMA_VERSION,
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
        service = config['service']
        legacy = 'artists' in config
        pool = config['materials']

        def select(kind, prefix):
            always = [row for row in pool if row['kind'] == kind and row['mode'] == 'always']
            choices = [row for row in pool if row['kind'] == kind and row['mode'] == 'candidate']
            count = rng.randint(max(len(always), rules[f'{prefix}_min']), rules[f'{prefix}_max'])
            return always + rng.sample(choices, count - len(always))

        tags = sorted(select('tag', 'artist'), key=lambda row: row['name'])
        tags = [{**row, 'weight': resolved_weight(row['weight'], rng, legacy)} for row in tags]
        loras = [
            {**row, 'weight': resolved_weight(row['weight'], rng, legacy)} for row in select('lora', 'lora')
        ]
        loras.sort(key=lambda row: row.get('id', row['name']))
        settings = {**copy.deepcopy(config['settings']), 'model': rng.choice(config['models'])}
        prompt_tags = [
            weighted_tag(material_tag_name(row, config['artist_format']), row['weight'], service, legacy)
            for row in tags
        ]
        if service == 'comfyui':
            settings['loras'] = [
                {'name': row['name'], 'strength_model': row['weight'], 'strength_clip': row['weight']}
                for row in loras
            ]
            prompt_tags.extend(row['trigger_words'] for row in loras if row.get('trigger_words'))
        elif service == 'pixai':
            settings['loras'] = [
                {key: row[key] for key in ('id', 'weight', 'trigger_words') if key in row} for row in loras
            ]
        return {
            'settings': settings,
            'artists': [{'name': row['name'], 'weight': row['weight']} for row in tags],
            'materials': tags + loras,
            'style_positive': joined(*prompt_tags),
            'style_negative': '',
        }

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
                            key: copy.deepcopy(candidate[key])
                            for key in ('artists', 'materials', 'style_positive')
                            if key in candidate
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
                # Material labels are inspection metadata. Keep v1 recipe identities for resumed sessions.
                signature = revisions.of({key: value for key, value in recipe.items() if key != 'materials'})
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
                if not isinstance(doc, dict) or doc.get('schema_version') not in READABLE_SCHEMAS:
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
