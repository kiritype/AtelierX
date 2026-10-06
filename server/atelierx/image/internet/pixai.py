"""PixAI image generation (#43), from the official API description at https://platform.pixai.art/en/docs.

A job becomes a task: POST /v2/image/create returns its id, GET /v1/task/{id} (no more often than every 1.5 s) says
when it is done, and GET /v1/media/{id}/image gives the image. Results are not kept for long, so they are fetched as
soon as the task completes. A task cannot be called back. The task id stays on the job, so after a restart or a
failed download the app asks about the same task again instead of paying for a new one.

There is no API to list models or LoRAs: the usual models are listed here (users may add version ids), and LoRAs are
registered in Settings from their PixAI Model Market address.
"""

import os
import re
import time

from ...core.i18n import Msg
from ..services import ResultPending
from .common import InternetService, choice, number, whole

API_URL = os.environ.get('ATELIERX_PIXAI_API_URL', 'https://api.pixai.art')

MODELS = [
    {'id': '1861558740588989558', 'name': 'Haruka v2', 'type': 'sdxl'},
    {'id': '1954632828118619567', 'name': 'Hoshino v2', 'type': 'sdxl'},
    {'id': '1983308862240288769', 'name': 'Tsubaki.2', 'type': 'dit'},
]
VERSION_ID = re.compile(r'^\d{6,25}$')
ASPECT_RATIOS = ('1:1', '2:3', '3:2', '3:4', '4:3', '3:5', '5:3', '9:16', '16:9', '1:3', '3:1')
SIZES = ('1k', '1.5k')
MODES = ('lite', 'standard', 'pro', 'ultra')  # Tsubaki models only
SAMPLERS = (
    'Euler a',
    'Euler',
    'LMS',
    'Heun',
    'DPM2 Karras',
    'DPM2 a Karras',
    'DDIM',
    'DPM++ 2M Karras',
    'DPM++ 2S a Karras',
    'DPM++ SDE Karras',
    'DPM++ 2M SDE Karras',
    'Restart',
)
MAX_LORAS = 5
DEFAULTS = {
    'model': MODELS[0]['id'],
    'aspect_ratio': '2:3',
    'size': '1k',
    'mode': 'standard',
    'sampler': 'Euler a',
    'steps': 25,
    'cfg_scale': 6.0,
    'prompt_helper': False,  # the prompt is already composed from the library; the helper would rewrite it
    'loras': [],
    'seed': -1,
}
POLL_EVERY = 1.5


