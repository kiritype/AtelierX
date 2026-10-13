from types import SimpleNamespace

from atelierx.image.reviews import ReviewStore


def test_select_all_keeps_every_filtered_path_beyond_10000(paths, monkeypatch):
    entries = [{'path': f'matches/{i:05}.png', 'folder': 'matches', '_mtime_ns': i} for i in range(20001)]
    entries.extend(
        [
            {'path': 'other/excluded.png', 'folder': 'other', '_mtime_ns': 1},
            {'path': 'matches/newer.png', 'folder': 'matches', '_mtime_ns': 30000},
        ]
    )
    store = ReviewStore(paths, SimpleNamespace(snapshot_items=lambda: entries))
    monkeypatch.setattr(store, 'annotate', lambda item: dict(item))
    selected = store.list(
        {'folder': 'matches', 'paths_only': 'true', 'snapshot': '20000', 'sort': 'oldest', 'page_size': '2'}
    )
    # Selection includes every match even beyond the bulk admission limit: the
    # receiving operation must explicitly reject oversize requests, never lose targets.
    assert selected['total'] == len(selected['paths']) == 20001
    assert selected['paths'] == [f'matches/{i:05}.png' for i in range(20001)]
    assert len(selected['results']) == 2
    assert selected['newer'] == 1
