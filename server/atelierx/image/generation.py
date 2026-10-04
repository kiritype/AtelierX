"""Image generation queue and worker (20-generation). The queue survives restarts (state/image/queue.json).

The worker runs in one daemon thread: it waits for the GPU and an idle image server, sends the graph,
polls /history, downloads the image and saves it as PNG with ComfyUI's prompt/workflow chunks plus a
JSON sidecar. A failure pauses the queue so a broken setting does not burn through every job.
"""

import copy
import io
import json
import logging
import secrets
import time
import uuid
from urllib.parse import quote, urlencode

from PIL import Image, PngImagePlugin

from ..core.i18n import Msg, message_of
from . import library
from .compose import Composer
from .util import atomic_json, code, now, read_json, replace_file, state_file
from .workflow import build_ui_workflow, build_workflow, validate_settings

log = logging.getLogger(__name__)

FINISHED = frozenset({'completed', 'failed', 'cancelled', 'interrupted'})
FINISHED_SHOWN = 1000
MAX_QUEUED = 5000
MAX_REQUEST = 3000
RETRY_KEYS = (
    'work_id',
    'character_id',
    'outfit_id',
    'expression_id',
    'expression_name',
    'outfit_name',
    'rating',
    'seed',
    'snapshot',
    'kind',
    'title',
    'lab_group',
    'lab_index',
    'lab_row',
    'lab_column',
    'lab_variant',
    'lab_sweep',
    'lab_source',
    'review_requested',
    'tool_item',
    'tag_settings',
    'post_op',
    'post_options',
    'post_prefix',
    'post_source',
    'post_mask',
    'batch_id',
)


