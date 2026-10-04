"""Collect bundled Python and frontend dependency license metadata and texts.

Run with the packaging Python environment after frontend dependencies are installed:
    python tools/collect_licenses.py dist/<build>/AtelierX

The output contains THIRD_PARTY_NOTICES.md and the license texts found in that
environment. Missing texts are reported for review; this tool does not infer a
license where package metadata does not declare one.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from email.parser import Parser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LICENSE_NAMES = (
    'LICENSE',
    'LICENSE.txt',
    'LICENSE.md',
    'COPYING',
    'COPYING.txt',
    'NOTICE',
    'NOTICE.txt',
    'AUTHORS',
    'AUTHORS.md',
)
PYTHON_LICENSE_FALLBACKS = {
    # Apply only to the versions present in the locked Windows packaging environment.
    ('proxy_tools', '0.1.0'): {
        'license': 'MIT (package metadata); upstream LICENSE.txt contains BSD-style terms',
        'text': ROOT / 'packaging' / 'licenses' / 'proxy_tools-0.1.0' / 'LICENSE.txt',
    },
    ('clr_loader', '0.3.1'): {
        'license': 'MIT (versioned upstream LICENSE; metadata omits a license field)',
    },
    ('pyinstaller_hooks_contrib', '2026.8'): {
        'license': 'GPL-2.0-or-later (standard hooks); Apache-2.0 (runtime hooks)',
    },
}
PYWEBVIEW_WEBVIEW2_SDK = {'6.2.1': '1.0.3856.49'}


def safe_name(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value).strip('._') or 'license'


def copy_license_files(source_dirs: list[Path], destination: Path) -> list[str]:
    """Copy conventional license/notice files and return output-relative paths."""
    copied: list[str] = []
    seen: set[Path] = set()
    destination.mkdir(parents=True, exist_ok=True)
    for source_dir in source_dirs:
        if not source_dir.is_dir():
            continue
        for filename in LICENSE_NAMES:
            candidate = source_dir / filename
            if not candidate.is_file() or candidate.resolve() in seen:
                continue
            seen.add(candidate.resolve())
            target = destination / filename
            if target.exists():
                target = destination / f'{len(copied) + 1}-{filename}'
            shutil.copyfile(candidate, target)
            copied.append(target.as_posix())
    return copied


def python_packages() -> list[dict[str, Any]]:
    """Read installed distribution metadata without requiring packaging libraries."""
    rows: list[dict[str, Any]] = []
    for metadata_path in sorted(Path(sys.prefix).glob('Lib/site-packages/*.dist-info/METADATA')):
        try:
            message = Parser().parsestr(metadata_path.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            continue
        name = message.get('Name') or metadata_path.parent.name.removesuffix('.dist-info')
        version = message.get('Version', 'unknown')
        license_fields = message.get_all('License-Expression', []) + message.get_all('License', [])
        license_fields = list(dict.fromkeys(item.strip() for item in license_fields if item.strip()))
        fallback = PYTHON_LICENSE_FALLBACKS.get((name.lower().replace('-', '_'), version))
        license_files = list(dict.fromkeys(message.get_all('License-File', [])))
        license_dirs = [metadata_path.parent / 'licenses', metadata_path.parent]
        # Copy to a package-specific location, keeping the original names when possible.
        source_files: list[Path] = []
        for license_dir in license_dirs:
            if license_dir.is_dir():
                source_files.extend(
                    file
                    for file in license_dir.iterdir()
                    if file.is_file()
                    and file.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS'))
                )
        if fallback and fallback.get('text') and fallback['text'].is_file():
            source_files.append(fallback['text'])
        rows.append(
            {
                'name': name,
                'version': version,
                'license': fallback['license']
                if fallback
                else '; '.join(license_fields) or 'Not declared in package metadata',
                'metadata_license_files': license_files,
                'metadata_path': metadata_path.parent,
                'source_files': list(dict.fromkeys(source_files)),
            }
        )
    return rows


def npm_packages() -> list[dict[str, Any]]:
    lock_path = ROOT / 'web' / 'package-lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    rows: list[dict[str, Any]] = []
    for lock_key, info in sorted(lock.get('packages', {}).items()):
        if not lock_key.startswith('node_modules/') or info.get('dev') is True:
            continue
        package_dir = ROOT / 'web' / lock_key
        package_json = package_dir / 'package.json'
        if not package_json.is_file():
            continue
        try:
            manifest = json.loads(package_json.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        name = manifest.get('name', lock_key.removeprefix('node_modules/'))
        version = manifest.get('version', info.get('version', 'unknown'))
        declared = manifest.get('license', info.get('license', 'Not declared in package metadata'))
        if isinstance(declared, dict):
            declared = json.dumps(declared, ensure_ascii=False, sort_keys=True)
        # Some packages keep the license next to what they ship (Pretendard: dist/LICENSE.txt, SIL OFL).
        source_files = [
            file
            for folder in (package_dir, package_dir / 'dist')
            if folder.is_dir()
            for file in folder.iterdir()
            if file.is_file() and file.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS'))
        ]
        rows.append(
            {
                'name': name,
                'version': version,
                'license': str(declared),
                'metadata_license_files': [],
                'metadata_path': package_dir,
                'source_files': source_files,
            }
        )
    return rows


def python_runtime() -> tuple[str, list[Path]]:
    version = sys.version.split()[0]
    candidates = [
        Path(sys.base_prefix) / 'LICENSE.txt',
        Path(sys.base_prefix) / 'LICENSE',
        Path(sys.base_prefix) / 'LICENSE.rtf',
        Path(sys.base_prefix) / 'COPYING.txt',
    ]
    found = [path for path in candidates if path.is_file()]
    return version, found


def render_section(title: str, rows: list[dict[str, Any]], output: Path, prefix: str) -> list[str]:
    lines = [
        f'## {title}',
        '',
        '| Component | Version | Category | License declared in metadata | License / notice files |',
        '|---|---:|---|---|---|',
    ]
    for row in rows:
        directory = output / 'licenses' / prefix / safe_name(row['name'])
        sources: list[Path] = row['source_files']
        # Also honor explicit PEP 639 license file paths, including unusual names.
        metadata_dir: Path = row['metadata_path']
        for relative in row['metadata_license_files']:
            candidate = metadata_dir / 'licenses' / relative
            if not candidate.is_file():
                candidate = metadata_dir / relative
            if candidate.is_file():
                sources.append(candidate)
        dests = copy_license_files_from_paths(sources, directory, output)
        label = ', '.join(f'`{path}`' for path in dests) if dests else 'No conventional license text found'
        category = row.get('component_kind', 'production dependency')
        lines.append(f'| {row["name"]} | {row["version"]} | {category} | {row["license"]} | {label} |')
    lines.append('')
    return lines


def render_native_gui_notices(output: Path) -> list[str]:
    """Record versioned native GUI components copied from the packaging environment."""

    def shipped(relative: Path) -> Path | None:
        for candidate in (output / '_internal' / relative, output / relative):
            if candidate.is_file():
                return candidate
        return None

    pywebview_version = next(
        (row['version'] for row in python_packages() if row['name'].lower().replace('-', '_') == 'pywebview'),
        None,
    )
    sdk_version = PYWEBVIEW_WEBVIEW2_SDK.get(pywebview_version)
    sdk_binaries = [
        Path('webview/lib/Microsoft.Web.WebView2.Core.dll'),
        Path('webview/lib/Microsoft.Web.WebView2.WinForms.dll'),
        Path('webview/lib/runtimes/win-x64/native/WebView2Loader.dll'),
        Path('webview/lib/runtimes/win-x86/native/WebView2Loader.dll'),
        Path('webview/lib/runtimes/win-arm64/native/WebView2Loader.dll'),
    ]
    shipped_sdk_binaries = [shipped(path) for path in sdk_binaries]
    lines = ['## Native GUI components', '']
    if sdk_version and all(path is not None for path in shipped_sdk_binaries):
        license_source = ROOT / 'packaging' / 'licenses' / f'webview2-sdk-{sdk_version}' / 'LICENSE.txt'
        copied = copy_license_files_from_paths([license_source], output / 'licenses' / 'webview2-sdk', output)
        label = ', '.join(f'`{path}`' for path in copied) if copied else 'License text missing'
        lines.append(
            f'pywebview {pywebview_version} supplies the Microsoft.Web.WebView2 .NET assemblies and '
            f'architecture-specific WebView2Loader.dll files (SDK {sdk_version}); license: {label}. '
            f'Source: https://www.nuget.org/packages/Microsoft.Web.WebView2/{sdk_version}/License'
        )
        lines.append(
            'This records the WebView2 SDK files shipped in the app; it does not include or determine the '
            'license state of the separate WebView2 Runtime on a target Windows machine.'
        )
    elif any(path is not None for path in shipped_sdk_binaries):
        lines.append(
            'WebView2 SDK binaries are present, but this generator has no exact pywebview-version mapping; '
            'review their version and license before distribution.'
        )
    else:
        lines.append('No WebView2 SDK binaries were found in this packaging environment.')

    pythonnet = shipped(Path('pythonnet/runtime/Python.Runtime.dll'))
    clr_loaders = [shipped(Path('clr_loader/ffi/dlls') / arch / 'ClrLoader.dll') for arch in ('amd64', 'x86')]
    if pythonnet or any(clr_loaders):
        lines.append(
            'Frozen `Python.Runtime.dll` and `ClrLoader.dll` files, when present in the application, '
            'come from the pythonnet and clr-loader distributions listed above; their copied package '
            'license texts are in `licenses/python/`.'
        )
    lines.append('')
    return lines


def copy_license_files_from_paths(sources: list[Path], destination: Path, output_root: Path) -> list[str]:
    copied: list[str] = []
    seen: set[Path] = set()
    destination.mkdir(parents=True, exist_ok=True)
    for source in sources:
        if not source.is_file() or source.resolve() in seen:
            continue
        seen.add(source.resolve())
        target = destination / source.name
        if target.exists():
            target = destination / f'{len(copied) + 1}-{source.name}'
        shutil.copyfile(source, target)
        copied.append(target.relative_to(output_root).as_posix())
    return copied


def collect(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    notice = [
        '# Third-party notices',
        '',
        'This report is generated from the packaging Python environment, its Python distribution metadata, and the locked production dependencies in `web/package-lock.json`. It records metadata as supplied by those packages; it is not a legal review. Review entries marked as missing before distribution.',
        '',
        '## Python runtime',
        '',
    ]
    py_version, runtime_files = python_runtime()
    runtime_dest = copy_license_files_from_paths(
        runtime_files, output / 'licenses' / 'python-runtime', output
    )
    notice.append(
        f'Python {py_version}; license text: {", ".join(f"`{x}`" for x in runtime_dest) if runtime_dest else "No license file found beside this interpreter."}'
    )
    notice.extend(['', '## Python distribution inventory', ''])
    py_rows = python_packages()
    # Build tools are present in the packaging environment but not in runtime dependencies.
    # Keep a clear marker so maintainers can decide which rows belong in a particular artifact.
    runtime_names = {
        'atelierx',
        'anyio',
        'bottle',
        'certifi',
        'cffi',
        'click',
        'clr_loader',
        'cryptography',
        'h11',
        'httpcore',
        'httpx',
        'idna',
        'pillow',
        'proxy_tools',
        'pycparser',
        'pythonnet',
        'pywebview',
        'pywin32_ctypes',
        'ruamel.yaml',
        'starlette',
        'typing_extensions',
        'uvicorn',
        'watchfiles',
    }
    for row in py_rows:
        row['name_key'] = row['name'].lower().replace('-', '_')
        row['component_kind'] = (
            'runtime' if row['name_key'] in runtime_names else 'build tool or other installed distribution'
        )
    notice.extend(render_section('Packaging environment distributions', py_rows, output, 'python'))
    notice.extend(
        [
            'Rows include distributions present in the packaging environment. The runtime artifact may include a subset; use the build manifest to identify shipped components. Build-only tools are included here as a conservative inventory.',
            'The proxy_tools 0.1.0 package metadata says MIT, while its upstream LICENSE.txt says BSD-style terms; this conflict is surfaced rather than resolved here. Sources: https://github.com/jtushman/proxy_tools/blob/master/setup.py and https://github.com/jtushman/proxy_tools/blob/master/LICENSE.txt.',
            '',
        ]
    )
    # This package-lock has npm's production/dev markers. Collect only production entries.
    notice.extend(render_section('Frontend production dependencies', npm_packages(), output, 'npm'))
    notice.extend(render_native_gui_notices(output))
    notice.extend(
        [
            'The frontend table excludes packages marked as development-only in the lockfile. License expressions and texts are copied as supplied by each installed package.',
            '',
            '## Project-provided materials',
            '',
            '- AtelierX source: [MIT License](LICENSE).',
            '- Separately installed ComfyUI extensions, trainers and model files are not part of this collection. Their own repositories or download pages provide their terms.',
            '',
            '## Source repository notices',
            '',
        ]
    )
    source_notices = ROOT / 'THIRD_PARTY_NOTICES.md'
    notice.append(source_notices.read_text(encoding='utf-8').rstrip())
    notice.append('')
    (output / 'THIRD_PARTY_NOTICES.md').write_text('\n'.join(notice), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='directory to receive THIRD_PARTY_NOTICES.md and licenses/')
    args = parser.parse_args()
    collect(args.output.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
