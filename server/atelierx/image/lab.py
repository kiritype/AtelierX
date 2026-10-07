"""Generate & compare (20-generation: 생성·비교). One prompt, tried with several seeds or one changing value.

Lab jobs run through the same queue and worker as work images but belong to no work: they skip review and are
saved under ``<output>/_lab/<date>/``. A run is the set of images of one request (``lab_group``); runs are read
back from the queue while they are in it and from the saved records afterwards, so clearing the queue does not
lose them.
"""

import copy
import secrets
import shutil
import uuid
from datetime import datetime
from pathlib import PurePosixPath

from ..core.i18n import Msg
from . import library
from . import settings as image_settings
from .comments import strip_text
from .util import atomic_json, code, now, read_json, replace_file
from .workflow import validate_settings

MAX_PROMPT_LENGTH = 30000
MAX_COUNT = 16
MAX_VARIANTS = 12
MAX_JOBS = 48
RUNS_SHOWN = 60
# Settings a sweep may change. The seed stays the same so only that value differs.
SWEEP_KEYS = {
    'cfg': float,
    'steps': int,
    'sampler': str,
    'scheduler': str,
    'clip_skip': int,
    'lora_strength': float,
}
SWEEP_LABELS = {
    'cfg': 'CFG',
    'steps': 'Steps',
    'sampler': Msg('server.lab.sampler', 'Sampler'),
    'scheduler': Msg('server.lab.scheduler', 'Scheduler'),
    'clip_skip': 'CLIP skip',
    'lora_strength': Msg('server.lab.lora_strength', 'LoRA strength'),
    'artist': Msg('server.lab.artist', 'Artist / style tags'),
    'lora_file': 'LoRA',
}


def _text(value, name):
    if not isinstance(value, str) or len(value) > MAX_PROMPT_LENGTH:
        raise ValueError(
            Msg(
                'server.lab.prompt_too_long',
                '{name} must be text of at most {limit} characters.',
                name=name,
                limit=f'{MAX_PROMPT_LENGTH:,}',
            )
        )
    return value.strip()


def _variants(settings, sweep, positive):
    """(label, setting changes, positive prompt or None) per compared value."""
    if not sweep:
        return [('', {}, None)]
    key = sweep.get('key')
    if key not in SWEEP_LABELS:
        raise ValueError(
            Msg(
                'server.lab.the_value_to_vary_is_one',
                'The value to vary is one of {values}.',
                values=', '.join(str(v) for v in SWEEP_LABELS.values()),
            )
        )
    values = sweep.get('values')
    if not isinstance(values, list) or not 2 <= len(values) <= MAX_VARIANTS:
        raise ValueError(
            Msg(
                'server.lab.enter_2_to_values_to_compare',
                'Enter 2 to {max_variants} values to compare.',
                max_variants=MAX_VARIANTS,
            )
        )
    bad = Msg('server.lab.check_the_values', 'Check the {key} values.', key=SWEEP_LABELS[key])
    if key == 'artist':
        # Each candidate is added to the shared prompt; an empty one is the baseline without any.
        if not all(isinstance(v, str) for v in values):
            raise ValueError(bad)
        candidates = [v.strip() for v in values]
        if len(set(candidates)) != len(candidates):
            raise ValueError(bad)
        out = []
        for candidate in candidates:
            prompt = f'{positive}, {candidate}' if candidate else positive
            _text(prompt, Msg('server.lab.positive_prompt', 'Positive prompt'))
            out.append((candidate, {}, prompt))
        return out
    if key == 'lora_file':
        if not all(isinstance(v, str) and v.strip() for v in values) or len(set(values)) != len(values):
            raise ValueError(bad)
        loras = settings.get('loras') or []
        index = sweep.get('lora_index', 0)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= len(loras):
            raise ValueError(bad)
        out = []
        for value in values:
            changed = copy.deepcopy(loras)
            if index == len(changed):
                changed.append({'name': value, 'strength_model': 1, 'strength_clip': 1})
            else:
                changed[index]['name'] = value
            if len({item['name'].replace('\\', '/') for item in changed}) != len(changed):
                raise ValueError(bad)
            out.append((value, {'loras': changed}, None))
        return out
    try:
        values = [SWEEP_KEYS[key](value) for value in values]
    except (TypeError, ValueError) as error:
        raise ValueError(bad) from error
    if key != 'lora_strength':
        return [(f'{SWEEP_LABELS[key]} {value}', {key: value}, None) for value in values]
    index = sweep.get('lora_index', 0)
    loras = settings.get('loras') or []
    if not isinstance(index, int) or not 0 <= index < len(loras):
        raise ValueError(
            Msg(
                'server.lab.choose_the_lora_whose_strength_changes', 'Choose the LoRA whose strength changes.'
            )
        )
    out = []
    for value in values:
        changed = copy.deepcopy(loras)
        changed[index].update(strength_model=value, strength_clip=value)
        out.append(
            (
                Msg('server.lab.lora_strength_2', 'LoRA strength {value}', value=value),
                {'loras': changed},
                None,
            )
        )
    return out


