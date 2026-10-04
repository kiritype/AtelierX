"""Install the image server (ComfyUI) custom nodes the image tools use, at the tested versions.

    uv run python tools/install_comfy_nodes.py                    # show the plan for the found ComfyUI
    uv run python tools/install_comfy_nodes.py --yes              # carry it out
    uv run python tools/install_comfy_nodes.py --only tagger,alpha --yes
    uv run python tools/install_comfy_nodes.py --comfy D:\\ComfyUI --python D:\\python_embeded\\python.exe

The node list and pinned commits are in comfy_nodes/nodes.json. Nothing third-party is shipped with the app:
missing nodes are cloned from their own repositories at the pinned commit and their requirements are installed
with ComfyUI's own Python. Installed nodes are left alone (only their version is reported). The app's own pack
(comfy_nodes/atelierx_nodes) is copied into custom_nodes. Restart ComfyUI afterwards.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

from atelierx.image import comfy_locate, node_install

KINDS = {
    'portable': 'portable build',
    'stability_matrix': 'Stability Matrix',
    'desktop': 'desktop app',
    'venv': 'git install with venv',
    'unknown': 'unknown kind',
}
MARKS = {'install': '+', 'repair': '+', 'ok': '=', 'differs': '~', 'blocked': '!', 'skip': '-'}


def describe(step):
    node, have = step['node'], step['have']
    name = f'{node["folder"]} {node["version"]} ({node["license"]})'
    text = {
        'install': f'install ({node["commit"][:7]})',
        'repair': f'unfinished install; check out {node["commit"][:7]} and install its requirements again',
        'ok': 'installed',
        'differs': f'another version is installed ({(have or {}).get("version") or (have or {}).get("commit", "")[:7] or "?"}); left alone',
        'blocked': 'a folder or link with this name is in the way; skipped',
        'skip': 'not chosen',
    }[step['action']]
    return f'  {MARKS[step["action"]]}  {name}: {text}'


def main(argv=None):
    # Node installers print progress bars and other characters a Korean console code page cannot show.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Install the ComfyUI nodes the image tools use.')
    parser.add_argument('--comfy', help='ComfyUI folder (the one with main.py)')
    parser.add_argument('--python', help="ComfyUI's Python (default: found next to ComfyUI)")
    parser.add_argument('--only', help='Features to install, comma separated')
    parser.add_argument('--yes', action='store_true', help='Carry out the plan')
    args = parser.parse_args(argv)
    data = node_install.manifest(ROOT)
    features = [f.strip() for f in args.only.split(',')] if args.only else None
    if features and (unknown := set(features) - set(data['features'])):
        parser.error(
            f'unknown feature: {", ".join(sorted(unknown))} (choose from: {", ".join(data["features"])})'
        )

    if args.comfy:
        comfy = Path(args.comfy)
        if not comfy_locate.is_comfy_dir(comfy):
            parser.error(f'not a ComfyUI folder (no main.py): {comfy}')
    else:
        found = comfy_locate.candidates()
        if not found:
            parser.error('no ComfyUI found; name its folder with --comfy')
        if len(found) > 1 and found[0]['source'] != 'running':
            print('Several ComfyUI installs were found; choose one with --comfy:')
            for item in found:
                print('  ', item['comfy_path'], f'({KINDS.get(item["kind"], item["kind"])})')
            return 2
        comfy = Path(found[0]['comfy_path'])
    python = Path(args.python) if args.python else comfy_locate.python_for(comfy)
    if not python or not python.is_file():
        parser.error("ComfyUI's Python was not found; name it with --python")

    print(f'ComfyUI: {comfy} ({KINDS.get(comfy_locate.kind_of(comfy), "?")})')
    print(f'Python:  {python}')
    # The app's portable Git (Settings → Install) counts too.
    git = shutil.which('git') or str(ROOT / 'bin' / 'git' / 'cmd' / 'git.exe')
    result = node_install.plan(ROOT, comfy, features, git=git)
    print(f'Tested with ComfyUI {result["comfyui_version"]}')
    for step in result['steps']:
        print(describe(step))
    pack = result['pack']
    print(
        {
            'install': f'  +  {pack["folder"]} ({pack["license"]}): copy',
            'update': f'  +  {pack["folder"]} ({pack["license"]}): update the copy',
            'ok': f'  =  {pack["folder"]} ({pack["license"]}): up to date',
            'blocked': f'  !  {pack["folder"]}: a folder or link not made by this app is in the way; skipped',
            'missing_source': f'  !  {pack["folder"]}: not found in comfy_nodes/ of this app',
            'skip': f'  -  {pack["folder"]}: not chosen',
        }[pack['action']]
    )
    if result['broken_links']:
        print('\nBroken links in custom_nodes (their targets are gone; ComfyUI cannot load them):')
        for name in result['broken_links']:
            print('   ', name)
    if result['legacy_packs']:
        print(
            '\nOther atelierx_* node folders may register the same node names:',
            ', '.join(result['legacy_packs']),
        )

    todo = any(s['action'] in ('install', 'repair') for s in result['steps']) or pack['action'] in (
        'install',
        'update',
    )
    if not todo:
        print('\nNothing to do.')
        return 0
    if not args.yes:
        print(
            '\nRun again with --yes to carry this out. Third-party nodes keep their own licenses (see above).'
        )
        return 0
    node_install.carry_out(ROOT, comfy, python, features, git=git)
    print('\nDone. Restart ComfyUI.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
