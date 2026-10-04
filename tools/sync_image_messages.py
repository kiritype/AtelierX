"""Copy translations of server messages used by the image module from the earlier image tool's catalogs.

Development helper (decision 0018). Usage: uv run python tools/sync_image_messages.py <earlier tool's static/i18n folder>
Only keys that the image package uses and that are missing in web/src/locales are added.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"Msg\(\s*'([\w.]+)'")


def main(source):
    used = set()
    for path in (ROOT / 'server' / 'atelierx' / 'image').rglob('*.py'):
        used |= set(KEY.findall(path.read_text(encoding='utf-8')))
    for lang in ('ko', 'en'):
        theirs = json.loads((Path(source) / f'{lang}.json').read_text(encoding='utf-8'))
        target = ROOT / 'web' / 'src' / 'locales' / f'{lang}.json'
        ours = json.loads(target.read_text(encoding='utf-8'))
        added = 0
        for key in sorted(used):
            if key not in ours and key in theirs:
                ours[key] = theirs[key]
                added += 1
        target.write_text(
            json.dumps(ours, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n'
        )
        missing = sorted(k for k in used if k not in ours)
        print(f'{lang}: +{added}, still missing {len(missing)}: {missing[:8]}')


if __name__ == '__main__':
    main(sys.argv[1])
