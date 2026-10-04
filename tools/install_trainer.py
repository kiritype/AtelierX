"""Install the LoRA trainer (anima_lora) at the tested version, for Settings → Image → LoRA training.

    uv run python tools/install_trainer.py              # show the plan
    uv run python tools/install_trainer.py --yes        # carry it out
    uv run python tools/install_trainer.py --dir D:\\trainers --yes

anima_lora (MIT, with Apache-2.0 parts) and its companion anime_tools are cloned from their own repositories into
<app>/vendor/ (or --dir), ``uv sync`` builds anima_lora's own Python environment (Python 3.13 and a CUDA build of
PyTorch: several GB), and the app's small patch is applied so preprocessing uses the model files chosen in the
settings. Nothing is shipped with the app. Existing folders are left alone.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'trainer' / 'anima_lora' / 'preprocess-model-paths.patch'
REPOS = (
    ('anime_tools', 'https://github.com/sorryhyun/anime_tools.git', 'v0.7.5'),
    ('anima_lora', 'https://github.com/sorryhyun/anima_lora.git', '69ff962'),
)


def run(cmd, cwd=None):
    print('  $', ' '.join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def patched(folder):
    preprocess = folder / 'scripts' / 'tasks' / 'preprocess.py'
    return preprocess.is_file() and '# atelierx patch' in preprocess.read_text(
        encoding='utf-8', errors='replace'
    )


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Install the LoRA trainer (anima_lora).')
    parser.add_argument('--dir', help='Folder that gets anima_lora/ and anime_tools/ (default: <app>/vendor)')
    parser.add_argument('--yes', action='store_true', help='Carry out the plan')
    args = parser.parse_args(argv)
    base = Path(args.dir) if args.dir else ROOT / 'vendor'
    missing = [tool for tool in ('git', 'uv') if not shutil.which(tool)]
    if missing:
        parser.error('install first: ' + ', '.join(missing))

    print(f'Folder: {base}')
    steps = []
    for name, url, ref in REPOS:
        target = base / name
        if target.exists():
            print(f'  =  {name}: already there; left alone')
        else:
            print(f'  +  {name}: clone {url} at {ref}')
            steps.append(('clone', name, url, ref))
    trainer = base / 'anima_lora'
    if not (trainer / '.venv').is_dir():
        print('  +  anima_lora: uv sync (Python 3.13, CUDA PyTorch; several GB)')
        steps.append(('sync',))
    if not patched(trainer):
        print('  +  anima_lora: apply the model-path patch')
        steps.append(('patch',))
    if not steps:
        print('\nNothing to do.')
    elif not args.yes:
        print('\nRun again with --yes to carry this out.')
        return 0
    else:
        base.mkdir(parents=True, exist_ok=True)
        for step in steps:
            if step[0] == 'clone':
                _, name, url, ref = step
                run(['git', 'clone', url, base / name])
                run(['git', '-C', base / name, 'checkout', '--quiet', ref])
            elif step[0] == 'sync':
                run(['uv', 'sync'], cwd=trainer)
            else:
                run(['git', 'apply', PATCH], cwd=trainer)
    print('\nIn Settings → Image → LoRA training:')
    print(f'  trainer folder: {trainer}')
    print('  then the LoRA output folder (your image server LoRA folder) and the training model files.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
