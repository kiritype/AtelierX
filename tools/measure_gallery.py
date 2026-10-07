"""Measure the gallery, review and completeness board at scale (#158).

Fills a throwaway output folder with fake images laid out like the queue writes them
(``<work>/<character>/images/<outfit>/<expression>/NNN.png`` with a JSON record), plus a review file with
verdicts, adoptions and a full history, then times the calls the screens make.

    uv run python tools/measure_gallery.py --count 20000
    uv run python tools/measure_gallery.py --count 50000 --root D:/tmp/ax-measure --keep
    uv run python tools/measure_gallery.py --count 50000 --root D:/tmp/ax-measure --keep --reuse

Freshly written files are often scanned by antivirus software, so measure a kept folder again with ``--reuse``.

The fake images are tiny, so hashing is cheaper than with real 1~2 MB files; ``--pad-kb`` makes them bigger.
"""

import argparse
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

from PIL import Image

from atelierx.core.paths import AppPaths
from atelierx.image import board
from atelierx.image.gallery import Gallery
from atelierx.image.reviews import HISTORY_KEPT, ReviewStore, _identity, _key

WORK = 'W900'
CHARACTERS = 43
OUTFITS = 2
EXPRESSIONS = 32
LIMITS = {'list': 1.0, 'review': 0.2}


def png_bytes(pad_kb):
    output = io.BytesIO()
    Image.new('RGB', (64, 64), (200, 180, 160)).save(output, format='PNG')
    data = output.getvalue()
    # Bytes after IEND are ignored by readers but count for hashing and copying.
    return data + b'\0' * (pad_kb * 1024)


def build(root, count, pad_kb, write=True):
    paths = AppPaths(root=root, defaults=ROOT / 'defaults', samples=ROOT / 'samples', web=root / 'web')
    output = Path(paths.output)
    data = png_bytes(pad_kb)
    sha = hashlib.sha256(data).hexdigest()
    combos = [
        (f'C{c:03}', f'o{o}', f'{e:03}')
        for c in range(1, CHARACTERS + 1)
        for o in range(1, OUTFITS + 1)
        for e in range(1, EXPRESSIONS + 1)
    ]
    records, adopted, history, made = {}, {}, [], []
    lab = count // 50
    for index in range(count - lab):
        character, outfit, expression = combos[index % len(combos)]
        number = index // len(combos) + 1
        relative = f'{WORK}/{character}/images/{outfit}/{expression}/{number:03}.png'
        made.append((relative, (WORK, character, outfit, expression)))
    for index in range(lab):
        made.append((f'_lab/2026-10-{index % 28 + 1:02}/{index:05}.png', None))
    for number, (relative, combo) in enumerate(made):
        if not write:
            continue
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record = {
            'created_at': f'2026-10-07T00:00:{number % 60:02}+00:00',
            'seed': number,
            'rating': 'general',
        }
        if combo:
            record.update(
                work_id=combo[0],
                character_id=combo[1],
                outfit_id=combo[2],
                expression_id=combo[3],
                settings={'family': 'anima', 'steps': 30, 'cfg': 4.5, 'prompt': 'x' * 600},
            )
        target.with_suffix('.json').write_text(json.dumps(record), encoding='utf-8')
        # Six in ten images have a person's verdict; the newest pass of each combination is adopted.
        if number % 10 < 6:
            verdict = 'pass' if number % 3 else 'fail'
            records[_identity(relative, sha)] = {
                'path': relative,
                'sha256': sha,
                'human': verdict,
                'reviewed_at': '2026-10-07T00:00:00+00:00',
                'auto': 'pass',
                'auto_reason': 'looks fine',
            }
            if verdict == 'pass' and combo:
                adopted[_key(combo)] = {'path': relative, 'sha256': sha}
    for number in range(HISTORY_KEPT if write else 0):
        history.append(
            {
                'at': '2026-10-07T00:00:00+00:00',
                'path': made[number % len(made)][0],
                'from': 'unreviewed',
                'to': 'pass',
            }
        )
    state = {'schema_version': 1, 'records': records, 'adopted': adopted, 'history': history, 'revision': 1}
    if write:
        (output / 'reviews.json').write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    work_app = root / 'work' / '.atelierx'
    for c in range(1, CHARACTERS + 1):
        design = work_app / 'image' / 'characters' / f'C{c:03}' / 'design.json'
        design.parent.mkdir(parents=True, exist_ok=True)
        design.write_text(
            json.dumps({'outfits': {f'o{o}': {'name': f'outfit {o}'} for o in range(1, OUTFITS + 1)}})
        )
    expressions = {
        f'{e:03}': {'name': f'expression {e}', 'prompt': 'smile'} for e in range(1, EXPRESSIONS + 1)
    }
    (work_app / 'image' / 'expressions.json').write_text(json.dumps({'items': expressions}))
    work = SimpleNamespace(
        id=WORK,
        app=work_app,
        index=lambda: [
            {'kind': 'character', 'name': f'C{c:03}', 'meta': {'id': f'C{c:03}'}}
            for c in range(1, CHARACTERS + 1)
        ],
    )
    return paths, work, made