class PixAIService(InternetService):
    id = 'pixai'
    name = 'PixAI'
    # A task's result can be asked for again: after a restart or a failed download, no new request is needed.
    resumable = True

    def __init__(self, config, stop):
        super().__init__(config, stop)
        self._polled = {}

    def validate_settings(self, settings):
        raw = settings or {}
        model = str(raw.get('model') or DEFAULTS['model'])
        if not VERSION_ID.match(model):
            raise ValueError(Msg('server.pixai.model', 'Choose a PixAI model (its version id).'))
        loras = raw.get('loras') or []
        if not isinstance(loras, list) or len(loras) > MAX_LORAS:
            raise ValueError(Msg('server.pixai.loras', 'Use at most {n} LoRAs.', n=MAX_LORAS))
        picked = []
        for entry in loras:
            ident = str((entry or {}).get('id') or '')
            if not VERSION_ID.match(ident):
                raise ValueError(Msg('server.pixai.lora_id', 'A LoRA needs its PixAI version id.'))
            item = {'id': ident, 'weight': number(entry.get('weight'), 0, 1, 1.0)}
            if str(entry.get('trigger_words') or '').strip():
                item['trigger_words'] = str(entry['trigger_words']).strip()[:500]
            picked.append(item)
        return {
            'model': model,
            'aspect_ratio': choice(raw.get('aspect_ratio'), ASPECT_RATIOS, DEFAULTS['aspect_ratio']),
            'size': choice(raw.get('size'), SIZES, DEFAULTS['size']),
            'mode': choice(raw.get('mode'), MODES, DEFAULTS['mode']),
            'sampler': choice(raw.get('sampler'), SAMPLERS, DEFAULTS['sampler']),
            'steps': whole(raw.get('steps'), 1, 100, DEFAULTS['steps']),
            'cfg_scale': number(raw.get('cfg_scale'), 0, 30, DEFAULTS['cfg_scale']),
            'prompt_helper': bool(raw.get('prompt_helper', DEFAULTS['prompt_helper'])),
            'loras': picked,
            'seed': whole(raw.get('seed'), -1, 2**31 - 1, -1),
        }

    @staticmethod
    def kind(model):
        return next((m['type'] for m in MODELS if m['id'] == model), 'sdxl')

    def request_body(self, job):
        snap = job['snapshot']
        s = snap['settings']
        body = {
            'modelVersionId': s['model'],
            'prompt': snap['positive'],
            'negativePrompt': snap['negative'],
            'aspectRatio': s['aspect_ratio'],
            'size': s['size'],
            'seed': job['seed'] % 2**31,
            'batchSize': 1,
            'promptHelper': 'enable' if s['prompt_helper'] else 'disable',
        }
        if self.kind(s['model']) == 'dit':
            body['mode'] = s['mode']
        else:
            body['sampling'] = {'method': s['sampler'], 'steps': s['steps'], 'cfgScale': s['cfg_scale']}
        if s['loras']:
            body['loras'] = [
                {
                    'modelId': lora['id'],
                    'weight': lora['weight'],
                    **({'triggerWords': lora['trigger_words']} if lora.get('trigger_words') else {}),
                }
                for lora in s['loras']
            ]
        return body

    def _headers(self):
        return {'Authorization': f'Bearer {self.key()}'}

    def submit(self, job):
        body = self.request_body(job)
        headers = self._headers()
        response = self.send(
            lambda client: client.post(f'{API_URL}/v2/image/create', json=body, headers=headers)
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(self.refused(response))
        task = response.json()
        if not task.get('id'):
            raise RuntimeError(Msg('server.pixai.no_task', 'PixAI did not start a task.'))
        return {'id': str(task['id']), 'record': body}

    def poll(self, job, sent):
        task_id = sent['id']
        # PixAI asks for no more than one status check every 1.5 seconds.
        moment = time.monotonic()
        if moment - self._polled.get(task_id, 0) < POLL_EVERY:
            return None
        self._polled[task_id] = moment
        with self.client() as client:
            response = client.get(f'{API_URL}/v1/task/{task_id}', headers=self._headers())
        if response.status_code == 429:
            return None
        if response.status_code != 200:
            raise ResultPending(self.refused(response), task_id)
        task = response.json()
        status = task.get('status')
        if status in ('waiting', 'running'):
            return None
        if status != 'completed':
            self._polled.pop(task_id, None)
            return {
                'error': Msg(
                    'server.pixai.task_failed',
                    'PixAI could not make the image ({status}).',
                    status=status or '?',
                )
            }
        self._polled.pop(task_id, None)
        outputs = task.get('outputs') or {}
        media = (outputs.get('mediaIds') or [None])[0]
        if not media:
            return {'error': Msg('server.pixai.no_image', 'PixAI returned no image.')}
        return {'image': self.download(task_id, media)}

    def download(self, task_id, media):
        try:
            with self.client() as client:
                response = client.get(f'{API_URL}/v1/media/{media}/image', headers=self._headers())
        except Exception as error:
            raise ResultPending(
                Msg(
                    'server.pixai.download_failed',
                    'The image was made but could not be downloaded: {error}',
                    error=str(error)[:300],
                ),
                task_id,
            ) from error
        if response.status_code in (404, 410):
            raise RuntimeError(
                Msg(
                    'server.pixai.expired',
                    'PixAI no longer has this image (results are kept only for a while).',
                )
            )
        if response.status_code != 200 or not response.content:
            raise ResultPending(
                Msg(
                    'server.pixai.download_failed',
                    'The image was made but could not be downloaded: {error}',
                    error=f'HTTP {response.status_code}',
                ),
                task_id,
            )
        return response.content

    def cancel(self, job, sent):
        return False  # PixAI has no way to call a task back; its image is kept when it arrives

    def account(self):
        return {'credits': None}  # PixAI's API does not report credits

    def info(self):
        return {
            'models': MODELS,
            'aspect_ratios': list(ASPECT_RATIOS),
            'sizes': list(SIZES),
            'modes': list(MODES),
            'samplers': list(SAMPLERS),
            'max_loras': MAX_LORAS,
            'loras': self.config.loras(self.id),
            'defaults': DEFAULTS,
        }
