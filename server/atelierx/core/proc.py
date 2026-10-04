"""Running other programs from the app.

The packaged app has no console of its own, so on Windows every console program it starts (git, pip, taskkill …)
would open a console window for a moment. Every subprocess call passes ``creationflags=NO_WINDOW``;
tests/test_no_console_windows.py checks that none is missed.
"""

import subprocess

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
