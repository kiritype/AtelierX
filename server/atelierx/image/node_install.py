"""Image server custom nodes the image tools need (22-image-tools: 노드 설치).

Third-party nodes are never shipped with the app. They are cloned from their own repositories at the
tested commit, into the user's ComfyUI, and their requirements are installed with ComfyUI's own Python.
The app's own node pack (``comfy_nodes/atelierx_nodes``, MIT) is copied, not linked, so moving the app
folder does not leave a broken link in ComfyUI.

``plan`` only looks; ``carry_out`` changes the ComfyUI folder and is run only on the user's request.

A node this app installs carries ``.atelierx-install.json``: written right after the clone, it says ``complete`` only
once the checkout and the requirements (pip, install.py) succeeded. An unfinished record is ``repair``: the next run
checks the commit out again and installs the requirements again. Nodes installed some other way are only looked at.
The repository and commit are read from the ``.git`` files, so looking needs no git program.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..core.proc import NO_WINDOW

ACTIONS = ('install', 'repair', 'ok', 'differs', 'blocked', 'skip')
STAMP = '.atelierx-pack'
RECORD = '.atelierx-install.json'


def manifest(app_dir):
    return json.loads((Path(app_dir) / 'comfy_nodes' / 'nodes.json').read_text(encoding='utf-8'))


def norm_repo(url):
    url = (url or '').strip().lower().removesuffix('/').removesuffix('.git')
    return re.sub(r'^git@github\.com:', 'https://github.com/', url)


def _git(folder, *args, git='git'):
    try:
        done = subprocess.run(
            [git, '-C', str(folder), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return done.stdout.strip() if done.returncode == 0 else ''


def _git_dir(folder):
    """The repository folder of a checkout: ``.git`` itself, or where a ``.git`` file points (worktrees, submodules)."""
    dot = folder / '.git'
    if dot.is_dir():
        return dot
    if dot.is_file():
        text = dot.read_text(encoding='utf-8', errors='replace').strip()
        if text.startswith('gitdir:'):
            target = Path(text.split(':', 1)[1].strip())
            return target if target.is_absolute() else (folder / target).resolve()
    return None


def _read_ref(base, ref):
    if (base / ref).is_file():
        return (base / ref).read_text(encoding='utf-8').strip()
    packed = base / 'packed-refs'
    if packed.is_file():
        found = re.search(
            rf'^([0-9a-f]{{40}}) {re.escape(ref)}$', packed.read_text(encoding='utf-8'), re.MULTILINE
        )
        if found:
            return found.group(1)
    return ''


def _read_git(folder):
    """(origin URL, HEAD commit) read from the repository files; empty strings where they cannot be read."""
    root = _git_dir(folder)
    if root is None:
        return '', ''
    remote = commit = ''
    try:
        common = root
        # A worktree keeps its config and refs in the common folder named by ``commondir``.
        if (root / 'commondir').is_file():
            common = (root / (root / 'commondir').read_text(encoding='utf-8').strip()).resolve()
        config = (common / 'config').read_text(encoding='utf-8', errors='replace')
        section = re.search(r'\[remote "origin"\]([^\[]*)', config)
        if section and (url := re.search(r'^\s*url\s*=\s*(\S+)', section.group(1), re.MULTILINE)):
            remote = url.group(1)
        head = (root / 'HEAD').read_text(encoding='utf-8', errors='replace').strip()
        if head.startswith('ref:'):
            ref = head[4:].strip()
            commit = _read_ref(root, ref) or _read_ref(common, ref)
        else:
            commit = head
    except OSError:
        return remote, ''
    return remote, commit if re.fullmatch(r'[0-9a-f]{40}', commit or '') else ''


def read_record(folder):
    try:
        data = json.loads((folder / RECORD).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_record(folder, node, complete):
    record = {'id': node['id'], 'repo': node['repo'], 'commit': node['commit'], 'complete': complete}
    (folder / RECORD).write_text(json.dumps(record) + '\n', encoding='utf-8')


def inspect(folder, git='git'):
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
        remote, commit = _read_git(folder)
        # Layouts the files do not explain are asked of git (the app's own copy when it has one).
        if not remote:
            remote = _git(folder, 'config', '--get', 'remote.origin.url', git=git)
        if remote and not commit:
            commit = _git(folder, 'rev-parse', 'HEAD', git=git)
        # A registry install inside a git checkout reports the outer repository; ignore it.
        if remote and 'comfyanonymous/comfyui' not in remote.lower():
            info['repo'] = remote
            info['commit'] = commit
    return info


def _broken_link(path):
    return path.is_symlink() and not path.exists() or (path.is_junction() and not path.exists())


def pack_hash(pack):
    digest = hashlib.sha256()
    for file in sorted(p for p in pack.rglob('*.py') if '__pycache__' not in p.parts):
        digest.update(file.relative_to(pack).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()[:16]


def plan(app_dir, comfy, features=None, git='git'):
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
                info = inspect(folder, git)
                if info['repo']:
                    installed[norm_repo(info['repo'])] = info
    steps = []
    for node in data['nodes']:
        wanted = not features or set(node['features']) & set(features)
        have = installed.get(norm_repo(node['repo']))
        target = custom / node['folder']
        record = read_record(target) if target.is_dir() else None
        # Complete only for the commit this app version asks for, and only when that commit is checked out.
        finished = (
            record
            and record.get('complete')
            and record.get('commit') == node['commit']
            and have
            and have['commit'] == node['commit']
        )
        if not wanted:
            action = 'skip'
        elif record and norm_repo(record.get('repo')) == norm_repo(node['repo']) and not finished:
            # Installed by this app but not finished (requirements failed, or the checkout did not happen).
            action = 'repair'
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
    """Install what ``plan`` marks install/repair/update. Returns the plan after the work."""
    result = plan(app_dir, comfy, features, git=git)
    custom = Path(comfy) / 'custom_nodes'
    custom.mkdir(exist_ok=True)
    for step in result['steps']:
        if step['action'] not in ('install', 'repair'):
            continue
        node = step['node']
        target = custom / node['folder']
        log(f'[{node["folder"]}] {node["license"]}' + (' (repair)' if step['action'] == 'repair' else ''))
        if step['action'] == 'install':
            try:
                _run([git, 'clone', '--quiet', node['repo'], target], log, env=env)
            except Exception:
                # A half-made clone would block every retry; this folder did not exist before.
                shutil.rmtree(target, ignore_errors=True)
                raise
        # Unfinished until every step below succeeds, also when an earlier install of another commit was complete.
        _write_record(target, node, complete=False)
        if step['action'] == 'repair':
            _run([git, '-C', target, 'fetch', '--quiet', 'origin'], log, env=env)
        _run([git, '-C', target, 'checkout', '--quiet', node['commit']], log, env=env)
        if (target / 'requirements.txt').is_file():
            _run([python, '-m', 'pip', 'install', '-r', target / 'requirements.txt'], log, env=env)
        if (target / 'install.py').is_file():
            # Some packs (Impact) fetch extra parts here, as ComfyUI-Manager does.
            _run([python, 'install.py'], log, cwd=target, env=env)
        _write_record(target, node, complete=True)
    if result['pack']['action'] in ('install', 'update'):
        data = manifest(app_dir)
        source = Path(app_dir) / 'comfy_nodes' / data['pack']['folder']
        target = custom / data['pack']['folder']
        log(f'[{target.name}] copy')
        if target.exists():
            shutil.rmtree(target)  # only a copy this app made (it has the stamp file)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__'))
        (target / STAMP).write_text(pack_hash(source) + '\n', encoding='utf-8')
    return plan(app_dir, comfy, features, git=git)
