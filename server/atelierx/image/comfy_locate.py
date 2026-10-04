"""Find ComfyUI installs: the running one first, then the usual places on Windows.

Works for git clones with a venv, the portable build (``python_embeded``), Stability
Matrix packages and the ComfyUI desktop app. Nothing here changes settings; callers show
the candidates and let the person confirm. Standard library only, so the node installer
can use it with any Python.
"""

from __future__ import annotations

import ipaddress
import json
import os
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from ..core.i18n import Msg

KINDS = {
    'portable': Msg('server.comfy_locate.comfyui_portable', 'ComfyUI portable'),
    'stability_matrix': 'Stability Matrix',
    'desktop': Msg('server.comfy_locate.comfyui_desktop_app', 'ComfyUI desktop app'),
    'venv': Msg('server.comfy_locate.git_install_venv', 'git install (venv)'),
    'unknown': Msg('server.comfy_locate.unknown', 'Unknown'),
}
_DEFAULT_STABILITY_MATRIX_PACKAGES = Path('C:/StabilityMatrix/Packages')


def is_comfy_dir(path: Path) -> bool:
    return (path / 'main.py').is_file() and (path / 'comfy').is_dir() and (path / 'nodes.py').is_file()


def _is_link_or_junction(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _desktop_layout() -> tuple[Path | None, list[Path]]:
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return None, []
    try:
        base = Path(
            json.loads((Path(appdata) / 'ComfyUI' / 'config.json').read_text(encoding='utf-8'))['basePath']
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None, []
    local = os.environ.get('LOCALAPPDATA', '')
    return base, [
        base / 'ComfyUI',
        Path(local) / 'Programs' / '@comfyorgcomfyui-electron' / 'resources' / 'ComfyUI',
    ]


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve() == second.resolve()
    except OSError:
        return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _is_loopback_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        return bool(
            parsed.scheme in ('http', 'https')
            and host
            and not parsed.username
            and not parsed.password
            and (host.lower() == 'localhost' or ipaddress.ip_address(host).is_loopback)
        )
    except ValueError:
        return False


def python_for(comfy: Path) -> Path | None:
    """The Python that runs this ComfyUI, when it can be told from the folders."""
    for candidate in (
        comfy.parent / 'python_embeded' / 'python.exe',  # portable build
        comfy / 'venv' / 'Scripts' / 'python.exe',
        comfy / '.venv' / 'Scripts' / 'python.exe',
        comfy.parent / '.venv' / 'Scripts' / 'python.exe',  # desktop app base folder
    ):
        if candidate.is_file():
            return candidate
    base, desktop_paths = _desktop_layout()
    if base and any(_same_path(comfy, desktop_path) for desktop_path in desktop_paths):
        candidate = base / '.venv' / 'Scripts' / 'python.exe'
        if candidate.is_file():
            return candidate
    return None


def kind_of(comfy: Path) -> str:
    if (comfy.parent / 'python_embeded').is_dir():
        return 'portable'
    if comfy.parent.name == 'Packages' and (comfy.parent.parent / 'Models').is_dir():
        return 'stability_matrix'
    base, desktop_paths = _desktop_layout()
    if base and any(_same_path(comfy, desktop_path) for desktop_path in desktop_paths):
        return 'desktop'
    if (comfy.parent / '.venv').is_dir() and not (comfy / '.git').exists():
        return 'desktop'
    if (comfy / 'venv').is_dir() or (comfy / '.venv').is_dir():
        return 'venv'
    return 'unknown'


def describe(comfy: Path, source: str) -> dict:
    python = python_for(comfy)
    return {
        'comfy_path': str(comfy),
        'python_path': str(python) if python else '',
        'kind': kind_of(comfy),
        'source': source,
    }


def running(
    url: str = 'http://127.0.0.1:8188', timeout: float = 2.0, _installs: list[Path] | None = None
) -> dict | None:
    """The install behind a running ComfyUI (``/system_stats`` names its ``main.py``)."""
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/system_stats', timeout=timeout) as reply:
            system = json.load(reply).get('system', {})
    except (OSError, ValueError):
        return None
    argv = system.get('argv') or []
    if not argv:
        return None
    main = Path(argv[0])
    if not main.is_absolute():
        # Some launchers expose just ``main.py`` in argv. Resolve it only when a
        # bounded local search identifies a single install; guessing among several
        # copies could label the wrong one as the live server.
        if main.name.lower() != 'main.py' or not _is_loopback_url(url):
            return None
        installs = _discovered_installs() if _installs is None else _installs
        if len(installs) == 1:
            main = installs[0] / 'main.py'
        else:
            return None
    comfy = main.parent if main.name == 'main.py' else None
    if not comfy or not is_comfy_dir(comfy):
        return None
    found = describe(comfy, 'running')
    found['version'] = system.get('comfyui_version', '')
    found['arguments'] = [a for a in argv[1:]]
    return found


def model_folders(url: str = 'http://127.0.0.1:8188', timeout: float = 2.0) -> dict | None:
    """Model folders of the running ComfyUI, including extra_model_paths.yaml entries."""
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/internal/folder_paths', timeout=timeout) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None
    return {key: [str(p) for p in value] for key, value in data.items() if isinstance(value, list)}


def suggest_lora_dir(folders: dict | None) -> str:
    """A LoRA folder to save trained LoRAs in: never ComfyUI's output folder, and one with
    an ``anima`` subfolder (kept for Anima LoRAs) when there is one."""
    usable = []
    for folder in (folders or {}).get('loras', []):
        path = Path(folder)
        if 'output' not in (part.lower() for part in path.parts[-2:]) and path.is_dir():
            usable.append(path)
    for path in usable:
        if (path / 'anima').is_dir():
            return str(path / 'anima')
    return str(usable[0]) if usable else ''


def _stability_matrix() -> list[Path]:
    found = []
    roots = []
    appdata = os.environ.get('APPDATA')
    if appdata:
        library = Path(appdata) / 'StabilityMatrix' / 'library.json'
        try:
            root = Path(json.loads(library.read_text(encoding='utf-8'))['LibraryPath'])
            roots.append(root / 'Packages')
        except (OSError, ValueError, KeyError, TypeError):
            pass
    # Default Windows installs commonly keep packages here and may not have a
    # library.json yet (or may have moved it with the app data).
    roots.extend((_DEFAULT_STABILITY_MATRIX_PACKAGES, Path.home() / 'StabilityMatrix' / 'Packages'))
    for packages in roots:
        try:
            found.extend(
                p
                for p in packages.iterdir()
                if p.is_dir() and not _is_link_or_junction(p) and is_comfy_dir(p)
            )
        except OSError:
            continue
    return found


def _desktop() -> list[Path]:
    _, paths = _desktop_layout()
    return [p for p in paths if is_comfy_dir(p)]


def _common_places() -> list[Path]:
    """Search a fixed set of roots, at most two directory levels below each."""
    home = Path.home()
    roots = [
        home,
        home / 'Desktop',
        home / 'Documents',
        home / 'Downloads',
        Path('C:/StabilityMatrix'),
        Path('C:/AI'),
        Path('C:/ComfyUI'),
        Path(os.environ.get('LOCALAPPDATA', 'C:/Users/Default/AppData/Local')) / 'Programs',
    ]
    found = []
    for root in roots:
        # Stability Matrix packages can be one level deeper than its root.
        if root.name.lower() == 'stabilitymatrix':
            packages = root / 'Packages'
            try:
                found.extend(
                    p
                    for p in packages.iterdir()
                    if p.is_dir() and not _is_link_or_junction(p) and is_comfy_dir(p)
                )
            except OSError:
                pass
        try:
            level1 = [p for p in root.iterdir() if p.is_dir() and not _is_link_or_junction(p)]
        except OSError:
            continue
        for folder in level1:
            name = folder.name.lower()
            if 'comfy' not in name and name not in {'ai', 'models', 'programs', 'stabilitymatrix'}:
                continue
            if is_comfy_dir(folder):
                found.append(folder)
                continue
            try:
                found += [
                    p
                    for p in folder.iterdir()
                    if p.is_dir() and not _is_link_or_junction(p) and is_comfy_dir(p)
                ]
            except OSError:
                pass
    return found


def _discovered_installs() -> list[Path]:
    found = []
    seen = set()
    for finder in (_stability_matrix, _desktop, _common_places):
        for path in finder():
            try:
                key = path.resolve()
            except OSError:
                key = path.absolute()
            if key not in seen:
                seen.add(key)
                found.append(path)
    return found


def candidates(url: str = 'http://127.0.0.1:8188') -> list[dict]:
    """Every install found, the running one first, without duplicates."""
    discovered = []
    for source, finder in (
        ('stability_matrix', _stability_matrix),
        ('desktop', _desktop),
        ('search', _common_places),
    ):
        discovered.extend((source, comfy) for comfy in finder())
    installs = [comfy for _, comfy in discovered]
    result = []
    seen = set()
    live = running(url, _installs=installs)
    if live:
        result.append(live)
        seen.add(Path(live['comfy_path']).resolve())
    for source, comfy in discovered:
        key = comfy.resolve()
        if key not in seen:
            seen.add(key)
            result.append(describe(comfy, source))
    return result
