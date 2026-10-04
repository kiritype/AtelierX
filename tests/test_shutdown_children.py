"""Programs the app starts end with it, so none keeps running with a log file of the app open."""

import subprocess
import sys
import threading
import time

from starlette.testclient import TestClient

from atelierx.api.app import build_app
from atelierx.core.proc import NO_WINDOW, stop_tree

FAST_KDF = {'name': 'scrypt', 'n': 2**10, 'r': 8, 'p': 1}

# Like a venv's python.exe running the real Python: the child that does the work inherits the log.
TREE = (
    'import subprocess, sys, time\n'
    "subprocess.Popen([sys.executable, '-c', 'import time; print(\"child\", flush=True); time.sleep(120)'])\n"
    'time.sleep(120)\n'
)


def start_tree(log_path):
    with log_path.open('ab') as log:
        process = subprocess.Popen(
            [sys.executable, '-c', TREE],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=NO_WINDOW,
        )
    deadline = time.monotonic() + 30
    while b'child' not in log_path.read_bytes():
        assert time.monotonic() < deadline, 'the child process did not start'
        time.sleep(0.1)
    return process


def test_closing_the_app_stops_its_comfyui_and_training_with_their_children(paths):
    app = build_app(paths, kdf=FAST_KDF)
    image = app.state.app.image
    logs = paths.root / 'state' / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    comfy_log, train_log = logs / 'comfy-managed.log', logs / 'train.log'
    comfy = train = None
    try:
        with TestClient(app, base_url='http://127.0.0.1:8765'):
            comfy = start_tree(comfy_log)
            image.control.process = comfy
            train = start_tree(train_log)
            trainer = image.trainer
            trainer.active, trainer.process = ('W001', 'C001', 'R001'), train

            def run():  # what the training thread does when its process ends
                train.wait()
                trainer.active = trainer.process = None

            threading.Thread(target=run, daemon=True).start()
        assert comfy.poll() is not None and train.poll() is not None
        assert trainer.active is None
        # Nothing holds the logs any more (on Windows an open file cannot be deleted).
        comfy_log.unlink()
        train_log.unlink()
    finally:
        stop_tree(comfy)
        stop_tree(train)
