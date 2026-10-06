"""The image module's long-lived state: image generation server connection, model families, GPU broker, queue."""

import threading

from ..core.i18n import AppError
from . import board, comfy_locate
from .comfy import Comfy
from .control import ComfyControl
from .gallery import Gallery
from .generation import GenerationMixin
from .gpu import GpuBroker
from .installs import Installs
from .job_queue import JobQueue
from .lab import LabMixin
from .lora import models as lora_models
from .lora.trainer import LoraTrainer
from .models import FAMILY_LABELS, ModelProfiles
from .review_rounds import ReviewRounds
from .reviews import ReviewStore
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
    def __init__(self, paths, works, llm):
        self.paths, self.works, self.llm = paths, works, llm
        self.stop = threading.Event()
        self._thread = None
        # One lock guards the queue and GPU ownership, as the generation worker and the API share them.
        self.lock = threading.RLock()
        self.queue = JobQueue(state_file(paths, 'queue.json'), self.lock)
        self.comfy = Comfy(DEFAULT_URL)
        # Where queued jobs are made, by the job's ``service``.
        self.services = {service.id: service for service in (ComfyService(self),)}
        self.models = ModelProfiles(paths)
        self.gpu = GpuBroker(paths, self.lock, lambda: self.queue.jobs)
        self.control = ComfyControl(self)
        self.tags = TagLookup(paths)
        self.gallery = Gallery(paths)
        self.reviews = ReviewStore(paths, self.gallery)
        self.reviews.adjust_plan = self._adjust_export_plan
        self.tools = ToolWorkspace(paths, self.gallery)
        self.convert = ConvertTasks(paths, self.tools, self.gallery)
        self.trash = OutputTrash(paths, self.gallery, self.tools)
        self.trainer = LoraTrainer(self)
        self.installs = Installs(self)
        self.load_queue()
        self.rounds = ReviewRounds(self)
        self.reviews.listeners.append(self.rounds.human_changed)

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
