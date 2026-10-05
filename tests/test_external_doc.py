"""The manual's external components page lists what the app actually pins, so a version bump updates it too."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / 'docs' / 'manual' / 'guide' / 'external.md').read_text(encoding='utf-8')


def test_every_pinned_node_and_the_tested_comfyui_are_listed():
    data = json.loads((ROOT / 'comfy_nodes' / 'nodes.json').read_text(encoding='utf-8'))
    assert data['comfyui']['version'] in PAGE
    for node in data['nodes']:
        assert node['repo'] in PAGE, node['id']
        assert f'`{node["commit"][:7]}`' in PAGE, node['id']
        assert node['license'] in PAGE, node['id']


def test_every_model_file_is_listed():
    data = json.loads((ROOT / 'defaults' / 'image' / 'downloads.json').read_text(encoding='utf-8'))
    for group in data['groups']:
        for item in group.get('items', group.get('files', [])):
            assert f'`{item["file"]}`' in PAGE, item['file']


def test_the_trainer_pins_are_listed():
    source = (ROOT / 'tools' / 'install_trainer.py').read_text(encoding='utf-8')
    pins = re.findall(r"\('(\w+)', '(https://github\.com/[^']+?)(?:\.git)?', '([^']+)'\)", source)
    assert pins
    for _name, url, ref in pins:
        assert url in PAGE and f'`{ref}`' in PAGE, (url, ref)