class GenerationMixin:
    """Queue and worker of ``ImageRuntime`` (expects paths, works, lock, jobs, paused, comfy, gpu, stop)."""

    # --- persistence ---------------------------------------------------------------------------------------------
    @property
    def queue_path(self):
        return state_file(self.paths, 'queue.json')

    def load_queue(self):
        saved = read_json(self.queue_path, {}) or {}
        self.jobs = saved.get('jobs') or []
        self.paused = bool(saved.get('paused'))
        for job in self.jobs:
            # Work cut off by a restart cannot be resumed; it is marked so it can be retried.
            if job['status'] in ('running', 'cancelling'):
                job.update(status='interrupted', progress=Msg('server.worker.interrupted', 'Interrupted'))

    def persist(self):
        atomic_json(self.queue_path, {'schema_version': 1, 'paused': self.paused, 'jobs': self.jobs})

    def public_jobs(self):
        with self.lock:
            finished = [i for i, j in enumerate(self.jobs) if j['status'] in FINISHED]
            hidden = set(finished[:-FINISHED_SHOWN])
            return {
                'paused': self.paused,
                'gpu': self.gpu.status(),
                'jobs': [
                    {k: v for k, v in j.items() if k not in ('snapshot', 'workflow')}
                    for i, j in enumerate(self.jobs)
                    if i not in hidden
                ],
            }

    # --- composing and queueing ------------------------------------------------------------------------------------
    def _settings(self, body):
        preset = None
        if body.get('preset_id'):
            preset = next((p for p in library.presets(self.paths) if p['id'] == body['preset_id']), None)
            if preset is None:
                raise ValueError(Msg('server.image.queue.no_preset', 'Generation preset not found.'))
        settings = {**((preset or {}).get('settings') or {}), **(body.get('settings') or {})}
        settings['family'] = settings.get('family') or (preset or {}).get('family') or 'anima'
        options = {
            'family': settings['family'],
            'common_ids': body.get('common_ids', (preset or {}).get('common') or None),
            'style_ids': body.get('style_ids', (preset or {}).get('styles') or []),
            'composition_id': body.get('composition_id'),
            'outfit_slots': body.get('outfit_slots'),
            'overrides': body.get('overrides') or {},
            'trigger': body.get('trigger'),
        }
        return settings, options, preset

    def preview(self, work, body):
        """Composed prompts for the targets without queueing (the generate screen's preview)."""
        _, options, _ = self._settings(body)
        targets = body.get('targets') or []
        if not isinstance(targets, list) or not targets:
            raise ValueError(
                Msg('server.image.queue.no_targets', 'Choose characters, outfits and expressions.')
            )
        composer = Composer(self.paths, work)
        if len(targets) > 1:
            options = {**options, 'overrides': {}}
        return [composer.compose(target, options) for target in targets[:200]]

    def enqueue(self, work, body):
        targets = body.get('targets')
        if not isinstance(targets, list) or not 1 <= len(targets) <= 500:
            raise ValueError(Msg('server.queue.select_1_to_500_expressions', 'Select 1 to 500 expressions.'))
        count = body.get('count', 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
            raise ValueError(
                Msg(
                    'server.queue.the_count_must_be_a_whole', 'The count must be a whole number from 1 to 50.'
                )
            )
        if len(targets) * count > MAX_REQUEST:
            raise ValueError(Msg('server.queue.up_to_3_000_images_per', 'Up to 3,000 images per request.'))
        catalog = self.comfy.catalog()
        if not catalog['connected']:
            raise ValueError(catalog['error'])
        raw_settings, options, preset = self._settings(body)
        settings = validate_settings(raw_settings, catalog)
        composer = Composer(self.paths, work)
        if len(targets) > 1:
            # Per-target edits would land on the wrong images when several are queued at once.
            options = {**options, 'overrides': {}}
        batch_id = uuid.uuid4().hex
        prepared = []
        for target in targets:
            snap = composer.compose(target, options)
            loras = self.auto_loras(work, snap['character_id'], snap['outfit_id'], settings['family'])
            for _ in range(count):
                seed = secrets.randbits(32) if settings.get('seed', -1) == -1 else settings['seed']
                actual = {**settings, 'seed': seed}
                if loras:
                    actual['loras'] = [
                        *loras,
                        *[x for x in actual.get('loras', []) if x['name'] not in {y['name'] for y in loras}],
                    ]
                    missing = [x['name'] for x in loras if x['name'] not in catalog.get('loras', [])]
                    if missing:
                        raise ValueError(
                            Msg(
                                'server.queue.automatic_lora_files_are_missing_in',
                                'Automatic LoRA files are missing in ComfyUI: {missing}',
                                missing=', '.join(missing),
                            )
                        )
                snapshot = copy.deepcopy(
                    {**snap, 'work_id': work.id, 'settings': actual, 'batch_id': batch_id}
                )
                if preset:
                    snapshot['generation_preset'] = {
                        'id': preset['id'],
                        'name': preset.get('name', preset['id']),
                    }
                prepared.append(
                    {
                        'id': uuid.uuid4().hex,
                        'status': 'queued',
                        'created_at': now(),
                        'work_id': work.id,
                        'character_id': snap['character_id'],
                        'outfit_id': snap['outfit_id'],
                        'outfit_name': snap['outfit_name'],
                        'expression_id': snap['expression_id'],
                        'expression_name': snap['expression_name'],
                        'rating': snap['rating'],
                        'seed': seed,
                        'batch_id': batch_id,
                        'snapshot': snapshot,
                    }
                )
        with self.lock:
            if sum(j['status'] == 'queued' for j in self.jobs) + len(prepared) > MAX_QUEUED:
                raise ValueError(
                    Msg(
                        'server.queue.too_many_queued_jobs_let_the',
                        'Too many queued jobs. Let the queue run first.',
                    )
                )
            # The generate screen may turn review off for one request; it is never on while disabled.
            wanted = self.review_wanted() and body.get('review', True) is not False
            for job in prepared:
                job['review_requested'] = wanted
                if wanted and body.get('llm'):
                    job['review_llm'] = {
                        key: body['llm'][key] for key in ('provider', 'model') if key in body['llm']
                    }
            self.jobs.extend(prepared)
            self.persist()
            self.register_jobs(prepared)
        return {'ok': True, 'batch_id': batch_id, 'count': len(prepared)}

    # --- queue actions -----------------------------------------------------------------------------------------------
    def _job(self, job_id):
        job = next((j for j in self.jobs if j['id'] == job_id), None)
        if job is None:
            raise ValueError(Msg('server.queue.job_not_found', 'Job not found.'))
        return job

    def cancel(self, job_id):
        with self.lock:
            job = self._job(job_id)
            if job['status'] == 'queued':
                job['status'] = 'cancelled'
            elif job['status'] == 'running':
                job['status'] = 'cancelling'
            self.persist()
        return {'ok': True}

    def retry(self, job_id):
        with self.lock:
            old = self._job(job_id)
            if old['status'] not in ('failed', 'cancelled', 'interrupted'):
                raise ValueError(
                    Msg(
                        'server.queue.only_failed_cancelled_or_interrupted_jobs',
                        'Only failed, cancelled or interrupted jobs can be retried.',
                    )
                )
            job = {k: copy.deepcopy(v) for k, v in old.items() if k in RETRY_KEYS}
            job.update(id=uuid.uuid4().hex, status='queued', created_at=now())
            self.attach_retry(old, job)
            self.jobs.append(job)
            self.persist()
        return {'ok': True}

    def remove_finished(self, job_id=None):
        with self.lock:
            if job_id is not None and self._job(job_id)['status'] not in FINISHED:
                raise ValueError(
                    Msg(
                        'server.queue.only_finished_jobs_can_be_cleared',
                        'Only finished jobs can be cleared. Cancel running or queued ones first.',
                    )
                )
            removed = {
                j['id']
                for j in self.jobs
                if j['status'] in FINISHED and (job_id is None or j['id'] == job_id)
            }
            self.jobs = [j for j in self.jobs if j['id'] not in removed]
            self.persist()
            self.after_remove()
            return {'ok': True, 'removed': len(removed)}

    def set_paused(self, paused):
        with self.lock:
            self.paused = bool(paused)
            self.persist()
            return {'ok': True, 'paused': self.paused}

    def cancel_queued(self):
        """Cancel every waiting job; the running image still finishes."""
        with self.lock:
            for job in self.jobs:
                if job['status'] == 'queued':
                    job['status'] = 'cancelled'
            self.persist()
            return {'ok': True}

    # --- saving results ----------------------------------------------------------------------------------------------
    def output_url(self, path):
        return '/api/image/files/' + quote(path.relative_to(self.paths.output).as_posix(), safe='/')

    def save_result(self, job, image_bytes, graph, prompt_id):
        """PNG with ComfyUI's ``prompt``/``workflow`` chunks (ComfyUI can reopen it) plus a JSON sidecar."""
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        if all(high == 0 for low, high in image.convert('RGB').getextrema()):
            raise RuntimeError(
                Msg(
                    'server.worker.an_all_black_image_came_back',
                    'An all-black image came back. It was not saved and the queue is paused.',
                )
            )
        if job.get('kind') == 'lab':
            stamp = time.localtime()
            folder = self.paths.output / '_lab' / time.strftime('%Y-%m-%d', stamp)
            stem = '{}_{}_{:02d}'.format(
                time.strftime('%H%M%S', stamp), job['lab_group'][:6], job['lab_index']
            )
        else:
            folder = (
                self.paths.output
                / code(job['work_id'])
                / code(job['character_id'])
                / 'images'
                / code(job['outfit_id'])
                / code(job['expression_id'])
            )
            stem = None
        folder.mkdir(parents=True, exist_ok=True)
        index = 1
        while True:
            candidate = f'{index:03d}' if stem is None else (stem if index == 1 else f'{stem}_{index:03d}')
            path = folder / (candidate + '.png')
            if not path.exists() and not path.with_suffix('.json').exists():
                break
            index += 1
        metadata = copy.deepcopy(job['snapshot'])
        metadata.update(
            schema_version=1,
            created_at=now(),
            job_id=job['id'],
            prompt_id=prompt_id,
            seed=job['seed'],
            workflow=graph,
            image_size=list(image.size),
            postprocessing={'applied': False, 'source_image': None},
        )
        info = PngImagePlugin.PngInfo()
        info.add_text('prompt', json.dumps(graph, ensure_ascii=False))
        try:
            editor = build_ui_workflow(
                metadata['settings'], metadata['positive'], metadata['negative'], job['seed']
            )
            info.add_text('workflow', json.dumps(editor, ensure_ascii=False))
        except (KeyError, ValueError):
            log.warning('No editor workflow for job %s; the API prompt is still saved.', job['id'])
        info.add_text(
            'atelierx', json.dumps({k: v for k, v in metadata.items() if k != 'workflow'}, ensure_ascii=False)
        )
        temp = path.with_suffix('.png.tmp')
        image.save(temp, format='PNG', pnginfo=info, compress_level=6)
        atomic_json(path.with_suffix('.json'), metadata)
        replace_file(temp, path)
        return self.output_url(path)

    # --- worker ------------------------------------------------------------------------------------------------------
    def worker(self):
        while not self.stop.wait(0.5):
            with self.lock:
                pending = any(job['status'] == 'queued' for job in self.jobs)
                free = not self.paused and self.gpu.generation_allowed()
            # Another program on the GPU holds new jobs back; the reason is shown in the UI.
            if pending and free and self.gpu.admit('generation'):
                continue
            with self.lock:
                free = not self.paused and self.gpu.generation_allowed()
                job = self.next_generation_job() if free else None
                if job is not None:
                    job.update(
                        status='running',
                        started_at=now(),
                        progress=Msg('server.worker.connecting_to_comfyui', 'Connecting to ComfyUI'),
                    )
                    self.persist()
            if job is None:
                try:
                    self.process_ready()
                except Exception:
                    log.exception('Image review halted')
                continue
            self.run_job(job)

    def run_job(self, job):
        try:
            # Wait for other clients; never clear or interrupt someone else's queue.
            deadline = time.monotonic() + 1800
            cancelling = False
            while True:
                if self.stop.is_set():
                    return
                with self.lock:
                    cancelling = job['status'] == 'cancelling'
                if cancelling:
                    break
                queue = self.comfy.request('/queue')
                if not queue.get('queue_running') and not queue.get('queue_pending'):
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        Msg(
                            'server.worker.waited_30_minutes_for_other_comfyui',
                            'Waited 30 minutes for other ComfyUI work.',
                        )
                    )
                self.stop.wait(2)
            if cancelling:
                with self.lock:
                    job['status'] = 'cancelled'
                    self.persist()
                return
            snap = job['snapshot']
            self.ensure_generation_safe()
            kind = job.get('kind')
            if kind == 'tag':
                graph = self.tag_graph(job)
            elif kind == 'post':
                graph = self.post_graph(job)
            else:
                graph = build_workflow(snap['settings'], snap['positive'], snap['negative'], job['seed'])
            response = self.comfy.request('/prompt', {'prompt': graph, 'client_id': 'atelierx-' + job['id']})
            if response.get('node_errors') or not response.get('prompt_id'):
                raise RuntimeError(
                    Msg(
                        'server.worker.workflow_validation_failed',
                        'Workflow validation failed: {response}',
                        response=json.dumps(response, ensure_ascii=False)[:3000],
                    )
                )
            prompt_id = response['prompt_id']
            with self.lock:
                working = (
                    Msg('server.worker.generating', 'Generating')
                    if kind in (None, 'lab')
                    else Msg('server.worker.processing', 'Processing')
                )
                job.update(prompt_id=prompt_id, progress=working)
                self.persist()
            deadline = time.monotonic() + 1800
            interrupt_sent = False
            while not self.stop.wait(1):
                with self.lock:
                    cancelling = job['status'] == 'cancelling'
                if cancelling and not interrupt_sent:
                    queue = self.comfy.request('/queue')
                    if any(item[1] == prompt_id for item in queue.get('queue_running', [])):
                        self.comfy.request('/interrupt', {'prompt_id': prompt_id})
                    elif any(item[1] == prompt_id for item in queue.get('queue_pending', [])):
                        self.comfy.request('/queue', {'delete': [prompt_id]})
                        break
                    interrupt_sent = True
                history = self.comfy.request('/history/' + quote(prompt_id))
                if prompt_id in history:
                    entry = history[prompt_id]
                    if entry.get('status', {}).get('status_str') == 'error':
                        if cancelling:
                            break
                        raise RuntimeError(
                            Msg(
                                'server.worker.comfyui_generation_error',
                                'ComfyUI generation error: {status}',
                                status=json.dumps(entry['status'].get('messages', []), ensure_ascii=False)[
                                    -2500:
                                ],
                            )
                        )
                    if cancelling:
                        break
                    if kind == 'tag':
                        tags = self.finish_tags(job, entry)
                        with self.lock:
                            job.update(
                                status='completed',
                                tag_count=len(tags),
                                finished_at=now(),
                                progress=Msg('server.worker.done', 'Done'),
                            )
                            self.persist()
                        break
                    images = entry.get('outputs', {}).get('output', {}).get('images', [])
                    if not images:
                        raise RuntimeError(
                            Msg('server.worker.comfyui_returned_no_image', 'ComfyUI returned no image.')
                        )
                    item = images[0]
                    data = self.comfy.request(
                        '/view?' + urlencode({k: item.get(k, '') for k in ('filename', 'subfolder', 'type')}),
                        raw=True,
                    )
                    if kind == 'post':
                        image_url, _ = self.save_post(job, data, graph)
                    else:
                        image_url = self.save_result(job, data, graph, prompt_id)
                    with self.lock:
                        job.update(
                            status='completed',
                            image_url=image_url,
                            metadata_url=image_url.rsplit('.', 1)[0] + '.json',
                            finished_at=now(),
                            progress=Msg('server.worker.done', 'Done'),
                        )
                        self.persist()
                    self.after_generation(job)
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        Msg(
                            'server.worker.waited_more_than_30_minutes_for',
                            'Waited more than 30 minutes for the result. Check progress in ComfyUI.',
                        )
                    )
            if cancelling:
                with self.lock:
                    job.update(
                        status='cancelled', finished_at=now(), progress=Msg('server.worker.cancel', 'Cancel')
                    )
                    self.persist()
        except Exception as error:
            log.exception('Image job failed: %s', job['id'])
            with self.lock:
                job.update(
                    status='failed',
                    error=message_of(error),
                    finished_at=now(),
                    progress=Msg('server.worker.failed', 'Failed'),
                )
                self.paused = True
                self.persist()

    # --- hooks the later stages fill in (review, tools, LoRA) -----------------------------------------------------------
    def review_wanted(self):
        return False

    def register_jobs(self, jobs):
        return None

    def attach_retry(self, old, new):
        return None

    def next_generation_job(self):
        return next((j for j in self.jobs if j['status'] == 'queued'), None)

    def process_ready(self):
        return None

    def ensure_generation_safe(self):
        return None

    def after_generation(self, job):
        return None

    def after_remove(self):
        return None

    def auto_loras(self, work, character_id, outfit_id, family):
        return []

    def tag_graph(self, job):
        raise RuntimeError(Msg('server.image.not_ready', 'This kind of job is not available yet.'))

    def post_graph(self, job):
        raise RuntimeError(Msg('server.image.not_ready', 'This kind of job is not available yet.'))

    def finish_tags(self, job, entry):
        raise RuntimeError(Msg('server.image.not_ready', 'This kind of job is not available yet.'))

    def save_post(self, job, data, graph):
        raise RuntimeError(Msg('server.image.not_ready', 'This kind of job is not available yet.'))
