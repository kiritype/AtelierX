import json
import shutil
from pathlib import Path

import pytest

from atelierx.image import node_install

ROOT = Path(__file__).resolve().parents[1]


def make_app(tmp_path):
    app = tmp_path / 'app'
    (app / 'comfy_nodes' / 'atelierx_nodes').mkdir(parents=True)
    shutil.copy(ROOT / 'comfy_nodes' / 'nodes.json', app / 'comfy_nodes' / 'nodes.json')
    (app / 'comfy_nodes' / 'atelierx_nodes' / '__init__.py').write_text('NODES = 1\n', encoding='utf-8')
    comfy = tmp_path / 'comfy'
    (comfy / 'custom_nodes').mkdir(parents=True)
    (comfy / 'main.py').write_text('', encoding='utf-8')
    return app, comfy


def test_plan_and_pack_copy(tmp_path):
    app, comfy = make_app(tmp_path)
    plan = node_install.plan(app, comfy)
    assert {s['action'] for s in plan['steps']} == {'install'} and plan['pack']['action'] == 'install'
    assert node_install.plan(app, comfy, ['tagger'])['pack']['action'] == 'skip'

    # Someone else's folder with the pack's name is never overwritten.
    (comfy / 'custom_nodes' / 'atelierx_nodes').mkdir()
    assert node_install.plan(app, comfy)['pack']['action'] == 'blocked'
    (comfy / 'custom_nodes' / 'atelierx_nodes').rmdir()

    # Only the pack is wanted here, so nothing is cloned.
    done = node_install.carry_out(app, comfy, 'python', ['upscale'], log=lambda _: None)
    copied = comfy / 'custom_nodes' / 'atelierx_nodes'
    assert (copied / '__init__.py').is_file() and done['pack']['action'] == 'ok'
    (app / 'comfy_nodes' / 'atelierx_nodes' / '__init__.py').write_text('NODES = 2\n', encoding='utf-8')
    assert node_install.plan(app, comfy)['pack']['action'] == 'update'


def test_manifest_lists_licenses():
    data = json.loads((ROOT / 'comfy_nodes' / 'nodes.json').read_text(encoding='utf-8'))
    assert all(node['license'] and len(node['commit']) == 40 for node in data['nodes'])


def fake_checkout(folder, repo, commit, packed=False):
    """A checkout as git leaves it on disk: origin URL in config, HEAD on a branch, the branch's commit."""
    git = folder / '.git'
    (git / 'refs' / 'heads').mkdir(parents=True, exist_ok=True)
    (git / 'config').write_text(
        f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {repo}\n', encoding='utf-8'
    )
    (git / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
    if packed:
        (git / 'packed-refs').write_text(f'# pack-refs\n{commit} refs/heads/main\n', encoding='utf-8')
    else:
        (git / 'refs' / 'heads' / 'main').write_text(commit + '\n', encoding='utf-8')


def test_status_reads_checkouts_without_a_git_program(tmp_path, monkeypatch):
    app, comfy = make_app(tmp_path)
    nodes = node_install.manifest(app)['nodes']
    for index, node in enumerate(nodes):
        fake_checkout(
            comfy / 'custom_nodes' / node['folder'],
            node['repo'] + '.git',
            node['commit'],
            packed=index % 2 == 1,
        )

    def no_git(*args, **kwargs):
        raise AssertionError('git must not be needed to look at checkouts')

    monkeypatch.setattr(node_install.subprocess, 'run', no_git)
    plan = node_install.plan(app, comfy)
    assert {s['action'] for s in plan['steps']} == {'ok'}


def test_failed_requirements_are_repaired_on_the_next_run(tmp_path, monkeypatch):
    app, comfy = make_app(tmp_path)
    node = next(n for n in node_install.manifest(app)['nodes'] if n['id'] == 'wd14-tagger')
    calls, fail = [], {'pip': True}

    def fake_run(cmd, log, cwd=None, env=None):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        if cmd[1] == 'clone':
            target = Path(cmd[-1])
            fake_checkout(target, cmd[-2], '0' * 40)
            (target / 'requirements.txt').write_text('onnxruntime\n', encoding='utf-8')
        elif 'checkout' in cmd:
            folder = Path(cmd[cmd.index('-C') + 1])
            (folder / '.git' / 'refs' / 'heads' / 'main').write_text(cmd[-1] + '\n', encoding='utf-8')
        elif 'pip' in cmd and fail['pip']:
            raise RuntimeError('pip failed')

    monkeypatch.setattr(node_install, '_run', fake_run)
    with pytest.raises(RuntimeError):
        node_install.carry_out(app, comfy, 'python', ['tagger'], log=lambda _: None)
    # The commit matches already, but the requirements never finished: not "installed".
    step = next(s for s in node_install.plan(app, comfy, ['tagger'])['steps'] if s['id'] == 'wd14-tagger')
    assert step['action'] == 'repair'

    fail['pip'] = False
    calls.clear()
    done = node_install.carry_out(app, comfy, 'python', ['tagger'], log=lambda _: None)
    assert any('checkout' in c for c in calls) and any('pip' in c for c in calls)
    assert not any(c[1] == 'clone' for c in calls)
    step = next(s for s in done['steps'] if s['id'] == 'wd14-tagger')
    assert step['action'] == 'ok'
    assert node_install.read_record(comfy / 'custom_nodes' / node['folder'])['complete'] is True


def test_failed_clone_leaves_no_folder_in_the_way(tmp_path, monkeypatch):
    app, comfy = make_app(tmp_path)

    def broken_clone(cmd, log, cwd=None, env=None):
        target = Path(str(cmd[-1]))
        (target / '.git').mkdir(parents=True)
        raise RuntimeError('network gone')

    monkeypatch.setattr(node_install, '_run', broken_clone)
    with pytest.raises(RuntimeError):
        node_install.carry_out(app, comfy, 'python', ['tagger'], log=lambda _: None)
    step = next(s for s in node_install.plan(app, comfy, ['tagger'])['steps'] if s['id'] == 'wd14-tagger')
    assert step['action'] == 'install'
