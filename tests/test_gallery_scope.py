import hashlib
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from atelierx.image.gallery import Gallery
from atelierx.image.reviews import ReviewStore


def _png(color=(20, 40, 60)):
    output = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(output, format='PNG')
    return output.getvalue()


def _image(paths, relative, record=None, color=(20, 40, 60)):
    target = paths.output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_png(color))
    if record is not None:
        target.with_suffix('.json').write_text(json.dumps(record), encoding='utf-8')
    return target


def _asset(work, filename):
    return f'{work}/C001/images/o01/e01/{filename}.png'


def test_work_list_and_tree_never_walk_other_work_or_single_generation(paths, monkeypatch):
    _image(paths, _asset('W001', '001'), {'rating': 'general'})
    _image(paths, _asset('W002', '001'), {'rating': 'general'})
    _image(paths, '_single/W001/001.png', {'work_id': 'W001', 'rating': 'general'})
    _image(paths, '_single/W002/001.png', {'work_id': 'W002', 'rating': 'general'})
    gallery = Gallery(paths)
    reviews = ReviewStore(paths, gallery)
    visited = []
    scandir = os.scandir

    def tracking_scandir(path):
        visited.append(Path(path).resolve())
        return scandir(path)

    monkeypatch.setattr('atelierx.image.gallery.os.scandir', tracking_scandir)
    listed = reviews.list({'library_work': 'W001'})
    tree = gallery.tree('W001')

    assert {item['path'] for item in listed['results']} == {
        _asset('W001', '001'),
        '_single/W001/001.png',
    }
    assert [branch['id'] for branch in tree['works']] == ['W001']
    assert all(
        path.is_relative_to(paths.output / 'W001') or path.is_relative_to(paths.output / '_single' / 'W001')
        for path in visited
    )


def test_work_scope_keeps_missing_record_single_images_and_limits_paths_and_pages(paths):
    missing_record = _asset('W001', '001')
    _image(paths, missing_record)
    _image(paths, _asset('W001', '002'), {'rating': 'general'})
    _image(paths, '_single/W001/001.png', {'work_id': 'W001', 'rating': 'general'})
    _image(paths, _asset('W002', '001'), {'rating': 'general'})
    reviews = ReviewStore(paths, Gallery(paths))

    first = reviews.list({'library_work': 'W001', 'page_size': '1', 'sort': 'oldest'})
    all_paths = reviews.list(
        {'library_work': 'W001', 'page_size': '1', 'sort': 'oldest', 'paths_only': 'true'}
    )

    assert first['total'] == 3 and len(first['results']) == 1
    assert all_paths['total'] == len(all_paths['paths']) == 3
    assert _asset('W002', '001') not in all_paths['paths']
    item = next(
        item
        for item in reviews.list({'library_work': 'W001', 'page_size': '20'})['results']
        if item['path'] == missing_record
    )
    assert item['has_record'] is False
    assert '_single/W001/001.png' in all_paths['paths']


def test_work_scope_refreshes_added_changed_and_deleted_files(paths):
    relative = _asset('W001', '001')
    target = _image(paths, relative, {'rating': 'general'})
    index = Gallery(paths).for_work('W001')
    index.scan(force=True)
    assert [item['path'] for item in index.snapshot_items()] == [relative]

    record = target.with_suffix('.json')
    record.write_text(json.dumps({'rating': 'sensitive'}), encoding='utf-8')
    stat = record.stat()
    os.utime(record, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    added = _image(paths, _asset('W001', '002'), {'rating': 'general'})
    index.scan(force=True)
    items = {item['path']: item for item in index.snapshot_items()}
    assert items[relative]['rating'] == 'sensitive'
    assert added.relative_to(paths.output).as_posix() in items

    target.unlink()
    index.scan(force=True)
    assert relative not in {item['path'] for item in index.snapshot_items()}


def test_detail_and_review_do_not_scan_the_global_gallery(paths, monkeypatch):
    relative = _asset('W001', '001')
    _image(paths, relative, {'work_id': 'W001', 'rating': 'general'})
    gallery = Gallery(paths)
    reviews = ReviewStore(paths, gallery)
    scans = []
    monkeypatch.setattr(gallery, 'scan', lambda force=False: scans.append(force))

    assert reviews.detail(relative)['path'] == relative
    assert reviews.review({'verdict': 'pass', 'items': [relative]})['updated'] == 1
    assert scans == []


def test_direct_lookup_keeps_hidden_images_out_of_the_gallery(paths):
    relative = '.hidden/private.png'
    _image(paths, relative)
    reviews = ReviewStore(paths, Gallery(paths))
    with pytest.raises(ValueError):
        reviews.detail(relative)
    with pytest.raises(ValueError):
        reviews.review({'verdict': 'pass', 'items': [relative]})


def test_full_refresh_invalidates_scoped_indexes(paths):
    relative = _asset('W001', '001')
    target = _image(paths, relative)
    gallery = Gallery(paths)
    old = gallery.for_work('W001')
    assert len(old.snapshot_items()) == 1
    target.unlink()
    gallery.scan(force=True)
    assert gallery.for_work('W001') is not old
    assert gallery.for_work('W001').snapshot_items() == []


def test_gallery_routes_pass_the_work_boundary_to_both_list_and_tree(unlocked):
    paths = unlocked.app.state.app.image.paths
    _image(paths, _asset('W001', '001'))
    _image(paths, '_single/W001/001.png')
    _image(paths, _asset('W002', '001'))
    response = unlocked.get('/api/image/gallery?library_work=W001')
    assert response.status_code == 200
    assert response.json()['total'] == 2
    tree = unlocked.get('/api/image/gallery/tree?library_work=W001')
    assert tree.status_code == 200
    assert [work['id'] for work in tree.json()['works']] == ['W001']
    assert unlocked.get('/api/image/gallery').json()['total'] == 3


def test_scoped_review_hash_flush_preserves_hashes_for_unloaded_works(paths):
    first = _asset('W001', '001')
    second = _asset('W002', '001')
    first_file = _image(paths, first, {'rating': 'general'})
    second_file = _image(paths, second, {'rating': 'general'})
    second_digest = hashlib.sha256(second_file.read_bytes()).hexdigest()
    # An old signature for W001 forces this scope to update the cache before flushing it.
    cache = paths.state / 'image' / 'hashes.json'
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'files': {
                    first: [0, 0, 'old-hash'],
                    second: [second_file.stat().st_mtime_ns, second_file.stat().st_size, second_digest],
                },
            }
        ),
        encoding='utf-8',
    )
    store = ReviewStore(paths, Gallery(paths))

    result = store.list({'library_work': 'W001'})
    persisted = json.loads(cache.read_text(encoding='utf-8'))['files']

    assert result['results'][0]['path'] == first
    assert persisted[second] == [second_file.stat().st_mtime_ns, second_file.stat().st_size, second_digest]
    assert persisted[first][2] == hashlib.sha256(first_file.read_bytes()).hexdigest()


def test_work_scope_rejects_invalid_ids_and_symlink_escapes(paths):
    gallery = Gallery(paths)
    with pytest.raises(ValueError):
        gallery.for_work('../outside')

    outside = paths.root / 'outside'
    outside.mkdir()
    link = paths.output / 'W003'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f'directory symlinks unavailable: {error}')
    with pytest.raises(ValueError):
        gallery.for_work('W003')