def timed(results, name, call, limit=None):
    start = time.perf_counter()
    value = call()
    seconds = time.perf_counter() - start
    results.append((name, seconds, limit))
    print(f'  {name:<44} {seconds:8.3f} s' + (f'  (기준 {limit} s)' if limit else ''), flush=True)
    return value


def measure(paths, work, made):
    results = []
    gallery = Gallery(paths)
    reviews = timed(results, 'reviews.json 읽기', lambda: ReviewStore(paths, gallery))
    timed(results, '갤러리 첫 색인', lambda: gallery.scan(force=True))
    indexed = len(gallery.items)
    if indexed != len(made):
        print(f'  ! 색인된 이미지 {indexed} / {len(made)} (훑기 시간 제한에 걸림)')
    timed(results, '갤러리 다시 훑기(변경 없음)', lambda: gallery.scan(force=True), LIMITS['list'])
    timed(results, '목록 첫 쪽(60장, 해시 처음)', lambda: reviews.list({}), LIMITS['list'])
    timed(results, '목록 첫 쪽(60장, 다시)', lambda: reviews.list({}), LIMITS['list'])
    timed(
        results,
        '목록 검수 필터(전체 해시 처음)',
        lambda: reviews.list({'human_status': 'pass'}),
        LIMITS['list'],
    )
    timed(results, '목록 검수 필터(다시)', lambda: reviews.list({'human_status': 'pass'}), LIMITS['list'])
    timed(results, '분류 나무', gallery.tree, LIMITS['list'])
    target = next(r for r, combo in made if combo)
    timed(
        results,
        '판정 1건 저장',
        lambda: reviews.review({'verdict': 'pass', 'items': [target]}),
        LIMITS['review'],
    )
    timed(
        results,
        '판정 100건 저장',
        lambda: reviews.review({'verdict': 'fail', 'items': [r for r, c in made[:100] if c]}),
    )
    runtime = SimpleNamespace(
        paths=paths, gallery=gallery, reviews=reviews, queue=SimpleNamespace(select=lambda f: [])
    )
    timed(results, '완성도 보드', lambda: board.board(runtime, work), LIMITS['list'])
    timed(results, '채택 내보내기 계획', lambda: reviews.plan_export({'work': WORK}))
    return results, indexed


def memory(paths, work):
    tracemalloc.start()
    gallery = Gallery(paths)
    reviews = ReviewStore(paths, gallery)
    gallery.scan(force=True)
    reviews.list({'human_status': 'pass'})
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return current, peak


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--count', type=int, default=20000)
    parser.add_argument('--pad-kb', type=int, default=0)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--keep', action='store_true', help='keep the fake folder')
    parser.add_argument(
        '--reuse', action='store_true', help='measure a folder kept earlier with the same --count'
    )
    args = parser.parse_args()
    root = args.root or Path(tempfile.mkdtemp(prefix='ax-measure-'))
    try:
        start = time.perf_counter()
        reuse = args.reuse and args.root is not None
        paths, work, made = build(root, args.count, args.pad_kb, write=not reuse)
        print(
            f'가짜 이미지 {len(made)}장 '
            + ('다시 씀' if reuse else '만들기')
            + f': {time.perf_counter() - start:.1f} s ({root})'
        )
        size = (Path(paths.output) / 'reviews.json').stat().st_size
        print(f'reviews.json {size / 1024 / 1024:.1f} MB')
        results, _ = measure(paths, work, made)
        current, peak = memory(paths, work)
        print(
            f'  {"메모리(색인+검수, 파이썬 할당)":<44} {current / 1024 / 1024:8.1f} MB (최대 {peak / 1024 / 1024:.1f} MB)'
        )
        over = [name for name, seconds, limit in results if limit and seconds > limit]
        print('기준 초과: ' + (', '.join(over) if over else '없음'))
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    main()
