"""The image module's long-lived state: image generation server connection, model families, GPU broker, queue."""

import threading
import time

from ..core.i18n import AppError, Msg
from ..core.lifecycle import CANCELLING, QUEUED, RUNNING, UNFINISHED
from . import board, comfy_locate
from .comfy import Comfy
from .control import ComfyControl
from .deploy.targets import DeployTargets
from .deploy.upload import DeployUploads
from .gallery import Gallery
from .generation import GenerationMixin
from .gpu import GpuBroker
from .installs import Installs
from .internet.novelai import NovelAIService
from .internet.pixai import PixAIService
from .job_queue import JobQueue
from .lab import LabMixin
from .lora import models as lora_models
from .lora import store as lora_store
from .lora.trainer import LoraTrainer
from .models import FAMILY_LABELS, ModelProfiles
from .review_rounds import ReviewRounds
from .reviews import ReviewStore
from .service_config import ServiceConfig
from .services import ComfyService
from .tags import TagLookup
from .tools.convert import ConvertTasks
from .tools.postprocess import PostprocessMixin
from .tools.tagger import TaggerMixin
from .tools.workspace import ToolWorkspace
from .trash import OutputTrash
from .util import state_file

DEFAULT_URL = 'http://127.0.0.1:8188'


class ImageRuntime(LabMixin, TaggerMixin, PostprocessMixin, GenerationMixin):
    _file_index = (0.0, None)

    def __init__(self, paths, works, llm):
        self.paths, self.works, self.llm = paths, works, llm
        self.stop = threading.Event()
        self._thread = None
        # One lock guards the queue and GPU ownership, as the generation worker and the API share them.
        self.lock = threading.RLock()
        self.queue = JobQueue(state_file(paths, 'queue.json'), self.lock)
        self.comfy = Comfy(DEFAULT_URL)
        # Where queued jobs are made, by the job's ``service``.
        self.service_config = ServiceConfig(paths, llm.vault)
        # Where adopted images are uploaded (decision 0023).
        self.deploy_targets = DeployTargets(paths, llm.vault)
        self.services = {
            service.id: service
            for service in (
                ComfyService(self),
                NovelAIService(self.service_config, self.stop),
                PixAIService(self.service_config, self.stop),
            )
        }
        self.models = ModelProfiles(paths)
        # Only jobs on this PC's GPU count for the GPU broker; an internet service's job does not hold it.
        self.gpu = GpuBroker(paths, self.lock, lambda: self.queue.select(self.on_gpu))
        self.control = ComfyControl(self)
        self.tags = TagLookup(paths)
        self.gallery = Gallery(paths)
        self.reviews = ReviewStore(paths, self.gallery)
        self.deploy = DeployUploads(self)
        self.reviews.adjust_plan = self._adjust_export_plan
        self.tools = ToolWorkspace(paths, self.gallery)
        self.convert = ConvertTasks(paths, self.tools, self.gallery)
        self.trash = OutputTrash(paths, self.gallery, self.tools)
        self.trainer = LoraTrainer(self)
        self.installs = Installs(self)
        self.load_queue()
        self._resume_sent_jobs()
        self.rounds = ReviewRounds(self)
        self.reviews.listeners.append(self.rounds.human_changed)

    def _resume_sent_jobs(self):
        """Jobs a restart cut off after their request went to a service that keeps results (PixAI) wait again for that
        result instead of being marked interrupted: asking again would pay twice."""
        with self.queue.editing() as jobs:
            for job in jobs:
                service = self.services.get(job.get('service') or 'comfyui')
                if job['status'] == 'interrupted' and job.get('prompt_id') and service and service.resumable:
                    job.update(
                        status='queued',
                        resume=job['prompt_id'],
                        progress=Msg(
                            'server.worker.resuming', 'Getting the result of the request already sent'
                        ),
                    )

    def _adjust_export_plan(self, plan, filters):
        """Apply each work's completeness board to the deployment export's missing list (#45)."""
        if filters.get('work'):
            ids = {filters['work']}
        else:
            ids = {m.split('/')[0] for m in plan['missing']} | {s.split('/')[0] for s in plan['manifest']}
        for work_id in sorted(ids):
            try:
                work = self.works.get(work_id)
            except AppError:
                continue  # images of a work that is gone: its combinations stay as the gallery sees them
            plan = board.adjust_export_plan(self, work, plan, {**filters, 'work': work_id})
        return plan

    # --- worker thread (started with the app, stopped on shutdown) ----------------------------------------------------
    def start(self):
        if self._thread is None:
            self.stop.clear()
            self._thread = threading.Thread(target=self.worker, name='image-worker', daemon=True)
            self._thread.start()

    def check_generation(self, generation):
        """Compare an image's generation settings with this PC's image server (#169): files present, names lacking."""
        from .tools import gen_info

        catalog = self.comfy.catalog()
        if not catalog.get('connected'):
            return generation
        stamp, index = self._file_index
        # The model folders' hash records are read at most once a minute.
        if index is None or time.monotonic() - stamp > 60:
            index = gen_info.file_index(self.installs.model_folders())
            self._file_index = (time.monotonic(), index)
        return gen_info.enrich(generation, catalog, index)

    def shutdown(self):
        self.stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        # Programs started by the app must not outlive it, still running and holding its log files open.
        self.trainer.shutdown()
        self.installs.shutdown()
        self.control.shutdown()

    # --- connection ------------------------------------------------------------------------------------------------
    def connection(self):
        return {'status': self.control.status(), 'config': self.control.config, 'gpu': self.gpu.status()}

    def locate(self):
        """ComfyUI installs on this PC (the running one first) and the running one's model folders."""
        return {
            'candidates': comfy_locate.candidates(self.comfy.url),
            'folders': comfy_locate.model_folders(self.comfy.url) or {},
        }

    def catalog(self):
        """What the server offers (models, LoRAs, samplers …) with each model's family."""
        catalog = self.comfy.catalog()
        if catalog.get('connected'):
            catalog['families'] = self.models.classify(catalog)
        catalog['family_labels'] = FAMILY_LABELS
        return catalog

    # --- what the jobs panel shows besides LLM work (#89) -------------------------------------------------------------
    def activity(self):
        """Unfinished image work, in the shared life cycle: the queue, an install, a LoRA training, conversions."""
        out = []
        counts = {}
        for job in self.queue.select(lambda j: j['status'] in UNFINISHED):
            counts[job['status']] = counts.get(job['status'], 0) + 1
        if counts:
            out.append(
                {
                    'kind': 'image_queue',
                    'status': RUNNING if counts.get(RUNNING) or counts.get(CANCELLING) else QUEUED,
                    'counts': counts,
                    'paused': self.queue.paused,
                }
            )
        run = self.installs.run
        if run and run['status'] in UNFINISHED:
            out.append({'kind': 'install', 'status': run['status'], 'section': run['section']})
        if self.trainer.active:
            work_id, character_id, run_id = self.trainer.active
            try:
                record = lora_store.read(lora_store.run_file(self.works.get(work_id), character_id, run_id))
            except Exception:  # the record is being written or the work is gone: show it as running
                record = {'status': RUNNING}
            out.append(
                {
                    'kind': 'lora',
                    'status': record.get('status', RUNNING),
                    'phase': record.get('phase'),
                    'title': record.get('output_name') or run_id,
                    'work_id': work_id,
                    'character_id': character_id,
                }
            )
        for run in self.deploy.active():
            out.append(
                {
                    'kind': 'deploy',
                    'status': run['status'],
                    'done': run['done'],
                    'total': run['total'],
                    'title': run['target_name'],
                }
            )
        for task in list(self.convert.tasks.values()):
            if task['status'] == RUNNING:
                out.append(
                    {'kind': 'convert', 'status': RUNNING, 'done': task['done'], 'total': task['total']}
                )
        return out

    # --- image services on the internet (#41) ---------------------------------------------------------------------
    def image_services(self):
        return self.service_config.public({i for i, s in self.services.items() if i != 'comfyui'})

    def save_image_services(self, doc):
        self.service_config.save(doc)
        return self.image_services()

    def _internet_service(self, ident):
        service = self.services.get(ident)
        if service is None or ident == 'comfyui':
            raise ValueError(Msg('server.image.services.unknown', 'Unknown image service: {id}', id=ident))
        return service

    def image_service_info(self, ident):
        """Models, choices and defaults of one internet service, for its settings panel."""
        return self._internet_service(ident).info()

    def image_service_account(self, ident):
        """The account's state (credit left) as the service reports it."""
        return self._internet_service(ident).account()

    # --- review hooks of the generation worker ----------------------------------------------------------------------
    def review_wanted(self):
        return bool(self.rounds.settings['enabled'])

    def register_jobs(self, jobs):
        self.rounds.register(jobs)

    def attach_retry(self, old, new):
        self.rounds.attach_retry(old, new)

    def process_ready(self):
        return self.rounds.process_ready()

    def after_remove(self):
        # Inpaint jobs keep a copy of their mask; copies of jobs that are gone are deleted.
        keep = {j['post_mask'] for j in self.queue.select(lambda j: j.get('post_mask'))}
        self.tools.prune_job_masks(keep)

    def auto_loras(self, work, character_id, outfit_id, family):
        # The character's registered LoRAs marked "auto apply" join its generations.
        return lora_models.auto_loras(work, character_id, outfit_id, family)
