"""Running other programs from the app.

The packaged app has no console of its own, so on Windows every console program it starts (git, pip, taskkill …)
would open a console window for a moment. Every subprocess call passes ``creationflags=NO_WINDOW``;
tests/test_no_console_windows.py checks that none is missed.
"""

import subprocess
import sys

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def stop_tree(process, timeout=10):
    """Stop a started program together with the programs it started, and wait for it to end.

    A venv's python.exe runs the real Python as its child, and the trainer starts workers; stopping only the first
    process would leave the others running with the app's log files open.
    """
    if process is None or process.poll() is not None:
        return
    if sys.platform == 'win32':
        subprocess.call(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
