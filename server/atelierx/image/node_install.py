"""Image server custom nodes the image tools need (22-image-tools: 노드 설치).

Third-party nodes are never shipped with the app. They are cloned from their own repositories at the
tested commit, into the user's ComfyUI, and their requirements are installed with ComfyUI's own Python.
The app's own node pack (``comfy_nodes/atelierx_nodes``, MIT) is copied, not linked, so moving the app
folder does not leave a broken link in ComfyUI.

``plan`` only looks; ``carry_out`` changes the ComfyUI folder and is run only on the user's request.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..core.proc import NO_WINDOW

ACTIONS = ('install', 'ok', 'differs', 'blocked', 'skip')
STAMP = '.atelierx-pack'


def manifest(app_dir):
    return json.loads((Path(app_dir) / 'comfy_nodes' / 'nodes.json').read_text(encoding='utf-8'))


def norm_repo(url):
    url = (url or '').strip().lower().removesuffix('/').removesuffix('.git')
    return re.sub(r'^git@github\.com:', 'https://github.com/', url)


def _git(folder, *args):
    try:
        done = subprocess.run(
            ['git', '-C', str(folder), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return done.stdout.strip() if done.returncode == 0 else ''


def inspect(folder):
    """Repository, commit and version of an installed node folder."""
    info = {'folder': folder.name, 'repo': '', 'commit': '', 'version': ''}
    toml = folder / 'pyproject.toml'
    if toml.is_file():
        text = toml.read_text(encoding='utf-8', errors='replace')
        if found := re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE):
            info['version'] = found.group(1)
        if found := re.search(r'^Repository\s*=\s*"([^"]+)"', text, re.MULTILINE):
            info['repo'] = found.group(1)
    if (folder / '.git').exists():
        remote = _git(folder, 'config', '--get', 'remote.origin.url')
        # A registry install inside a git checkout reports the outer repository; ignore it.
        if remote and 'comfyanonymous/comfyui' not in remote.lower():
            info['repo'] = remote
            info['commit'] = _git(folder, 'rev-parse', 'HEAD')
    return info


def _broken_link(path):
    return path.is_symlink() and not path.exists() or (path.is_junction() and not path.exists())


def pack_hash(pack):
    digest = hashlib.sha256()
    for file in sorted(p for p in pack.rglob('*.py') if '__pycache__' not in p.parts):
        digest.update(file.relative_to(pack).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()[:16]


def plan(app_dir, comfy, features=None):
    """What would happen for each node: install, ok, differs (another version, left alone), blocked, skip."""
    data = manifest(app_dir)
    custom = Path(comfy) / 'custom_nodes'
    installed, broken, legacy = {}, [], []
    if custom.is_dir():
        for folder in custom.iterdir():
            if folder.name.startswith(('.', '__')):
                continue
            if _broken_link(folder):
                broken.append(folder.name)
                continue
            if folder.name.startswith('atelierx_') and folder.name != data['pack']['folder']:
                legacy.append(folder.name)
            if folder.is_dir():
                info = inspect(folder)
                if info['repo']:
                    installed[norm_repo(info['repo'])] = info
    steps = []
    for node in data['nodes']:
        wanted = not features or set(node['features']) & set(features)
        have = installed.get(norm_repo(node['repo']))
        target = custom / node['folder']
        if not wanted:
            action = 'skip'
        elif have is None:
            action = (
                'blocked' if target.exists() or target.is_symlink() or target.is_junction() else 'install'
            )
        elif have['commit'] == node['commit'] or (not have['commit'] and have['version'] == node['version']):
            action = 'ok'
        else:
            action = 'differs'
        steps.append({'id': node['id'], 'node': node, 'have': have, 'action': action})

    pack = Path(app_dir) / 'comfy_nodes' / data['pack']['folder']
    target = custom / data['pack']['folder']
    wanted = not features or set(data['pack']['features']) & set(features)
    if not wanted:
        pack_action = 'skip'
    elif not pack.is_dir():
        pack_action = 'missing_source'
    elif target.is_symlink() or target.is_junction() or (target.exists() and not (target / STAMP).is_file()):
        pack_action = 'blocked'  # not a copy this app made; never overwritten
    elif not target.exists():
        pack_action = 'install'
    else:
        pack_action = (
            'ok' if (target / STAMP).read_text(encoding='utf-8').strip() == pack_hash(pack) else 'update'
        )
    return {
        'comfy': str(comfy),
        'comfyui_version': data['comfyui']['version'],
        'steps': steps,
        'pack': {'folder': data['pack']['folder'], 'action': pack_action, 'license': data['pack']['license']},
        'broken_links': broken,
        'legacy_packs': legacy,
    }


def _run(cmd, log, cwd=None, env=None):
    log('$ ' + ' '.join(str(c) for c in cmd))
    done = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        creationflags=NO_WINDOW,
        # Child Pythons print in UTF-8 so their output can be read back on any console code page.
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8', **(env or {})},
    )
    for line in (done.stdout + done.stderr).splitlines()[-40:]:
        log('  ' + line)
    if done.returncode:
        raise RuntimeError(f'{cmd[0]} failed (exit {done.returncode})')


def carry_out(app_dir, comfy, python, features=None, log=print, git='git', env=None):
    """Install what ``plan`` marks install/update. Returns the plan after the work."""
    result = plan(app_dir, comfy, features)
    custom = Path(comfy) / 'custom_nodes'
    custom.mkdir(exist_ok=True)
    for step in result['steps']:
        if step['action'] != 'install':
            continue
        node = step['node']
        target = custom / node['folder']
        log(f'[{node["folder"]}] {node["license"]}')
        _run([git, 'clone', '--quiet', node['repo'], target], log, env=env)
        _run([git, '-C', target, 'checkout', '--quiet', node['commit']], log, env=env)
        if (target / 'requirements.txt').is_file():
            _run([python, '-m', 'pip', 'install', '-r', target / 'requirements.txt'], log, env=env)
        if (target / 'install.py').is_file():
            # Some packs (Impact) fetch extra parts here, as ComfyUI-Manager does.
            _run([python, 'install.py'], log, cwd=target, env=env)
    if result['pack']['action'] in ('install', 'update'):
        data = manifest(app_dir)
        source = Path(app_dir) / 'comfy_nodes' / data['pack']['folder']
        target = custom / data['pack']['folder']
        log(f'[{target.name}] copy')
        if target.exists():
            shutil.rmtree(target)  # only a copy this app made (it has the stamp file)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__'))
        (target / STAMP).write_text(pack_hash(source) + '\n', encoding='utf-8')
    return plan(app_dir, comfy, features)
