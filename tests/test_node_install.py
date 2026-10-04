import json
import shutil
from pathlib import Path

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
