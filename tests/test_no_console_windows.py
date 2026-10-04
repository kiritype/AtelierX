"""Every program the server starts must hide its console window (core/proc.NO_WINDOW).

The packaged app has no console, so a console program started without CREATE_NO_WINDOW flashes a window. The
settings → install page polls, which turned a missing flag into windows popping up every few seconds.
"""

import ast
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'server'
STARTERS = {'run', 'Popen', 'call', 'check_call', 'check_output'}


def test_every_subprocess_call_hides_its_window():
    missing = []
    for path in sorted(SERVER.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in STARTERS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'subprocess'
                and not any(k.arg == 'creationflags' for k in node.keywords)
            ):
                missing.append(f'{path.relative_to(SERVER)}:{node.lineno}')
    assert missing == []


def test_install_status_reuses_the_node_check(unlocked, monkeypatch, tmp_path):
    installs = unlocked.app.state.app.image.installs
    comfy = tmp_path / 'comfy'
    (comfy / 'custom_nodes').mkdir(parents=True)
    calls = []
    monkeypatch.setattr(installs, 'comfy_dirs', lambda: (comfy, None))
    monkeypatch.setattr(installs, 'model_folders', lambda: None)
    real = __import__('atelierx.image.node_install', fromlist=['plan']).plan
    monkeypatch.setattr('atelierx.image.node_install.plan', lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(3):
        assert unlocked.get('/api/image/installs').status_code == 200
    assert len(calls) == 1
    installs._nodes_cache = None
    unlocked.get('/api/image/installs')
    assert len(calls) == 2
