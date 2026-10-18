from types import SimpleNamespace

from atelierx.image.reviews import ReviewStore


def test_gallery_anchor_paging_preserves_sort_slot_after_review(paths, monkeypatch):
    entries = [
        {'path': f'work/{index:03}.png', 'folder': 'work', '_mtime_ns': index + 1} for index in range(121)
    ]
    status = {}
    store = ReviewStore(paths, SimpleNamespace(snapshot_items=lambda: entries))
    store._recorded = {item['path'] for item in entries}
    monkeypatch.setattr(
        store,
        'annotate',
        lambda item: {
            **item,
            'human_status': status.get(item['path'], 'unreviewed'),
            'auto_status': 'pending',
            'adopted': False,
        },
    )
    base = {
        'folder': 'work',
        'sort': 'oldest',
        'snapshot': '200',
        'page_size': '60',
        'human_status': 'unreviewed',
    }

    def around(index, direction=None):
        return store.list(
            {**base, 'anchor': entries[index]['path'], **({'direction': direction} if direction else {})}
        )

    first = around(59, 'next')
    assert (first['page'], first['total'], first['target_index']) == (2, 121, 60)
    assert first['results'][0]['path'] == entries[60]['path']
    assert around(60, 'prev')['results'][-1]['path'] == entries[59]['path']
    assert around(0, 'prev')['target_index'] is None
    assert around(120, 'next')['target_index'] is None

    status[entries[59]['path']] = 'pass'
    located = around(59)
    assert (located['anchor_index'], located['anchor_in_results'], located['total']) == (59, False, 120)
    assert around(59, 'next')['results'][59]['path'] == entries[60]['path']
    assert around(59, 'prev')['results'][58]['path'] == entries[58]['path']

    status[entries[60]['path']] = 'pass'
    assert around(59, 'next')['results'][59]['path'] == entries[61]['path']
    assert around(60, 'prev')['results'][58]['path'] == entries[58]['path']

    # A last page with one image still works in both directions.
    status.clear()
    assert around(119, 'next')['results'][0]['path'] == entries[120]['path']
    assert around(120, 'prev')['results'][-1]['path'] == entries[119]['path']

    reversed_page = store.list({**base, 'sort': 'newest', 'anchor': entries[60]['path'], 'direction': 'next'})
    assert reversed_page['results'][1]['path'] == entries[59]['path']

    store.gallery.snapshot_items = lambda: entries[:60]
    assert around(59, 'next')['target_index'] is None
    store.gallery.snapshot_items = lambda: entries

    status.update({item['path']: 'pass' for item in entries})
    empty = store.list({**base, 'page': '3', 'anchor': entries[120]['path']})
    assert (empty['page'], empty['total'], empty['anchor_index'], empty['anchor_in_results']) == (
        1,
        0,
        0,
        False,
    )
    assert around(120, 'prev')['target_index'] is None
