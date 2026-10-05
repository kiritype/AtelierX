"""An item ID that other data refers to cannot change through a plain save, and IDs stay unique in a work."""

import pytest


@pytest.fixture
def work(unlocked, tmp_path):
    wid = unlocked.post('/api/samples/single/install').json()['id']
    folder = next(p for p in (tmp_path / 'data' / 'works').iterdir() if p.is_dir())
    return wid, folder


def get(client, wid, path):
    return client.get(f'/api/works/{wid}/file', params={'path': path}).json()


def put(client, wid, path, **data):
    return client.put(f'/api/works/{wid}/file', params={'path': path}, json=data)


def test_a_linked_id_is_locked_but_the_item_still_saves(unlocked, work):
    wid, folder = work
    item = get(unlocked, wid, '인물/윤하람.md')
    assert item['meta']['id'] == 'C001' and {'char', 'relations'} <= set(item['id_links'])

    before = (folder / '인물' / '윤하람.md').read_bytes()
    response = put(
        unlocked,
        wid,
        '인물/윤하람.md',
        meta={**item['meta'], 'id': 'C002'},
        body=item['body'],
        base_hash=item['hash'],
    )
    assert response.status_code == 409 and response.json()['error']['key'] == 'server.works.id_linked'
    assert (folder / '인물' / '윤하람.md').read_bytes() == before
    for meta in ({**item['meta'], 'id': None}, {**item['meta'], 'id': 'c001x'}):
        assert put(unlocked, wid, '인물/윤하람.md', meta=meta, base_hash=item['hash']).status_code == 409

    saved = put(
        unlocked,
        wid,
        '인물/윤하람.md',
        meta=item['meta'],
        body=item['body'] + '\n추가',
        base_hash=item['hash'],
    )
    assert saved.status_code == 200 and saved.json()['meta']['id'] == 'C001'


def test_ids_are_unique_in_the_work_ignoring_case(unlocked, work):
    wid, _ = work
    new = unlocked.post(f'/api/works/{wid}/file', json={'path': '장소/서점'}).json()
    for taken in ('L001', 'l001'):
        response = put(unlocked, wid, new['path'], meta={'id': taken}, base_hash=new['hash'])
        assert response.status_code == 409 and response.json()['error']['key'] == 'server.works.id_taken'

    first = put(unlocked, wid, new['path'], meta={'id': 'L099'}, base_hash=new['hash']).json()
    assert first['meta']['id'] == 'L099' and first['id_links'] == []
    # Nothing refers to L099 yet, so it can still change.
    assert put(unlocked, wid, new['path'], meta={'id': 'L100'}, base_hash=first['hash']).status_code == 200
