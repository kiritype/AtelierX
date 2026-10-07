"""Prepare the external trainer (anima_lora) for a run (23-lora-training: 학습 도구 연결).

The trainer is installed separately (tools/install_trainer.py). Before each run the app checks that it carries the
small preprocessing patch, copies the app's method files into it and writes the training-model presets from the
settings into a marked block of ``configs/presets.toml``, so the trainer needs no hand edits.
"""

import filecmp
import shutil
from pathlib import Path

from ...core.i18n import Msg
from ..settings import MODEL_KEYS, get
from .link import app_folder


def shipped(paths):
    """The patch and method files ship with the program, next to its defaults/ folder."""
    return Path(paths.defaults).parent / 'trainer' / 'anima_lora'


# The earlier image tool shipped the same patch under its own marker.
PATCH_MARKERS = ('# atelierx patch', '# asset-studio patch')
BLOCK_START = '# >>> atelierx: written by AtelierX from config/image/training.json'
BLOCK_END = '# <<< atelierx'
TRAINER_KEYS = {'dit': 'pretrained_model_name_or_path', 'text_encoder': 'qwen3', 'vae': 'vae'}

# Training bases: the official Anima base, or the Anima fine-tune used for generation.
BASES = {
    'official': {
        'label': Msg('server.trainer_setup.official_anima_base', 'Official Anima base'),
        'preset': 'atelierx_base',
        'cache_dir': 'post_image_dataset/atelierx_base',
    },
    'generation': {
        'label': Msg('server.trainer_setup.generation_model', 'Generation model'),
        'preset': 'atelierx',
        'cache_dir': 'post_image_dataset/atelierx',
    },
}
METHODS = {
    'atelierx_tlora': 'T-LoRA (dim 32, alpha 32)',
    'atelierx_lora': 'LoRA (dim 32, alpha 128)',
}


def settings(paths):
    values = get(paths, 'training')
    trainer = values.get('trainer_dir') or str(Path(paths.root) / 'vendor' / 'anima_lora')
    return {**values, 'trainer_dir': str(Path(trainer))}


def configured_bases(values):
    """``{id: {...BASES[id], paths, base_model}}`` for bases whose three files are all set."""
    result = {}
    for ident, base in BASES.items():
        files = (values.get('bases') or {}).get(ident) or {}
        if all(files.get(key) for key in MODEL_KEYS):
            stem = Path(files['dit']).stem
            result[ident] = {**base, 'paths': files, 'base_model': stem}
    return result


def status(paths):
    """What the training settings screen shows: whether the trainer and each file are found."""
    values = settings(paths)
    trainer = Path(values['trainer_dir'])
    preprocess = trainer / 'scripts' / 'tasks' / 'preprocess.py'
    text = preprocess.read_text(encoding='utf-8', errors='replace') if preprocess.is_file() else ''
    files = {}
    for base in BASES:
        for key in MODEL_KEYS:
            path = ((values.get('bases') or {}).get(base) or {}).get(key)
            files[f'{base}.{key}'] = bool(path) and Path(path).is_file()
    return {
        'settings': values,
        'trainer_found': (trainer / 'train.py').is_file(),
        'python_found': (trainer / values['trainer_python']).is_file(),
        'patched': any(marker in text for marker in PATCH_MARKERS),
        'lora_dir_found': app_folder(paths, values).is_dir(),
        'lora_dir': str(app_folder(paths, values)),
        'files': files,
        'bases': [{'id': k, 'label': v['label']} for k, v in configured_bases(values).items()],
        'methods': [{'id': k, 'label': v} for k, v in METHODS.items()],
    }


def _preset_block(bases):
    lines = [BLOCK_START]
    for base in bases.values():
        lines.append(f'[{base["preset"]}]')
        for key, field in TRAINER_KEYS.items():
            lines.append(f'{field} = "{str(base["paths"][key]).replace(chr(92), "/")}"')
        lines += [
            'vocab_pack = ""',
            'torch_compile = false',
            'use_repa = false',
            f'lora_cache_dir = "{base["cache_dir"]}"',
            '',
        ]
    lines.append(BLOCK_END)
    return '\n'.join(lines) + '\n'


def write_presets(path, bases):
    """Replace the app's marked block in presets.toml, leaving the trainer's own presets alone."""
    text = path.read_text(encoding='utf-8') if path.is_file() else ''
    if BLOCK_START in text and BLOCK_END in text:
        head, rest = text.split(BLOCK_START, 1)
        text = head.rstrip('\n') + '\n\n' + rest.split(BLOCK_END, 1)[1].lstrip('\n')
    names = {base['preset'] for base in bases.values()}
    for line in text.splitlines():
        if line.startswith('[') and line.strip().strip('[]') in names:
            raise ValueError(
                Msg(
                    'server.trainer_setup.preset_taken',
                    '{path} already has a [{name}] preset. The app manages that name; remove that section and try again.',
                    path=str(path),
                    name=line.strip().strip('[]'),
                )
            )
    path.write_text(text.rstrip('\n') + '\n\n' + _preset_block(bases), encoding='utf-8')


def prepare(paths):
    """Check and configure the trainer; returns (settings, configured bases). Raises with how to fix it."""
    values = settings(paths)
    trainer = Path(values['trainer_dir'])
    if not (trainer / 'train.py').is_file():
        raise ValueError(
            Msg(
                'server.trainer_setup.trainer_missing',
                'The trainer (anima_lora) was not found: {trainer}. Install it with tools/install_trainer.py.',
                trainer=str(trainer),
            )
        )
    preprocess = trainer / 'scripts' / 'tasks' / 'preprocess.py'
    if not preprocess.is_file() or not any(
        m in preprocess.read_text(encoding='utf-8') for m in PATCH_MARKERS
    ):
        raise ValueError(
            Msg(
                'server.trainer_setup.not_patched',
                'The model-path patch is not applied to anima_lora. Run git apply "{patch}" in the trainer folder.',
                patch=str(shipped(paths) / 'preprocess-model-paths.patch'),
            )
        )
    bases = configured_bases(values)
    if not bases:
        raise ValueError(
            Msg(
                'server.trainer_setup.set_models',
                'Set the training model files in Settings → Image → LoRA training.',
            )
        )
    for base in bases.values():
        for key in MODEL_KEYS:
            if not Path(base['paths'][key]).is_file():
                raise ValueError(
                    Msg(
                        'server.trainer_setup.training_model_file_not_found',
                        'Training model file not found: {paths}',
                        paths=base['paths'][key],
                    )
                )
    methods = trainer / 'configs' / 'methods'
    methods.mkdir(parents=True, exist_ok=True)
    for source in sorted((shipped(paths) / 'methods').glob('*.toml')):
        target = methods / source.name
        if not target.is_file() or not filecmp.cmp(source, target, shallow=False):
            shutil.copyfile(source, target)
    write_presets(trainer / 'configs' / 'presets.toml', bases)
    return values, bases
