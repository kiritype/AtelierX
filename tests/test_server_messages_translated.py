"""Every message the server raises has its Korean text in the catalog (it fell back to English before)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_server_message_key_is_in_the_korean_catalog():
    source = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'server' / 'atelierx').rglob('*.py'))
    keys = set(re.findall(r"Msg\(\s*'(server\.[A-Za-z0-9_.]+)'", source))
    catalog = json.loads((ROOT / 'web' / 'src' / 'locales' / 'ko.json').read_text(encoding='utf-8'))
    assert keys and sorted(k for k in keys if k not in catalog) == []
