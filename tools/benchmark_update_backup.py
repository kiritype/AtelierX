"""Compare update backup policies on synthetic data; never reads an installed app's data.

Run: uv run python tools/benchmark_update_backup.py --parent <scratch-directory> --rounds 3
The newly created fixture directory is retained for inspection; all archives are hash-checked.
"""

import argparse
import hashlib
import json
import random
import shutil
import statistics
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image

from atelierx.core.fsutil import write_json
from atelierx.core.paths import AppPaths
from atelierx.core.updater import Updater, finish_update


def cleanup_benchmark(parent, rounds, files=2000):
    results = []
    for iteration in range(rounds):
        for policy in ('legacy', 'deferred'):
            root = Path(tempfile.mkdtemp(prefix='cleanup-', dir=parent)).resolve()
            paths = AppPaths.for_dev(root)
            folder = paths.state / 'update'
            backup = folder / 'backups' / ('a' * 32)
            backup.mkdir(parents=True)
            for n in range(files):
                (backup / f'{n}.dll').write_bytes(b'x' * 2048)
            (folder / 'new').mkdir()
            write_json(folder / 'pending.json', {'version': 'v9.9.9', 'from': '0.6.0'})
            write_json(folder / 'result.json', {'state': 'ok', 'backup_id': 'a' * 32})
            start = time.perf_counter()
            if policy == 'legacy':
                assert backup.resolve().is_relative_to(root)
                shutil.rmtree(backup)
                shutil.rmtree(folder / 'new')
            else:
                finish_update(paths)
            before_ready = time.perf_counter() - start
            start = time.perf_counter()
            if policy == 'deferred':
                Updater(paths).cleanup.run()
            after_ready = time.perf_counter() - start
            assert not backup.exists()
            results.append({'policy': policy, 'before_ready_s': before_ready, 'after_ready_s': after_ready})
    return {
        'files': files,
        'runs': results,
        'medians': {
            policy: {
                key: statistics.median(r[key] for r in results if r['policy'] == policy)
                for key in ('before_ready_s', 'after_ready_s')
            }
            for policy in ('legacy', 'deferred')
        },
    }


def legacy_files(root):
    for name in ('config', 'data', 'state'):
        for path in (root / name).rglob('*'):
            rel = path.relative_to(root)
            if (
                not path.is_file()
                or (
                    name == 'state'
                    and len(rel.parts) > 1
                    and rel.parts[1] in ('update', 'packages', 'webview', 'logs')
                )
                or path.name == 'desktop.lock'
            ):
                continue
            yield path


def run(parent, rounds, texts=600, images=16, excluded=4000):
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='update-bench-', dir=parent)).resolve()
    for folder in ('config', 'data/works', 'data/image-tools', 'state/update', 'state/webview'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    rng = random.Random(323)
    for i in range(texts):
        (root / 'data/works' / f'{i}.md').write_text(
            f'Synthetic character prompt {i}. ' * 300, encoding='utf-8'
        )
    for i in range(images):
        image = Image.frombytes('RGB', (1024, 1024), rng.randbytes(1024 * 1024 * 3))
        image.save(root / 'data/image-tools' / f'{i}.png')
        image.save(root / 'data/image-tools' / f'{i}.jpg', quality=90)
    (root / 'config/settings.json').write_text('{"language":"ko"}', encoding='utf-8')
    for i in range(excluded):
        folder = root / 'state/webview' / str(i // 40)
        folder.mkdir(exist_ok=True)
        (folder / f'{i}.cache').write_bytes(b'cache' * 10)
    expected = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_files(root)
    }
    up = Updater(AppPaths.for_dev(root))
    results = []
    policies = ('legacy', 'fast-deflate', 'mixed')
    for iteration in range(rounds):
        # Rotate order so one policy does not always get the warmest cache.
        for policy in policies[iteration % 3 :] + policies[: iteration % 3]:
            start = time.perf_counter()
            files = list(legacy_files(root) if policy == 'legacy' else up._backup_files())
            walk = time.perf_counter() - start
            target = root / 'state/update' / f'{policy}-{iteration}.zip'
            start = time.perf_counter()
            with zipfile.ZipFile(
                target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6 if policy == 'legacy' else 1
            ) as archive:
                for path in files:
                    compressed = policy == 'mixed' and path.suffix.lower() in {
                        '.png',
                        '.jpg',
                        '.jpeg',
                        '.webp',
                        '.zip',
                        '.gz',
                        '.7z',
                        '.mp4',
                    }
                    archive.write(
                        path,
                        path.relative_to(root).as_posix(),
                        compress_type=zipfile.ZIP_STORED if compressed else zipfile.ZIP_DEFLATED,
                    )
            compression = time.perf_counter() - start
            with zipfile.ZipFile(target) as archive:
                actual = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
            assert actual == expected
            results.append(
                {
                    'policy': policy,
                    'walk_s': walk,
                    'write_s': compression,
                    'total_s': walk + compression,
                    'zip_bytes': target.stat().st_size,
                }
            )
    summary = {
        p: {
            k: statistics.median(r[k] for r in results if r['policy'] == p)
            for k in ('walk_s', 'write_s', 'total_s', 'zip_bytes')
        }
        for p in policies
    }
    return {
        'fixture': str(root),
        'files': len(expected),
        'source_bytes': sum(p.stat().st_size for p in legacy_files(root)),
        'excluded_files': excluded,
        'rounds': rounds,
        'hashes_match': True,
        'medians': summary,
        'runs': results,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--texts', type=int, default=600)
    parser.add_argument('--images', type=int, default=16)
    parser.add_argument('--excluded', type=int, default=4000)
    parser.add_argument(
        '--cleanup', action='store_true', help='Also measure deferred cleanup on 2,000 small files'
    )
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    result = run(args.parent.resolve(), args.rounds, args.texts, args.images, args.excluded)
    if args.cleanup:
        result['cleanup'] = cleanup_benchmark(args.parent.resolve(), args.rounds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
