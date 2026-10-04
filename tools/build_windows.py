"""Build a fresh, allowlisted Windows portable bundle and distributable ZIP.

Run with the packaging virtual environment; Node is needed only on the build machine.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Fresh output directory (never overwritten)')
    parser.add_argument('--skip-web-build', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build Windows packages on Windows.')
    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
    output = (args.output or ROOT / 'dist' / stamp).resolve()
    if output.exists():
        parser.error(f'Choose a new output directory: {output}')
    if not args.skip_web_build:
        node = shutil.which('node')
        if not node:
            parser.error('Node.js is needed to build the frontend.')
        run(node, 'web/node_modules/typescript/bin/tsc', '-b', 'web')
        run(node, 'web/node_modules/vite/bin/vite.js', 'build', 'web')
    if not (ROOT / 'web/dist/index.html').is_file():
        parser.error('Build web/dist before packaging.')
    output.mkdir(parents=True)
    run(
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        '--distpath',
        str(output),
        '--workpath',
        str(ROOT / 'notes' / 'packaging' / f'build-{stamp}'),
        str(ROOT / 'packaging' / 'atelierx.spec'),
    )
    bundle = output / 'AtelierX'
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
    shutil.copy2(ROOT / 'packaging' / 'PORTABLE_README.txt', bundle / '읽어주세요.txt')
    run(sys.executable, 'tools/collect_licenses.py', str(bundle))
    run(sys.executable, 'tools/build_manual.py')
    shutil.copytree(ROOT / 'dist' / 'manual', bundle / 'manual')
    manifest = {
        'version': '0.0.1',
        'built_at': datetime.now().astimezone().isoformat(),
        'python': sys.version.split()[0],
        'dependencies': dict(sorted((d.metadata['Name'], d.version) for d in distributions())),
        'files': {},
    }
    forbidden = {'config', 'data', 'state', 'output', 'vendor', 'notes', '.git', '.venv', 'node_modules'}
    if forbidden & {p.name for p in bundle.iterdir()}:
        raise RuntimeError('Mutable or private folders entered the bundle.')
    for file in sorted(bundle.rglob('*')):
        if file.is_file():
            manifest['files'][file.relative_to(bundle).as_posix()] = hashlib.sha256(
                file.read_bytes()
            ).hexdigest()
    (bundle / 'BUILD-MANIFEST.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    archive = output / 'AtelierX-0.0.1-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for file in sorted(bundle.rglob('*')):
            if file.is_file():
                zipped.write(file, 'AtelierX/' + file.relative_to(bundle).as_posix())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    # LF on every platform, so `sha256sum -c` reads the file name correctly on Linux (release.yml).
    archive.with_suffix('.zip.sha256').write_text(
        f'{checksum}  {archive.name}\n', encoding='ascii', newline='\n'
    )
    print(json.dumps({'bundle': str(bundle), 'zip': str(archive), 'sha256': checksum}, indent=2))


if __name__ == '__main__':
    main()
