"""Image settings sections (Settings → Image). Each section is one JSON file in config/image/.

Every section is validated here and merged into its file (keys the page does not know are kept).
The connection keeps its own endpoint because it also controls the server process.
"""

import copy

from ..core.i18n import Msg
from .util import atomic_json, read_json, settings_file

GPU_KINDS = ('generation', 'tool', 'vlm', 'training')
MAX_TEXT = 1000


def _text(value, name, allow_empty=True):
    if value is None:
        value = ''
    if not isinstance(value, str) or len(value) > MAX_TEXT or (not allow_empty and not value):
        raise ValueError(Msg('server.image.settings.check_the_text', '{name}: check the text.', name=name))
    return value.strip()


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(
            Msg(
                'server.image.settings.whole_number',
                '{name}: must be a whole number from {low} to {high}.',
                name=name,
                low=low,
                high=high,
            )
        )
    return value


def _lines(value, name):
    if value in (None, ''):
        return []
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ValueError(
            Msg('server.image.settings.one_per_line', '{name}: put one item on each line.', name=name)
        )
    return [_text(x, name) for x in value]


def _gpu(values, current):
    result = copy.deepcopy(current)
    if 'enabled' in values:
        if not isinstance(values['enabled'], bool):
            raise ValueError(
                Msg('server.image.settings.gpu_switch', 'The GPU wait switch must be true or false.')
            )
        result['enabled'] = values['enabled']
    if 'min_free_vram_mb' in values:
        limits = result.setdefault('min_free_vram_mb', {})
        for kind in GPU_KINDS:
            if kind in (values['min_free_vram_mb'] or {}):
                limits[kind] = _integer(values['min_free_vram_mb'][kind], kind, 0, 200000)
    if 'watch_processes' in values:
        result['watch_processes'] = _lines(values['watch_processes'], 'watch_processes')
    return result


def _models(values, current):
    result = {**current}
    if 'models_dir' in values:
        folder = _text(values['models_dir'], 'models_dir')
        if folder:
            result['models_dir'] = folder
        else:
            result.pop('models_dir', None)
    return result


def _tags(values, current):
    result = {**current}
    if 'exclude' in values:
        result['exclude'] = _lines(values['exclude'], 'exclude')
    return result


TRAINING_BASES = ('official', 'generation')
MODEL_KEYS = ('dit', 'text_encoder', 'vae')


def _training(values, current):
    result = copy.deepcopy(current)
    for key in ('trainer_dir', 'trainer_python', 'lora_dir'):
        if key in values:
            result[key] = _text(values[key], key)
    if 'bases' in values:
        bases = result.setdefault('bases', {})
        for base in TRAINING_BASES:
            given = (values['bases'] or {}).get(base)
            if given is not None:
                bases[base] = {key: _text(given.get(key), f'{base}.{key}') for key in MODEL_KEYS}
    return result


def _presets(values, current):
    result = {**current}
    if 'preview_seed' in values:
        result['preview_seed'] = _integer(values['preview_seed'], 'preview_seed', 0, 2**32 - 1)
    return result


def _downloads(values, current):
    result = {**current}
    if 'civitai_key' in values:
        key = values['civitai_key'] or ''
        # Only a vault entry is stored here (decision 0011), never the key itself.
        if key and not (isinstance(key, str) and key.startswith('secret:') and len(key) <= 200):
            raise ValueError(
                Msg('server.llm.secret_reference', 'Save credentials in Settings and select the saved entry.')
            )
        result['civitai_key'] = key
    if 'nsfw' in values:
        result['nsfw'] = bool(values['nsfw'])
    return result


SECTIONS = {
    'gpu': (
        'gpu.json',
        {
            'enabled': False,
            'min_free_vram_mb': {'generation': 2048, 'tool': 1024, 'vlm': 16384, 'training': 16384},
            'watch_processes': [],
        },
        _gpu,
    ),
    'models': ('models.json', {'models_dir': ''}, _models),
    # Getting models from Civitai (#161): the vault entry of the API key, and whether searches show adult models.
    'downloads': ('downloads.json', {'civitai_key': '', 'nsfw': False}, _downloads),
    # Style presets (#169): the one seed every preview uses, so the previews compare side by side.
    'presets': ('presets.json', {'preview_seed': 1234567}, _presets),
    # Tags left out when tagger results are exported (watermarks, signatures ...).
    'tags': ('tags.json', {'exclude': []}, _tags),
    # LoRA training: the anima_lora folder and its Python, where finished LoRAs go, and the training models.
    'training': (
        'training.json',
        {
            'trainer_dir': '',
            'trainer_python': '.venv/Scripts/python.exe',
            'lora_dir': '',
            'bases': {base: dict.fromkeys(MODEL_KEYS, '') for base in TRAINING_BASES},
        },
        _training,
    ),
}


def read(paths, section):
    name, defaults, _ = SECTIONS[section]
    path = settings_file(paths, name)
    saved = read_json(path, {})
    if not isinstance(saved, dict):
        saved = {}
    merged = copy.deepcopy(defaults)
    merged.update(saved)
    if section == 'gpu':
        # gpu.json exists only once the checks are wanted; an absent file means "off".
        merged['enabled'] = bool(saved.get('enabled', True)) if path.is_file() else False
        merged['min_free_vram_mb'] = {**defaults['min_free_vram_mb'], **(saved.get('min_free_vram_mb') or {})}
    return merged, saved


def get(paths, section):
    if section not in SECTIONS:
        raise ValueError(Msg('server.image.settings.unknown_section', 'Unknown settings section.'))
    return read(paths, section)[0]


def save(paths, section, values):
    if section not in SECTIONS:
        raise ValueError(Msg('server.image.settings.unknown_section', 'Unknown settings section.'))
    if not isinstance(values, dict):
        raise ValueError(Msg('server.image.settings.values_object', 'values must be an object.'))
    name, _, validate = SECTIONS[section]
    current, saved = read(paths, section)
    updated = validate(values, current)
    atomic_json(settings_file(paths, name), {**saved, **updated})
    return read(paths, section)[0]
