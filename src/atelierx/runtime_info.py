"""Public process-start build identity; never includes configuration or secrets."""
import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _identity():
    try:
        release = version("atelierx")
    except PackageNotFoundError:
        release = "0.0.1"
    digest = hashlib.sha256()
    try:
        for path in sorted(Path(__file__).parent.glob("*.py")):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        build = digest.hexdigest()[:12]
    except OSError:
        build = "unavailable"
    return {"version": release, "build": build}


# Capture once: editing files must not make an old process claim a new build.
RUNTIME_INFO = _identity()
