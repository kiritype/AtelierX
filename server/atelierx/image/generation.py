"""Image generation (20-generation): composing and queueing images, and the worker that runs queued jobs.

The queue itself is ``JobQueue`` (job_queue.py) and where a job is made is its generation service (services.py).
The worker runs one job at a time in a daemon thread: it takes the GPU's turn for a local service, waits until the
service is free, sends the job, checks on it, and saves the image as PNG (with the service's request) plus a JSON
sidecar. A failure pauses the queue so a broken setting does not burn through every job.
"""

import copy
import io
import json
import logging
import secrets
import time
import uuid
from urllib.parse import quote

from PIL import Image, PngImagePlugin

from ..core.i18n import AppError, Msg, message_of
from . import library
from .compose import Composer
from .services import ResultPending
from .util import atomic_json, code, now, replace_file
from .workflow import build_ui_workflow, pipeline_stages, validate_settings

log = logging.getLogger(__name__)

DEFAULT_SERVICE = 'comfyui'


class GenerationMixin:
    """Generation over ``ImageRuntime`` (expects paths, works, queue, services, lock, gpu, stop)."""

    # --- the queue's state, as callers and tests still read it --------------------------------------------------------
    @property
    def jobs(self):
        return self.queue.jobs

    @jobs.setter
    def jobs(self, value):
        self.queue.jobs = value

    @property
    def paused(self):
        return self.queue.paused

    @paused.setter
    def paused(self, value):
        self.queue.paused = value

    def load_queue(self):
        self.queue.load()

    def persist(self):
        self.queue.persist()

    def public_jobs(self):
        return self.queue.public(self.gpu.status())

    # --- composing and queueing ------------------------------------------------------------------------------------
    def _service(self, body):
        ident = body.get('service') or DEFAULT_SERVICE
        service = self.services.get(ident)
        if service is None:
            raise ValueError(
                Msg(
                    'server.worker.unknown_service',
                    'This job needs an image service that is not set up: {service}',
                    service=ident,
                )
            )
        return service

    def _settings(self, body):
        service = self._service(body)
        if service.id != DEFAULT_SERVICE:
            # An internet service has its own settings; prompts are composed for it (library targets, #80).
            # A style preset made for this service (#169) gives its settings and artist tags.
            preset = self._preset(body, service.id)
            settings = {
                **((preset or {}).get('settings') or {}),
                **(body.get('settings') or {}),
                'family': service.id,
            }
            options = {
                'family': service.id,
                'common_ids': body.get('common_ids', (preset or {}).get('common') or None),
                **self._artist(body, preset),
                'composition_id': body.get('composition_id'),
                'outfit_slots': body.get('outfit_slots'),
                'overrides': body.get('overrides') or {},
                'trigger': False,  # a trigger word only means something to a local LoRA
            }
            return settings, options, preset
        preset = self._preset(body, 'comfyui')
        settings = {**((preset or {}).get('settings') or {}), **(body.get('settings') or {})}
        settings['family'] = settings.get('family') or (preset or {}).get('family') or 'anima'
        options = {
            'family': settings['family'],
            'common_ids': body.get('common_ids', (preset or {}).get('common') or None),
            **self._artist(body, preset),
            'composition_id': body.get('composition_id'),
            'outfit_slots': body.get('outfit_slots'),
            'overrides': body.get('overrides') or {},
            'trigger': body.get('trigger'),
        }
        return settings, options, preset

    def _preset(self, body, service):
        if not body.get('preset_id'):
            return None
        preset = next((p for p in library.presets(self.paths) if p['id'] == body['preset_id']), None)
        if preset is None:
            raise ValueError(Msg('server.image.queue.no_preset', 'Style preset not found.'))
        if preset['service'] != service:
            raise ValueError(
                Msg(
                    'server.image.queue.preset_service',
                    'Style preset {name} is for {service}.',
                    name=preset['name'],
                    service=preset['service'],
                )
            )
        return preset

    @staticmethod
    def _artist(body, preset):
        """The artist tags: the request's (the screen may edit them for one run), else the preset's."""
        artist = body.get('artist') if isinstance(body.get('artist'), dict) else (preset or {}).get('artist')
        return {'artist': artist or {}}

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
        # No cap per request (#209): the screen shows the total and asks before a large one; the queue's own limit
        # (MAX_QUEUED) is what keeps it workable.
        if not isinstance(targets, list) or not targets:
            raise ValueError(
                Msg('server.image.queue.no_targets', 'Choose characters, outfits and expressions.')
            )
        count = body.get('count', 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
            raise ValueError(
                Msg(
                    'server.queue.the_count_must_be_a_whole', 'The count must be a whole number from 1 to 50.'
                )
            )
        service = self._service(body)
        raw_settings, options, preset = self._settings(body)
        if service.id == DEFAULT_SERVICE:
            catalog = self.comfy.catalog()
            if not catalog['connected']:
                raise ValueError(catalog['error'])
            settings = validate_settings(raw_settings, catalog)
        else:
            catalog = None
            limit = self.service_config.limit()
            if limit and len(targets) * count > limit:
                raise ValueError(
                    Msg(
                        'server.image.services.over_limit',
                        '{n} images is over the limit of {limit} per run for internet image services. '
                        'Queue fewer, or raise the limit in Settings → Image.',
                        n=len(targets) * count,
                        limit=limit,
                    )
                )
            settings = service.validate_settings(raw_settings)
            self._check_repeat(service, body, settings)
        composer = Composer(self.paths, work)
        if len(targets) > 1:
            # Per-target edits would land on the wrong images when several are queued at once.
            options = {**options, 'overrides': {}}
        batch_id = uuid.uuid4().hex
        prepared = []
        for target in targets:
            snap = composer.compose(target, options)
            # Local LoRAs only exist for the local image server.
            loras = (
                self.auto_loras(work, snap['character_id'], snap['outfit_id'], settings['family'])
                if catalog is not None
                else []
            )
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
                    {
                        **snap,
                        'work_id': work.id,
                        'service': service.id,
                        'settings': actual,
                        'batch_id': batch_id,
                    }
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
                        'service': service.id,
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
        # The generate screen may turn review off for one request; it is never on while disabled.
        wanted = self.review_wanted() and body.get('review', True) is not False

        def mark(jobs):
            for job in jobs:
                job['review_requested'] = wanted
                if wanted and body.get('llm'):
                    job['review_llm'] = {
                        key: body['llm'][key] for key in ('provider', 'model') if key in body['llm']
                    }
            self.register_jobs(jobs)

        self.queue.add(prepared, before_save=mark)
        return {'ok': True, 'batch_id': batch_id, 'count': len(prepared)}

    REPEAT_WINDOW = 600

    def _check_repeat(self, service, body, settings):
        signature = json.dumps(
            {
                'service': service.id,
                'settings': {k: v for k, v in settings.items() if k != 'seed'},
                **{
                    k: body.get(k)
                    for k in (
                        'targets',
                        'count',
                        'preset_id',
                        'artist',
                        'common_ids',
                        'composition_id',
                        'overrides',
                    )
                },
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        recent = getattr(self, '_recent_requests', None)
        if recent is None:
            recent = self._recent_requests = {}
        moment = time.monotonic()
        for old in [s for s, at in recent.items() if moment - at > self.REPEAT_WINDOW]:
            del recent[old]
        if signature in recent and not body.get('repeat_ok'):
            raise AppError(
                Msg(
                    'server.image.services.repeat',
                    'The same request went to {service} a moment ago. Send it again?',
                    service=getattr(service, 'name', service.id),
                ),
                409,
            )
        recent[signature] = moment

    # --- queue actions -----------------------------------------------------------------------------------------------
    def cancel(self, job_id):
        self.queue.cancel(job_id)
        return {'ok': True}

    def retry(self, job_id):
        self.queue.retry(job_id, attach=self.attach_retry)
        return {'ok': True}

    def remove_finished(self, job_id=None):
        removed = self.queue.remove_finished(job_id)
        self.after_remove()
        return {'ok': True, 'removed': removed}

    def set_paused(self, paused):
        return {'ok': True, 'paused': self.queue.set_paused(paused)}

    def cancel_queued(self):
        """Cancel every waiting job; the running image still finishes."""
        self.queue.cancel_queued()
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
        if (job.get('service') or DEFAULT_SERVICE) == DEFAULT_SERVICE:
            info.add_text('prompt', json.dumps(graph, ensure_ascii=False))
            try:
                editor = build_ui_workflow(
                    metadata['settings'], metadata['positive'], metadata['negative'], job['seed']
                )
                info.add_text('workflow', json.dumps(editor, ensure_ascii=False))
            except (KeyError, ValueError):
                log.warning('No editor workflow for job %s; the API prompt is still saved.', job['id'])
        else:
            # An internet service's own PNG text (its generation settings) stays with the image.
            for name, value in (getattr(image, 'text', None) or {}).items():
                if name != 'atelierx' and isinstance(value, str):
                    info.add_text(name, value)
        info.add_text(
            'atelierx', json.dumps({k: v for k, v in metadata.items() if k != 'workflow'}, ensure_ascii=False)
        )
        temp = path.with_suffix('.png.tmp')
        image.save(temp, format='PNG', pnginfo=info, compress_level=6)
        atomic_json(path.with_suffix('.json'), metadata)
        replace_file(temp, path)
        preview = job.get('preset_preview')
        if preview:
            # A style preset's preview (#169): the lab image stays; a WebP copy goes next to the preset.
            try:
                library.store_preview(self.paths, preview['id'], path, preview['seed'], preview['hash'])
            except (OSError, ValueError):
                log.exception('Could not keep the preview of style preset %s', preview.get('id'))
        return self.output_url(path)

    # --- worker ------------------------------------------------------------------------------------------------------
    def on_gpu(self, job):
        service = self.services.get(job.get('service') or DEFAULT_SERVICE)
        return service is None or service.local_gpu

    def worker(self):
        while not self.stop.wait(0.5):
            with self.lock:
                upcoming = self.next_generation_job()
                local = upcoming is not None and self.on_gpu(upcoming)
                free = not self.paused and (not local or self.gpu.generation_allowed())
            # Another program on the GPU holds new local jobs back; the reason is shown in the UI.
            if upcoming is not None and local and free and self.gpu.admit('generation'):
                continue
            with self.lock:
                job = self.next_generation_job() if not self.paused else None
                if job is not None and self.on_gpu(job) and not self.gpu.generation_allowed():
                    job = None
                if job is not None:
                    self.queue.update(
                        job,
                        status='running',
                        started_at=now(),
                        progress=Msg('server.worker.connecting_to_comfyui', 'Connecting to ComfyUI'),
                    )
            if job is None:
                try:
                    self.process_ready()
                except Exception:
                    log.exception('Image review halted')
                continue
            self.run_job(job)

    def service_for(self, job):
        ident = job.get('service') or DEFAULT_SERVICE
        service = self.services.get(ident)
        if service is None:
            raise RuntimeError(
                Msg(
                    'server.worker.unknown_service',
                    'This job needs an image service that is not set up: {service}',
                    service=ident,
                )
            )
        return service

    def run_job(self, job):
        """Run one job that the worker (or a test) marked running, on its service, to its end."""
        try:
            service = self.service_for(job)

            def cancelling():
                return self.queue.status_of(job) == 'cancelling'

            # A job whose request already went out (restart, failed download) asks about it again: no new request.
            resume = job.get('resume') if service.resumable else None
            # Wait while the service works for others.
            deadline = time.monotonic() + service.wait_limit
            while not resume:
                if self.stop.is_set():
                    return
                if cancelling() or not service.busy():
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError(service.busy_too_long())
                self.stop.wait(2)
            if cancelling() and not resume:
                self.queue.update(job, status='cancelled')
                return
            self.ensure_generation_safe()
            kind = job.get('kind')
            sent = {'id': resume, 'record': service.request_body(job)} if resume else service.submit(job)
            working = (
                self._generating(job)
                if kind in (None, 'lab')
                else Msg('server.worker.processing', 'Processing')
            )
            self.queue.update(job, prompt_id=sent['id'], progress=working)

            # Check on it; a cancel asks the service once and then waits for its answer.
            deadline = time.monotonic() + service.result_limit
            stopping = cancel_sent = False
            while not self.stop.wait(1):
                stopping = cancelling()
                if stopping and not cancel_sent:
                    if service.cancel(job, sent):
                        break
                    cancel_sent = True
                result = service.poll(job, sent)
                if result is not None:
                    if 'error' in result:
                        if stopping:
                            break
                        raise RuntimeError(result['error'])
                    if stopping and not service.keep_on_cancel:
                        break
                    # A paid image that arrives after a cancel is kept: the request could not be called back.
                    self._finish(job, result, sent)
                    stopping = False
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError(service.too_long())
            if stopping:
                self.queue.update(
                    job, status='cancelled', finished_at=now(), progress=Msg('server.worker.cancel', 'Cancel')
                )
        except Exception as error:
            log.exception('Image job failed: %s', job['id'])
            with self.lock:
                if isinstance(error, ResultPending):
                    # Kept so that Retry fetches this result instead of asking (and paying) again.
                    job['resume'] = error.task_id
                job.update(
                    status='failed',
                    error=message_of(error),
                    finished_at=now(),
                    progress=Msg('server.worker.failed', 'Failed'),
                )
                self.paused = True
                self.persist()

    @staticmethod
    def _generating(job):
        """'Generating', naming the steps after it when the job has them (#168)."""
        stages = pipeline_stages((job.get('snapshot') or {}).get('settings'))
        if stages == ['generate']:
            return Msg('server.worker.generating', 'Generating')
        if stages == ['generate', 'upscale']:
            return Msg('server.worker.generating_upscale', 'Generating → upscale')
        if stages == ['generate', 'detailer']:
            return Msg('server.worker.generating_detailer', 'Generating → detailer')
        return Msg('server.worker.generating_upscale_detailer', 'Generating → upscale → detailer')

    def _finish(self, job, result, sent):
        done = Msg('server.worker.done', 'Done')
        kind = job.get('kind')
        if kind == 'tag':
            tags = self.finish_tags(job, result['entry'])
            self.queue.update(job, status='done', tag_count=len(tags), finished_at=now(), progress=done)
            return
        if kind == 'post':
            image_url, _ = self.save_post(job, result['image'], sent['record'])
        else:
            image_url = self.save_result(job, result['image'], sent['record'], sent['id'])
        self.queue.update(
            job,
            status='done',
            image_url=image_url,
            metadata_url=image_url.rsplit('.', 1)[0] + '.json',
            finished_at=now(),
            progress=done,
        )
        self.after_generation(job)

    # --- hooks the later stages fill in (review, tools, LoRA) -----------------------------------------------------------
    def review_wanted(self):
        return False

    def register_jobs(self, jobs):
        return None

    def attach_retry(self, old, new):
        return None

    def next_generation_job(self):
        return next(iter(self.queue.select(lambda j: j['status'] == 'queued')), None)

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
