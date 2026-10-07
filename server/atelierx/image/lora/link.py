"""Where trained LoRAs live and how ComfyUI sees them (#160, decision 0025).

The originals stay in the app: the LoRA folder of the training settings, ``output/loras/`` when it is left empty. ComfyUI
reads them through a folder junction (a symbolic link outside Windows) named ``atelierx`` inside one of its own LoRA
folders, so a new LoRA shows up there without copying. Nothing is ever overwritten: a different ``atelierx`` folder or
link in ComfyUI is reported and left alone.
"""

import os
import shutil
import sys
from pathlib import Path

from ...core.i18n import Msg

LINK_NAME = 'atelierx'


def app_folder(paths, values):
    """The folder trained LoRAs are written to; made when missing."""
    folder = Path(values.get('lora_dir') or Path(paths.output) / 'loras')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def comfy_folder(folders, shared=''):
    """The ComfyUI LoRA folder to link from: under the shared models folder when set, never an output folder."""
    candidates = [
        Path(f)
        for f in (folders or {}).get('loras', [])
        if 'output' not in (p.lower() for p in Path(f).parts)
    ]
    if shared:
        preferred = [c for c in candidates if str(c).lower().startswith(str(Path(shared)).lower())]
        candidates = preferred + [c for c in candidates if c not in preferred]
    existing = [c for c in candidates if c.is_dir()]
    return (existing or [None])[0]


def _is_link(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _target(path):
    try:
        return Path(os.readlink(path))
    except OSError:
        return None


def _same(a, b):
    def norm(p):
        text = str(p)
        return os.path.normcase(os.path.normpath(text.removeprefix('\\\\?\\')))

    return norm(a) == norm(b)


def _inside(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def status(paths, values, folders, shared=''):
    """``{state, folder, comfy_folder, link}``; state is linked, missing, broken, conflict, inside or no_comfy.

    ``inside``: the LoRA folder already is (or is under) a ComfyUI LoRA folder, as older settings chose; no link needed.
    """
    folder = app_folder(paths, values)
    out = {'folder': str(folder), 'comfy_folder': None, 'link': None}
    for comfy in (folders or {}).get('loras', []):
        if _inside(folder, comfy):
            return {**out, 'state': 'inside', 'comfy_folder': str(comfy)}
    comfy = comfy_folder(folders, shared)
    if comfy is None:
        return {**out, 'state': 'no_comfy'}
    link = comfy / LINK_NAME
    out.update(comfy_folder=str(comfy), link=str(link))
    if _is_link(link):
        target = _target(link)
        if target is not None and _same(target, folder):
            return {**out, 'state': 'linked'}
        return {**out, 'state': 'broken', 'target': str(target) if target else None}
    if link.exists():
        return {**out, 'state': 'conflict'}
    return {**out, 'state': 'missing'}


def connect(paths, values, folders, shared=''):
    """Make (or point again) the ``atelierx`` link in ComfyUI's LoRA folder at the app's LoRA folder."""
    current = status(paths, values, folders, shared)
    state = current['state']
    if state in ('linked', 'inside'):
        return current
    if state == 'no_comfy':
        raise ValueError(
            Msg(
                'server.lora_link.no_comfy',
                'The image server has no LoRA folder to link from. Start ComfyUI and check its model folders.',
            )
        )
    if state == 'conflict':
        raise ValueError(
            Msg(
                'server.lora_link.conflict',
                'ComfyUI already has a folder named {name} at {path}. Rename or move it first; it is not overwritten.',
                name=LINK_NAME,
                path=current['link'],
            )
        )
    link, target = Path(current['link']), Path(current['folder'])
    if state == 'broken':
        # Only the link goes: os.rmdir on a junction and unlink on a symbolic link leave its target alone.
        if link.is_symlink():
            link.unlink()
        else:
            os.rmdir(link)
    try:
        if sys.platform == 'win32':
            import _winapi

            _winapi.CreateJunction(str(target.resolve()), str(link))
        else:
            link.symlink_to(target.resolve(), target_is_directory=True)
    except OSError as error:
        raise ValueError(
            Msg(
                'server.lora_link.failed',
                'Could not link {link} to {folder}: {error}. A junction needs both folders on local drives.',
                link=str(link),
                folder=str(target),
                error=error,
            )
        ) from error
    return status(paths, values, folders, shared)


def move_into_app(paths, values, rename):
    """Move the LoRAs of an older ComfyUI LoRA folder setting into ``output/loras/``.

    ``rename(old_name, new_name)`` updates what refers to a file (characters' LoRA lists). Returns the moved file names.
    """
    source = Path(values.get('lora_dir') or '')
    target = Path(paths.output) / 'loras'
    if not source.is_dir() or _same(source, target):
        return []
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for file in sorted(source.glob('*.safetensors')):
        destination = target / file.name
        if destination.exists():
            raise ValueError(
                Msg(
                    'server.lora_link.exists',
                    '{name} is already in the app LoRA folder; nothing was moved.',
                    name=file.name,
                )
            )
    for file in sorted(source.glob('*.safetensors')):
        shutil.move(str(file), str(target / file.name))
        rename(file.name, f'{LINK_NAME}\\{file.name}')
        moved.append(file.name)
    return moved
