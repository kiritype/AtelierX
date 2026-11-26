"""Build the optional reference adapter ZIP and verify the candidate assets before publication."""

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ID = 'anima-ref-adapter'
UPSTREAM = {
    'LICENSE': 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30',
    '__init__.py': '6d8a7b0ebf7b7ef53352aa9d753ab6c68a6259a6edac7dd301eb5a51f9555c33',
    'js/anima_ref_adapter.js': '3d7145cb55e291c745b34dc74068325d64998c0493b598e3362362cc6cbdec21',
    'pyproject.toml': '4e24c90202cec62ae91a67e725593c42a3f65c599f346e4fffcf84b7537d5d6d',
    'snapref.py': 'e4c7d86adc846dc12c784579574d09a96dc5093326c719471b545a7bb6403c08',
    'workflows/anima_ref_adapter.json': '5c6543a7e91a2d6b2c1ece5d28e9c7e6c2c6781bd112acee7be4c6bf3b048d8d',
}


def _node():
    manifest = json.loads((ROOT / 'comfy_nodes' / 'nodes.json').read_text(encoding='utf-8'))
    return next(node for node in manifest['nodes'] if node['id'] == ADAPTER_ID)


def archive_names(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError(f'Invalid application version: {version}')
    return f'AtelierX-{version}-windows-x64.zip', f'AtelierX-{version}-{ADAPTER_ID}.zip'


def _expected_members(node):
    prefix = node['folder']
    credits = f"""# Anima Reference Adapter for ComfyUI

Anima Reference Adapter by ElectronGirl and the ArcAnima project contributors.
Source: {node['repo']}
Revision: {node['commit']}
The upstream files in this archive are unmodified and distributed under Apache-2.0.
The full license is in LICENSE.

Unpack the node folder into ComfyUI/custom_nodes and restart ComfyUI.
Put the weights for the selected adapter in ComfyUI/models/loras.
Anima Ref Adapter v2 is available at https://huggingface.co/ElectronGirl/anima-ref-adapter
and SnapRef v2a at https://huggingface.co/0ppxnhximxr/snapref-v2a.
Both weight downloads use the CircleStone Labs Non-Commercial License v1.2.
For the bundled Anima v2 example, open workflows/anima_ref_adapter.json in ComfyUI
and select your own reference image in Load Image.
"""
    credits_bytes = credits.encode('utf-8')
    members = {f'{prefix}/{path}': digest for path, digest in UPSTREAM.items()}
    members[f'{prefix}/CREDITS.md'] = hashlib.sha256(credits_bytes).hexdigest()
    return members, credits_bytes


def _file_sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _verify_adapter(path, node):
    expected, _ = _expected_members(node)
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(expected) or set(names) != expected.keys():
            raise ValueError(f'{path.name} has missing, unexpected or duplicate ZIP members')
        for name, digest in expected.items():
            with archive.open(name) as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                    raise ValueError(f'{path.name} has incorrect contents for {name}')


def build_adapter(source, output, version):
    """Archive exact Git blobs from the pinned upstream checkout."""
    node = _node()
    revision = node['commit']
    prefix = node['folder']
    _, filename = archive_names(version)
    files = {}
    for name, digest in UPSTREAM.items():
        data = subprocess.check_output(['git', '-C', str(source), 'show', f'{revision}:{name}'])
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Incorrect upstream contents: {name}')
        files[f'{prefix}/{name}'] = data
    _, files[f'{prefix}/CREDITS.md'] = _expected_members(node)

    output.mkdir(parents=True, exist_ok=True)
    archive = output / filename
    with ZipFile(archive, 'x') as target:
        for name, data in sorted(files.items()):
            target.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)
    _verify_adapter(archive, node)
    checksum = _file_sha256(archive)
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {filename}\n', encoding='ascii', newline='\n')
    return archive


def verify_candidate(folder, version, commit):
    """Verify both asset pairs, the app build identity, and every adapter archive member."""
    app_name, adapter_name = archive_names(version)
    archives = (app_name, adapter_name)
    expected = {name for filename in archives for name in (filename, f'{filename}.sha256')}
    actual = {path.name for path in folder.iterdir() if path.is_file()}
    if actual != expected:
        raise ValueError(
            f'Release assets differ from the expected set. Missing: {sorted(expected - actual)}. '
            f'Unexpected: {sorted(actual - expected)}.'
        )

    checksums = {}
    for filename in archives:
        checksum = (folder / f'{filename}.sha256').read_text(encoding='ascii')
        fields = checksum.splitlines()
        match = (
            re.fullmatch(r'([0-9a-f]{64})  ' + re.escape(filename), fields[0]) if len(fields) == 1 else None
        )
        if match is None:
            raise ValueError(f'{filename}.sha256 must name its own ZIP exactly once')
        digest = _file_sha256(folder / filename)
        if digest != match[1]:
            raise ValueError(f'SHA256 mismatch: {filename}')
        checksums[filename] = digest

    node = _node()
    node_folder = node['folder'].casefold()
    with ZipFile(folder / app_name) as archive:
        archive.getinfo('AtelierX/AtelierX.exe')
        manifest = json.loads(archive.read('AtelierX/BUILD-MANIFEST.json'))
        if any(node_folder in name.casefold().split('/') for name in archive.namelist()):
            raise ValueError(f'{app_name} contains the standalone adapter node')
    if manifest.get('version') != version or manifest.get('commit') != commit:
        raise ValueError(f'{app_name} was not built from {version} at {commit}')
    _verify_adapter(folder / adapter_name, node)
    return checksums


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build-adapter')
    build.add_argument('--source', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('folder', type=Path)
    verify.add_argument('--version', required=True)
    verify.add_argument('--commit', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'build-adapter':
            version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project'][
                'version'
            ]
            print(build_adapter(args.source, args.output, version))
        else:
            for name, digest in verify_candidate(args.folder, args.version, args.commit).items():
                print(f'- `{name}`: `{digest}`')
    except (BadZipFile, KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
