"""Build and validate an offline manual from the VitePress Markdown sources."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/manual'


class PageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.references = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.ids.add(values['id'])
        for attr in ('href', 'src'):
            if values.get(attr):
                self.references.append((tag, attr, values[attr]))


def check_built_manual(output: Path) -> list[str]:
    output = output.resolve()
    errors = []
    pages = {}
    for path in output.rglob('*.html'):
        parser = PageReferences()
        parser.feed(path.read_text(encoding='utf-8'))
        pages[path] = parser
    if output / 'index.html' not in pages:
        return ['Manual index is missing']
    for page, parser in pages.items():
        for tag, attr, ref in parser.references:
            parsed = urlsplit(ref)
            if parsed.scheme or parsed.netloc:
                if tag != 'a' or parsed.scheme not in ('https', 'http', 'mailto'):
                    errors.append(f'External resource: {page.name}: {ref}')
                continue
            target = (page.parent / unquote(parsed.path)).resolve() if parsed.path else page
            if not target.is_relative_to(output) or not target.is_file():
                errors.append(f'Broken {attr}: {page.relative_to(output)}: {ref}')
            elif parsed.fragment and target in pages and unquote(parsed.fragment) not in pages[target].ids:
                errors.append(f'Broken anchor: {page.name}: {ref}')
    return errors


def build(output: Path) -> int:
    output = output.resolve()
    # Never overwrite source directories or arbitrary repository files.
    if not output.is_relative_to(ROOT / 'dist') or output == ROOT / 'dist':
        raise ValueError('Manual output must be a subdirectory of dist/')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js and web dependencies are required to render Markdown.')
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([node, str(ROOT / 'tools/render_manual.mjs'), str(output)], cwd=ROOT, check=True)
    for filename in ('manual.css', 'offline.js'):
        shutil.copy2(SOURCE / filename, output / filename)
    shutil.copytree(SOURCE / 'screenshots', output / 'screenshots', dirs_exist_ok=True)
    errors = check_built_manual(output)
    if errors:
        raise RuntimeError('\n'.join(errors))
    print(f'Offline manual links validated: {output.relative_to(ROOT)}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', nargs='?', type=Path, default=ROOT / 'dist/manual')
    args = parser.parse_args()
    return build(args.output)


if __name__ == '__main__':
    raise SystemExit(main())
