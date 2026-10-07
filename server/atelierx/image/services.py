"""Generation services (#86): where a queued image job is actually made.

The worker (generation.py) runs the same steps for every service: wait until the service can take the job, send
it, check on it until it is done, and on a cancel ask the service to stop. A service only knows how to talk to its
server; queue state, saving and review stay with the worker. ComfyUI on this PC is the first service; image services
on the internet (#42, #43) follow the same shape.
"""

import json
from urllib.parse import quote, urlencode

from ..core.i18n import Msg
from . import extensions
from .workflow import build_workflow, defaults


class ResultPending(RuntimeError):
    """The service has (or is making) the image but it could not be fetched. Asking about ``task_id`` again needs no new
    request, so a retry continues with it."""

    def __init__(self, msg, task_id):
        super().__init__(msg)
        self.task_id = task_id


class GenerationService:
    """What the worker needs from a service. ``id`` is the job's ``service`` value."""

    id = ''
    # Runs on this PC's GPU: the worker takes the GPU broker's turn first and LoRA training waits for it.
    local_gpu = False
    # Whether a sent job can be asked about again later (after a restart or a failed download) by its id.
    resumable = False
    # Whether an image that arrives after a cancel is saved (a request to a paid service cannot be called back).
    keep_on_cancel = False
    # How long the worker waits for a free service and for one result.
    wait_limit = 1800
    result_limit = 1800

    def busy(self):
        """True while the service is working for someone else and the job should wait."""
        return False

    def busy_too_long(self):
        return Msg('server.worker.service_busy', 'Waited 30 minutes for the image service.')

    def validate_settings(self, settings):
        """The settings a job keeps, checked and completed with defaults; ValueError for the user's mistake."""
        return settings

    def submit(self, job):
        """Send the job. Returns what was sent: ``{'id': <the service's id for it>, 'record': <request to keep>}``."""
        raise NotImplementedError

    def poll(self, job, sent):
        """None while it runs; then ``{'image': bytes}``, ``{'entry': raw result}`` or ``{'error': Msg}``."""
        raise NotImplementedError

    def cancel(self, job, sent):
        """Ask the service to stop. True when the job is surely gone (no result will come), False to keep polling."""
        return True

    def too_long(self):
        return Msg('server.worker.result_too_long', 'Waited more than 30 minutes for the result.')


class ComfyService(GenerationService):
    """ComfyUI on this PC. Jobs wait while other clients use it; its queue and history are polled over HTTP."""

    id = 'comfyui'
    local_gpu = True

    def __init__(self, runtime):
        # The runtime, for its current client (tests and the connection settings swap it) and the graphs of tool jobs.
        self.rt = runtime

    @property
    def comfy(self):
        return self.rt.comfy

    def busy(self):
        # Never clear or interrupt someone else's queue.
        queue = self.comfy.request('/queue')
        return bool(queue.get('queue_running') or queue.get('queue_pending'))

    def busy_too_long(self):
        return Msg(
            'server.worker.waited_30_minutes_for_other_comfyui', 'Waited 30 minutes for other ComfyUI work.'
        )

    def graph(self, job):
        kind = job.get('kind')
        if kind == 'tag':
            return self.rt.tag_graph(job)
        if kind == 'post':
            return self.rt.post_graph(job)
        snap = job['snapshot']
        settings = snap['settings']
        if settings.get('patches') or settings.get('fallback'):
            # Queued work does not stop to ask (#178): what ComfyUI no longer has is left out and noted.
            catalog = self.comfy.catalog()
            if catalog.get('connected'):
                settings = extensions.apply(
                    {**settings, 'missing': 'skip'},
                    catalog,
                    lambda key: list(catalog.get(key) or []),
                    defaults(catalog),
                )
                if settings.get('skipped'):
                    snap['settings'] = settings
        return build_workflow(settings, snap['positive'], snap['negative'], job['seed'])

    def submit(self, job):
        graph = self.graph(job)
        response = self.comfy.request('/prompt', {'prompt': graph, 'client_id': 'atelierx-' + job['id']})
        if response.get('node_errors') or not response.get('prompt_id'):
            raise RuntimeError(
                Msg(
                    'server.worker.workflow_validation_failed',
                    'Workflow validation failed: {response}',
                    response=json.dumps(response, ensure_ascii=False)[:3000],
                )
            )
        return {'id': response['prompt_id'], 'record': graph}

    def poll(self, job, sent):
        prompt_id = sent['id']
        history = self.comfy.request('/history/' + quote(prompt_id))
        if prompt_id not in history:
            return None
        entry = history[prompt_id]
        if entry.get('status', {}).get('status_str') == 'error':
            return {
                'error': Msg(
                    'server.worker.comfyui_generation_error',
                    'ComfyUI generation error: {status}',
                    status=json.dumps(entry['status'].get('messages', []), ensure_ascii=False)[-2500:],
                )
            }
        if job.get('kind') == 'tag':
            return {'entry': entry}
        images = entry.get('outputs', {}).get('output', {}).get('images', [])
        if not images:
            return {'error': Msg('server.worker.comfyui_returned_no_image', 'ComfyUI returned no image.')}
        item = images[0]
        data = self.comfy.request(
            '/view?' + urlencode({k: item.get(k, '') for k in ('filename', 'subfolder', 'type')}), raw=True
        )
        return {'image': data}

    def cancel(self, job, sent):
        prompt_id = sent['id']
        queue = self.comfy.request('/queue')
        if any(item[1] == prompt_id for item in queue.get('queue_running', [])):
            # Interrupted, it ends in history as an error, which the worker then reads as the cancel.
            self.comfy.request('/interrupt', {'prompt_id': prompt_id})
            return False
        if any(item[1] == prompt_id for item in queue.get('queue_pending', [])):
            self.comfy.request('/queue', {'delete': [prompt_id]})
            return True
        return False

    def too_long(self):
        return Msg(
            'server.worker.waited_more_than_30_minutes_for',
            'Waited more than 30 minutes for the result. Check progress in ComfyUI.',
        )
