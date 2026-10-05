"""Cancelling an install (also when the app closes) stops node installs too: the running command and every later step."""

import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from atelierx.image import installs as installs_module
from atelierx.image import node_install
from atelierx.image.installs import Cancelled, Installs

ROOT = Path(__file__).resolve().parents[1]

# A command whose real work runs in a child that inherits the output, like git or pip under a launcher.
TREE = (
    'import subprocess, sys, time\n'
    "subprocess.Popen([sys.executable, '-c', 'import time; print(\"child\", flush=True); time.sleep(120)'])\n"
    'time.sleep(120)\n'
)


def make(tmp_path):
    app = tmp_path / 'app'
    (app / 'comfy_nodes').mkdir(parents=True)
    shutil.copy(ROOT / 'comfy_nodes' / 'nodes.json', app / 'comfy_nodes' / 'nodes.json')
    shutil.copytree(ROOT / 'comfy_nodes' / 'atelierx_nodes', app / 'comfy_nodes' / 'atelierx_nodes')
    comfy = tmp_path / 'comfy'
    (comfy / 'custom_nodes').mkdir(parents=True)
    (comfy / 'main.py').write_text('', encoding='utf-8')
    runtime = SimpleNamespace(
        paths=SimpleNamespace(root=tmp_path, defaults=app / 'defaults', config=tmp_path / 'config')
    )
    installs = Installs(runtime)
    installs.run = {'log': [], 'status': 'running'}
    installs.cancel_requested = False
    return installs, app, comfy


def test_cancel_during_a_node_clone_stops_before_the_next_step(tmp_path, monkeypatch):
    installs, app, comfy = make(tmp_path)
    node = next(n for n in node_install.manifest(app)['nodes'] if n['id'] == 'wd14-tagger')
    monkeypatch.setattr(installs, 'comfy_dirs', lambda: (comfy, Path(sys.executable)))
    monkeypatch.setattr(installs, 'git', lambda: 'git')
    calls = []

    # No real program may run here: the node installer's own runner records too, in case it is still used.
    def direct_run(cmd, *_args, **_kwargs):
        calls.append([str(c) for c in cmd])
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(node_install.subprocess, 'run', direct_run)

    class Process:
        pid, stdout = 0, iter(())

        def __init__(self, cmd, **_kwargs):
            calls.append(cmd)
            if cmd[1] == 'clone':
                (Path(cmd[-1]) / '.git').mkdir(parents=True)
                # The user presses cancel (from another request thread) while git is cloning.
                installs.cancel_requested = True

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(installs_module.subprocess, 'Popen', Process)
    with pytest.raises(Cancelled):
        installs._install_nodes({'features': ['tagger']})
    assert [c[1] for c in calls] == ['clone']  # no checkout, pip or install.py after the cancel
    assert not (comfy / 'custom_nodes' / node['folder']).exists()


def test_cancel_stops_the_running_command_with_its_children(tmp_path):
    installs, _, _ = make(tmp_path)
    outcome = {}

    def install():
        try:
            installs._call([sys.executable, '-c', TREE])
        except Cancelled:
            outcome['cancelled'] = True

    worker = threading.Thread(target=install, daemon=True)
    worker.start()
    deadline = time.monotonic() + 30
    # The command line itself is logged too and contains the word; wait for the child's own output line.
    while not any(line.strip() == 'child' for line in installs.run['log']):
        assert time.monotonic() < deadline, 'the child process did not start'
        time.sleep(0.1)
    installs.shutdown()
    # The output pipe closes only when the command and its child have both ended.
    worker.join(20)
    assert not worker.is_alive() and outcome == {'cancelled': True}
