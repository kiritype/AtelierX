import io
import json
import os

from PIL import Image

from atelierx.image.gallery import Gallery
from atelierx.image.reviews import ReviewStore


def _png(color):
    output = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(output, format='PNG')
    return output.getvalue()


def _image(paths, relative, color=(0, 0, 0), record=None):
    target = paths.output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_png(color))
    if record is not None:
        target.with_suffix('.json').write_text(json.dumps(record), encoding='utf-8')
    return target


def _touch_later(path):
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


A = 'W001/C001/images/o01/001/001.png'
B = 'W001/C001/images/o01/002/001.png'


def test_the_index_rereads_only_changed_files_and_drops_removed_ones(paths):
    _image(paths, A, record={'rating': 'general', 'expression_name': 'calm'})
    _image(paths, B, record={'rating': 'general'})
    gallery = Gallery(paths)
    gallery.scan(force=True)
    first = {i['path']: i for i in gallery.snapshot_items()}
    assert set(first) == {A, B} and first[A]['expression_name'] == 'calm'

    # Changing a record alone updates its item; the other item is the same object, not read again.
    record = paths.output / A.replace('.png', '.json')
    record.write_text(json.dumps({'rating': 'sensitive', 'expression_name': 'calm'}), encoding='utf-8')
    _touch_later(record)
    gallery.scan(force=True)
    second = {i['path']: i for i in gallery.snapshot_items()}
    assert second[A]['rating'] == 'sensitive'
    assert second[B] is first[B]

    (paths.output / B).unlink()
    gallery.scan(force=True)
    assert [i['path'] for i in gallery.snapshot_items()] == [A]
    assert gallery.find(A, refresh=False)['path'] == A


def test_hashes_survive_a_restart_and_unreviewed_images_filter_without_hashing(paths):
    _image(paths, A, record={})
    _image(paths, B, (255, 255, 255), record={})
    gallery = Gallery(paths)
    reviews = ReviewStore(paths, gallery)
    reviews.review({'verdict': 'pass', 'items': [A]})
    hashes = json.loads((paths.state / 'image' / 'hashes.json').read_text(encoding='utf-8'))
    assert set(hashes['files']) == {A}
    # Written without indentation; still the same JSON.
    text = (paths.output / 'reviews.json').read_text(encoding='utf-8')
    assert '\n' not in text and json.loads(text)['adopted']

    restarted = ReviewStore(paths, Gallery(paths))
    opened = []
    original = restarted.sha256

    def counting(relative, fresh=False, signature=None):
        before = dict(restarted._hashes)
        value = original(relative, fresh=fresh, signature=signature)
        if restarted._hashes != before or fresh:
            opened.append(relative)
        return value

    restarted.sha256 = counting
    unreviewed = restarted.list({'human_status': 'unreviewed'})
    assert [i['path'] for i in unreviewed['results']] == [B]
    passed = restarted.list({'human_status': 'pass'})
    assert [i['path'] for i in passed['results']] == [A] and passed['results'][0]['adopted']
    # A came from the saved hashes; only B, shown on the page, was hashed.
    assert opened == [B]


def test_a_verdict_on_many_images_scans_once(paths):
    _image(paths, A, record={})
    _image(paths, B, (255, 255, 255), record={})
    gallery = Gallery(paths)
    reviews = ReviewStore(paths, gallery)
    gallery.scan(force=True)
    calls = []
    scan = gallery.scan
    gallery.scan = lambda force=False: (calls.append(force), scan(force))
    result = reviews.review({'verdict': 'fail', 'items': [A, B]})
    assert result['updated'] == 2 and len(calls) == 1
    before = reviews.state
    reviews.review({'verdict': 'pass', 'items': [A]})
    # The previous state is left as it was (a failed save would keep it).
    assert next(r for r in before['records'].values() if r['path'] == A)['human'] == 'fail'


def test_an_adopted_image_replaced_within_a_rescan_is_not_exported(paths):
    _image(paths, A, record={'work_id': 'W001'})
    gallery = Gallery(paths)
    reviews = ReviewStore(paths, gallery)
    reviews.review({'verdict': 'pass', 'items': [A]})
    assert reviews.plan_export({})['count'] == 1
    # New content right away: the index has not rescanned yet, the export still sees the change.
    target = paths.output / A
    target.write_bytes(_png((255, 0, 0)) + b'changed')
    _touch_later(target)
    assert reviews.plan_export({})['count'] == 0


def test_the_measure_tool_keeps_a_named_folder(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / 'tools' / 'measure_gallery.py'
    busy = tmp_path / 'busy'
    busy.mkdir()
    (busy / 'mine.txt').write_text('keep me', encoding='utf-8')
    refused = subprocess.run(
        [sys.executable, str(script), '--count', '10', '--root', str(busy)], capture_output=True, check=False
    )
    assert refused.returncode == 2 and (busy / 'mine.txt').is_file()
    reused = subprocess.run(
        [sys.executable, str(script), '--count', '10', '--root', str(busy), '--reuse'],
        capture_output=True,
        check=False,
    )
    assert reused.returncode == 2 and (busy / 'mine.txt').is_file()
    fresh = tmp_path / 'fresh'
    made = subprocess.run(
        [sys.executable, str(script), '--count', '60', '--root', str(fresh)], capture_output=True, check=False
    )
    assert made.returncode == 0, made.stderr.decode(errors='replace')
    assert (fresh / '.ax-measure').is_file() and (fresh / 'output' / 'reviews.json').is_file()