class LabMixin:
    """Lab part of ``ImageRuntime`` (expects comfy, lock, jobs, persist, gallery)."""

    def enqueue_preset_preview(self, ident):
        """One preview image for a ComfyUI style preset (#169), queued like a lab run and kept next to the preset."""
        preset = next((p for p in library.presets(self.paths) if p['id'] == ident), None)
        if preset is None:
            raise ValueError(Msg('server.image.queue.no_preset', 'Style preset not found.'))
        if preset['service'] != 'comfyui':
            raise ValueError(
                Msg(
                    'server.image.presets.preview_comfy_only',
                    'Previews are made with ComfyUI for now. This preset is for {service}.',
                    service=preset['service'],
                )
            )
        seed = image_settings.get(self.paths, 'presets')['preview_seed']
        positive, negative = library.preview_prompts(self.paths, preset)
        body = {
            'positive': positive,
            'negative': negative,
            'settings': {**preset['settings'], 'family': preset['family'], 'seed': seed},
            'count': 1,
        }
        marker = {'id': ident, 'seed': seed, 'hash': library.preview_hash(preset, seed)}
        return self.enqueue_lab(body, preset_preview=marker)

    def enqueue_lab(self, body, preset_preview=None):
        # Notes (#157) are left out of what is sent and recorded.
        positive = strip_text(
            _text(body.get('positive', ''), Msg('server.lab.positive_prompt', 'Positive prompt'))
        )
        negative = strip_text(
            _text(body.get('negative', ''), Msg('server.lab.negative_prompt', 'Negative prompt'))
        )
        if not positive:
            raise ValueError(Msg('server.lab.enter_a_positive_prompt', 'Enter a positive prompt.'))
        count = body.get('count', 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT:
            raise ValueError(
                Msg(
                    'server.lab.seeds_must_be_a_whole_number',
                    'Seeds must be a whole number from 1 to {max_count}.',
                    max_count=MAX_COUNT,
                )
            )
        source = body.get('source')
        if source is not None and not isinstance(source, str):
            raise ValueError(Msg('server.lab.bad_source', 'The reference image is not valid.'))
        if source:
            self.gallery.safe_path(source)
        catalog = self.comfy.catalog()
        if not catalog['connected']:
            raise ValueError(catalog['error'])
        base = validate_settings(body.get('settings') or {}, catalog)
        variants = [
            (label, validate_settings({**base, **changes}, catalog), variant_positive or positive)
            for label, changes, variant_positive in _variants(base, body.get('sweep'), positive)
        ]
        if count * len(variants) > MAX_JOBS:
            raise ValueError(
                Msg(
                    'server.lab.up_to_images_per_lab_run',
                    'Up to {max_jobs} images per lab run.',
                    max_jobs=MAX_JOBS,
                )
            )
        fixed = base.get('seed', -1)
        # Every value of one row shares its seed, so only the compared value differs.
        seeds = [secrets.randbits(32) if fixed == -1 else (fixed + i) % 2**32 for i in range(count)]
        group = uuid.uuid4().hex[:12]
        created = now()
        sweep_key = (body.get('sweep') or {}).get('key')
        prepared = []
        for row, seed in enumerate(seeds):
            for column, (label, settings, prompt) in enumerate(variants):
                lab = {
                    'lab_group': group,
                    'lab_index': len(prepared) + 1,
                    'lab_row': row,
                    'lab_column': column,
                    'lab_variant': label,
                    'lab_sweep': sweep_key,
                    'lab_source': source,
                }
                if preset_preview:
                    lab['preset_preview'] = preset_preview
                prepared.append(
                    {
                        'id': uuid.uuid4().hex,
                        'kind': 'lab',
                        'status': 'queued',
                        'created_at': created,
                        'seed': seed,
                        'review_requested': False,
                        **lab,
                        'snapshot': {
                            'kind': 'lab',
                            'positive': prompt,
                            'negative': negative,
                            'settings': {**settings, 'seed': seed},
                            'run_created_at': created,
                            **lab,
                        },
                    }
                )
        self.queue.add(prepared)
        return {'lab_group': group, 'count': len(prepared), 'seeds': seeds}

    def lab_runs(self):
        """Recent runs, newest first: their cells (row = seed, column = compared value) with image or status."""
        runs = {}

        def cell(run_id, created, entry):
            run = runs.setdefault(
                run_id, {'id': run_id, 'created_at': created, 'sweep': entry.get('lab_sweep'), 'cells': {}}
            )
            key = (entry.get('lab_row') or 0, entry.get('lab_column') or 0)
            run['cells'].setdefault(key, {}).update({k: v for k, v in entry.items() if v is not None})

        for item in self.gallery.snapshot_items():
            if item['kind'] != 'lab':
                continue
            try:
                meta = self.gallery.metadata(item['path'])
            except ValueError:
                continue
            if not meta.get('lab_group'):
                continue
            cell(
                meta['lab_group'],
                meta.get('run_created_at') or meta.get('created_at') or item['created_at'],
                {
                    'lab_row': meta.get('lab_row'),
                    'lab_column': meta.get('lab_column'),
                    'lab_variant': meta.get('lab_variant'),
                    'lab_sweep': meta.get('lab_sweep'),
                    'seed': meta.get('seed'),
                    'status': 'done',
                    'path': item['path'],
                    'image_url': item['image_url'],
                    'source': meta.get('lab_source'),
                },
            )
        live = self.queue.select(lambda j: j.get('kind') == 'lab' and j.get('lab_group'))
        for job in live:
            cell(
                job['lab_group'],
                job['created_at'],
                {
                    'lab_row': job.get('lab_row'),
                    'lab_column': job.get('lab_column'),
                    'lab_variant': job.get('lab_variant'),
                    'lab_sweep': job.get('lab_sweep'),
                    'seed': job['seed'],
                    'status': job['status'],
                    'job_id': job['id'],
                    'error': job.get('error'),
                    'image_url': job.get('image_url'),
                    'source': job.get('lab_source'),
                },
            )
        out = []
        for run in runs.values():
            cells = [
                {**value, 'row': key[0], 'column': key[1]} for key, value in sorted(run['cells'].items())
            ]
            source = next((c.get('source') for c in cells if c.get('source')), None)
            out.append(
                {
                    'id': run['id'],
                    'created_at': run['created_at'],
                    'sweep': run['sweep'],
                    'source': source,
                    'source_url': self.gallery.url(source) if source else None,
                    'rows': 1 + max(c['row'] for c in cells),
                    'columns': 1 + max(c['column'] for c in cells),
                    'cells': cells,
                }
            )
        out.sort(key=lambda r: _when(r['created_at']), reverse=True)
        return {'runs': out[:RUNS_SHOWN]}

    # --- a lab result into the gallery (#53) -------------------------------------------------------------------------
    def import_lab(self, body):
        """Copy a lab result into a character's outfit × expression folder, with its generation record, so it goes
        through review, adoption and export like a generated image. The lab copy stays where it was."""
        body = body if isinstance(body, dict) else {}
        rel = str(body.get('path') or '')
        source = self.gallery.safe_path(rel)
        if PurePosixPath(rel).parts[0] != '_lab' or not source.is_file():
            raise ValueError(
                Msg('server.lab.import_not_lab', 'Choose a result of the comparison generation.')
            )
        work = self.works.get(str(body.get('work_id') or ''))
        character_id, outfit_id, expression_id = (
            code(body.get('character_id')),
            code(body.get('outfit_id')),
            code(body.get('expression_id')),
        )
        design = read_json(work.app / 'image' / 'characters' / character_id / 'design.json') or {}
        outfit = (design.get('outfits') or {}).get(outfit_id)
        expression = library.items(self.paths, work, 'expressions').get(expression_id)
        if outfit is None or expression is None:
            raise ValueError(
                Msg(
                    'server.lab.import_no_combo',
                    'This character has no such outfit, or there is no such expression.',
                )
            )
        folder = self.paths.output / work.id / character_id / 'images' / outfit_id / expression_id
        folder.mkdir(parents=True, exist_ok=True)
        index = 1
        while (folder / f'{index:03d}.png').exists() or (folder / f'{index:03d}.json').exists():
            index += 1
        target = folder / f'{index:03d}.png'
        record = read_json(source.with_suffix('.json')) or {}
        for key in (
            'kind',
            'lab_group',
            'lab_index',
            'lab_variant',
            'lab_row',
            'lab_column',
            'review_round_id',
        ):
            record.pop(key, None)
        record.update(
            schema_version=1,
            work_id=work.id,
            character_id=character_id,
            outfit_id=outfit_id,
            outfit_name=outfit.get('name', outfit_id),
            expression_id=expression_id,
            expression_name=expression.get('name', expression_id),
            rating=expression.get('rating') or 'general',
            imported_from=rel,
            imported_at=now(),
        )
        temp = target.with_suffix('.png.tmp')
        shutil.copyfile(source, temp)
        atomic_json(target.with_suffix('.json'), record)
        replace_file(temp, target)
        self.gallery.scan(force=True)
        return {'path': target.relative_to(self.paths.output).as_posix()}


def _when(text):
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return 0
