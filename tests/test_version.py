"""One version number: the package, the web app and the packaged README follow ``atelierx.__version__``."""

import json
import re
import tomllib
from pathlib import Path

from atelierx import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_the_same_everywhere():
    pyproject = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    package = json.loads((ROOT / 'web' / 'package.json').read_text(encoding='utf-8'))
    assert re.fullmatch(r'\d+\.\d+\.\d+', __version__)
    assert pyproject['project']['version'] == __version__
    assert package['version'] == __version__


def test_packaged_files_take_the_version_from_the_package():
    readme = (ROOT / 'packaging' / 'PORTABLE_README.txt').read_text(encoding='utf-8')
    build = (ROOT / 'tools' / 'build_windows.py').read_text(encoding='utf-8')
    assert '{version}' in readme and __version__ not in readme
    assert __version__ not in build


def test_the_web_app_shows_the_version_from_package_json():
    sources = [p for p in (ROOT / 'web' / 'src').rglob('*') if p.suffix in ('.ts', '.tsx')]
    assert not [p.name for p in sources if __version__ in p.read_text(encoding='utf-8')]
    assert '__APP_VERSION__' in (ROOT / 'web' / 'vite.config.ts').read_text(encoding='utf-8')
