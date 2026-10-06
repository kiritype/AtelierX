"""NovelAI image generation (#42), from the official API description at https://image.novelai.net/docs/index.html.

One request makes one image: POST /ai/generate-image with a persistent API token. The answer is the image itself
(a ZIP with the PNG, or base64 JSON when asked for), so a job is done when ``submit`` returns. The model picks the
version (V4.5, V5 …); V4 and later models also need the prompt as ``v4_prompt`` / ``v4_negative_prompt``.
The account's Anlas comes from GET /user/subscription.
"""

import base64
import io
import os
import re
import zipfile

from ...core.i18n import Msg
from .common import InternetService, choice, number, whole

IMAGE_URL = os.environ.get('ATELIERX_NOVELAI_IMAGE_URL', 'https://image.novelai.net')
API_URL = os.environ.get('ATELIERX_NOVELAI_API_URL', 'https://api.novelai.net')

MODELS = [
    {'id': 'nai-diffusion-4-5-full', 'name': 'V4.5 Full'},
    {'id': 'nai-diffusion-4-5-curated', 'name': 'V4.5 Curated'},
    {'id': 'nai-diffusion-5-full', 'name': 'V5 Full'},
    {'id': 'nai-diffusion-5-curated', 'name': 'V5 Curated'},
]
MODEL_NAME = re.compile(r'^[a-z0-9][a-z0-9-]{2,63}$')  # users may add models that come out later
SAMPLERS = (
    'k_euler_ancestral',
    'k_euler',
    'k_dpmpp_2s_ancestral',
    'k_dpmpp_2m_sde',
    'k_dpmpp_2m',
    'k_dpmpp_sde',
)
NOISE_SCHEDULES = ('karras', 'exponential', 'polyexponential')
DEFAULTS = {
    'model': 'nai-diffusion-4-5-full',
    'width': 832,
    'height': 1216,
    'steps': 28,
    'scale': 5.0,
    'sampler': 'k_euler_ancestral',
    'noise_schedule': 'karras',
    'quality_toggle': True,
    'uc_preset': 0,
    'seed': -1,
}
# Opus subscribers make an image of at most this size and steps, one at a time, without spending Anlas.
FREE_PIXELS = 1024 * 1024
FREE_STEPS = 28


class NovelAIService(InternetService):
    id = 'novelai'
    name = 'NovelAI'

    def validate_settings(self, settings):
        raw = settings or {}
        model = raw.get('model') or DEFAULTS['model']
        if not isinstance(model, str) or not MODEL_NAME.match(model):
            raise ValueError(Msg('server.novelai.model', 'Choose a NovelAI model.'))
        width = whole(raw.get('width'), 64, 2048, DEFAULTS['width'])
        height = whole(raw.get('height'), 64, 2048, DEFAULTS['height'])
        if width % 64 or height % 64:
            raise ValueError(Msg('server.novelai.size', 'NovelAI needs a width and height in steps of 64.'))
        return {
            'model': model,
            'width': width,
            'height': height,
            'steps': whole(raw.get('steps'), 1, 50, DEFAULTS['steps']),
            'scale': number(raw.get('scale'), 0, 10, DEFAULTS['scale']),
            'sampler': choice(raw.get('sampler'), SAMPLERS, DEFAULTS['sampler']),
            'noise_schedule': choice(raw.get('noise_schedule'), NOISE_SCHEDULES, DEFAULTS['noise_schedule']),
            'quality_toggle': raw.get('quality_toggle', DEFAULTS['quality_toggle']) is not False,
            'uc_preset': whole(raw.get('uc_preset'), 0, 4, DEFAULTS['uc_preset']),
            'seed': whole(raw.get('seed'), -1, 2**32 - 1, -1),
        }

    def request_body(self, job):
        snap = job['snapshot']
        s = snap['settings']
        positive, negative = snap['positive'], snap['negative']
        return {
            'input': positive,
            'model': s['model'],
            'action': 'generate',
            'parameters': {
                'params_version': 3,
                'width': s['width'],
                'height': s['height'],
                'scale': s['scale'],
                'sampler': s['sampler'],
                'steps': s['steps'],
                'n_samples': 1,
                'seed': job['seed'],
                'noise_schedule': s['noise_schedule'],
                'qualityToggle': s['quality_toggle'],
                'ucPreset': s['uc_preset'],
                'negative_prompt': negative,
                'v4_prompt': {
                    'caption': {'base_caption': positive, 'char_captions': []},
                    'use_coords': False,
                    'use_order': True,
                },
                'v4_negative_prompt': {
                    'caption': {'base_caption': negative, 'char_captions': []},
                    'legacy_uc': False,
                },
            },
        }

    def submit(self, job):
        body = self.request_body(job)
        key = self.key()
        response = self.send(
            lambda client: client.post(
                f'{IMAGE_URL}/ai/generate-image',
                json=body,
                headers={'Authorization': f'Bearer {key}', 'Accept': 'application/zip, application/json'},
            )
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(self.refused(response))
        return {'id': None, 'record': body, 'image': _image_of(response)}

    def poll(self, job, sent):
        return {'image': sent['image']}

    def cancel(self, job, sent):
        return False  # already answered: the image is kept

    def account(self):
        """Tier and Anlas left, for the generate screen; None when it cannot be read."""
        key = self.key()
        with self.client() as client:
            response = client.get(f'{API_URL}/user/subscription', headers={'Authorization': f'Bearer {key}'})
        if response.status_code != 200:
            raise RuntimeError(self.refused(response))
        doc = response.json()
        steps = doc.get('trainingStepsLeft') or {}
        anlas = None
        if isinstance(steps, dict):
            parts = [steps.get('fixedTrainingStepsLeft'), steps.get('purchasedTrainingSteps')]
            if any(isinstance(p, int) for p in parts):
                anlas = sum(p for p in parts if isinstance(p, int))
        return {
            'tier': doc.get('tier'),
            'active': doc.get('active'),
            'anlas': anlas,
            'opus': doc.get('tier') == 3,
        }

    def info(self):
        return {
            'models': MODELS,
            'samplers': list(SAMPLERS),
            'noise_schedules': list(NOISE_SCHEDULES),
            'defaults': DEFAULTS,
            'free': {'pixels': FREE_PIXELS, 'steps': FREE_STEPS},
        }


def _image_of(response):
    """The PNG in NovelAI's answer: a ZIP with image_0.png, or JSON with base64 images."""
    kind = response.headers.get('content-type', '')
    data = response.content
    if 'json' in kind:
        doc = response.json()
        images = doc.get('images') if isinstance(doc, dict) else doc
        first = images[0] if images else None
        if isinstance(first, dict):
            first = first.get('image')
        if not first:
            raise RuntimeError(Msg('server.novelai.no_image', 'NovelAI returned no image.'))
        return base64.b64decode(first)
    if data[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith('.png')]
            if not names:
                raise RuntimeError(Msg('server.novelai.no_image', 'NovelAI returned no image.'))
            return archive.read(names[0])
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return data
    raise RuntimeError(Msg('server.novelai.no_image', 'NovelAI returned no image.'))
