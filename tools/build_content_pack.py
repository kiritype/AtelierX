"""Prepare reviewable public content artifacts from an app folder. Never changes the source or uploads files."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from atelierx.core.paths import AppPaths
from atelierx.image import library_share, preset_share
from atelierx.image.default_content import DefaultContent, https_url
from atelierx.image.model_info import KINDS, ModelLibrary
from atelierx.image.models import ModelProfiles
from atelierx.image.tools.gen_info import file_index


def build(
    source,
    output,
    base_url,
    content_version,
    author='',
    license_text='',
    preset_ids=None,
    expression_ids=None,
):
    """Existing sharing formats plus a small HTTPS catalog. Only selected content and its dependencies are packed."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', content_version) or content_version in ('.', '..'):
        raise ValueError('Use a content version containing letters, digits, dots, hyphens or underscores.')
    paths = AppPaths.for_dev(source)
    output = Path(output).resolve()
    if output.is_relative_to(paths.root.resolve()):
        raise ValueError('Keep the output directory outside the source app folder.')
    https_url(base_url)
    output.mkdir(parents=True, exist_ok=True)
    profiles = ModelProfiles(paths)
    root = profiles.models_dir()
    folders = (
        {spec[0]: [str(root / name) for name in spec[1] if (root / name).is_dir()] for spec in KINDS.values()}
        if root
        else {}
    )
    index = file_index(folders)
    for kind, entries in ModelLibrary(paths, profiles, lambda: folders).portable_index(folders).items():
        own = {entry['name']: entry for entry in entries}
        index[kind] = [entry for entry in index.get(kind, []) if entry['name'] not in own] + list(
            own.values()
        )
    artifacts = []
    for kind, title, description in (
        ('presets', '기본 그림체 프리셋', '그림체 프리셋·미리보기·공통 프롬프트'),
        ('expressions', '기본 감정 프롬프트', '감정별 표정 프롬프트와 연결된 구도'),
    ):
        if kind == 'presets':
            raw, _ = preset_share.export(paths, preset_ids or [], index)
            filename = f'presets-{content_version}.zip'
        else:
            doc, _ = library_share.export(paths, None, kind, expression_ids or [])
            raw = (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            filename = f'expressions-{content_version}.json'
        pack = {
            'id': 'atelierx-default-' + kind,
            'kind': kind,
            'version': content_version,
            'min_app_version': '0.8.1',
            'title': title,
            'description': description,
            'author': author,
            'license': license_text,
            'url': base_url.rstrip('/') + '/' + filename,
            'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }
        # Validate the same format the receiver will read, before writing any artifact.
        reader = DefaultContent(type('Source', (), {'paths': paths})())
        reader._read_pack(pack, raw)
        artifacts.append((filename, raw, pack))
    catalog = {'kind': 'atelierx-default-content', 'schema_version': 1, 'packs': [p for _, _, p in artifacts]}
    files = [(name, raw) for name, raw, _ in artifacts]
    files.append(('catalog.json', (json.dumps(catalog, ensure_ascii=False, indent=2) + '\n').encode('utf-8')))
    if any((output / name).exists() for name, _ in files):
        raise ValueError('Output files already exist. Use a new output directory or a new content version.')
    for name, raw in files:
        (output / name).write_bytes(raw)
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default='https://content.example.invalid')
    parser.add_argument('--version', required=True)
    parser.add_argument('--author', default='')
    parser.add_argument('--license', default='')
    parser.add_argument('--presets', nargs='*')
    parser.add_argument('--expressions', nargs='*')
    args = parser.parse_args()
    # Version is also a file-name segment.
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', args.version) or args.version in ('.', '..'):
        parser.error('Use a content version containing letters, digits, dots, hyphens or underscores.')
    catalog = build(
        args.source_root,
        args.output,
        args.base_url,
        args.version,
        args.author,
        args.license,
        args.presets,
        args.expressions,
    )
    for pack in catalog['packs']:
        print(f'{pack["id"]}: {pack["size"]:,} bytes, SHA256 {pack["sha256"]}')
    print(f'Prepared {args.output.resolve() / "catalog.json"}. No files were uploaded.')


if __name__ == '__main__':
    main()
