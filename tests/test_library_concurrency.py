"""Library transactions and editor revisions (#227)."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from atelierx.image import library


def test_concurrent_saves_preserve_both_items(paths, monkeypatch):
    path = library._file(paths, None, 'common', 'global')
    read = library.read_json
    entered, release = threading.Event(), threading.Event()
    start = threading.Barrier(3)

    def paused_read(candidate, *args):
        value = read(candidate, *args)
        if candidate == path and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return value

    monkeypatch.setattr(library, 'read_json', paused_read)

    def save(ident):
        start.wait(timeout=5)
        return library.save_item(paths, None, 'common', 'global', ident, {'name': ident})

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(save, ident) for ident in ('one', 'two')]
        start.wait(timeout=5)
        assert entered.wait(5)
        acquired = library._lock.acquire(blocking=False)
        if acquired:
            library._lock.release()
        release.set()
        assert not acquired, 'The read must hold the transaction lock until its write finishes.'
        for future in futures:
            future.result(timeout=5)
    assert set(library.items(paths, None, 'common')) == {'one', 'two'}


def test_failed_scope_move_restores_destination_and_keeps_source(paths, monkeypatch):
    work = SimpleNamespace(app=paths.root / 'work' / '.atelierx')
    library.save_item(paths, work, 'common', 'global', 'one', {'name': 'global'})
    library.save_item(paths, work, 'common', 'work', 'one', {'name': 'work'})
    write = library.atomic_json

    def fail_source(path, doc):
        if path == library._file(paths, work, 'common', 'work'):
            raise OSError('source is locked')
        write(path, doc)

    monkeypatch.setattr(library, 'atomic_json', fail_source)
    with pytest.raises(OSError):
        library.save_item(paths, work, 'common', 'global', 'one', {'name': 'moved'}, 'work')
    assert library.items(paths, work, 'common')['one']['name'] == 'work'
    assert library.items(paths, None, 'common')['one']['name'] == 'global'


def test_api_rejects_stale_save_delete_and_import(unlocked):
    c = unlocked
    url = '/api/image/library/common/unique'
    first = c.put(url, json={'item': {'name': 'first'}}).json()['unique']
    exported = c.get('/api/image/library-share/common/export?ids=unique').json()
    preview = c.post('/api/image/library-share/common/preview', json={'file': exported}).json()
    second = c.put(url, json={'item': {'name': 'second'}, 'revision': first['revision']})
    assert second.status_code == 200
    stale = c.put(url, json={'item': {'name': 'stale'}, 'revision': first['revision']})
    assert stale.status_code == 409
    assert stale.json()['error']['key'] == 'server.save.stale'
    assert c.delete(url, params={'revision': first['revision']}).status_code == 409
    response = c.post(
        '/api/image/library-share/common/import',
        json={
            'file': exported,
            'choices': {'unique': 'overwrite'},
            'revisions': {'unique': preview['items'][0]['revision']},
        },
    )
    assert response.status_code == 409
    assert c.get('/api/image/library/common').json()['unique']['name'] == 'second'
    assert c.delete(url, params={'revision': second.json()['unique']['revision']}).status_code == 200


def test_unrelated_item_change_does_not_invalidate_editor(unlocked):
    c = unlocked
    one = c.put('/api/image/library/common/one', json={'item': {'name': 'one'}}).json()['one']
    assert c.put('/api/image/library/common/two', json={'item': {'name': 'two'}}).status_code == 200
    assert (
        c.put(
            '/api/image/library/common/one',
            json={
                'item': {'name': 'changed'},
                'revision': one['revision'],
            },
        ).status_code
        == 200
    )


def test_move_rejects_changed_destination_and_does_not_persist_revision(unlocked, paths):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    url = '/api/image/library/common/moving'
    original = c.put(url, json={'item': {'name': 'global'}}).json()['moving']
    override = c.put(
        url,
        json={
            'work': wid,
            'scope': 'work',
            'item': {'name': 'work'},
            'revision': original['revision'],
        },
    ).json()['moving']
    assert (
        c.put(url, json={'item': {'name': 'new global'}, 'revision': original['revision']}).status_code == 200
    )
    refused = c.put(
        url,
        json={
            'work': wid,
            'scope': 'global',
            'from_scope': 'work',
            'item': {'name': 'move'},
            'revision': override['revision'],
        },
    )
    assert refused.status_code == 409
    assert c.get('/api/image/library/common', params={'work': wid}).json()['moving']['name'] == 'work'
    assert c.get('/api/image/library/common').json()['moving']['name'] == 'new global'
    assert 'revision' not in library.read_json(paths.data / 'image' / 'common.json')['items']['moving']
