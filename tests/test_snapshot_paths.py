"""Snapshot paths, ids and digests never reach files outside the work folder or the snapshot store."""

import json

from atelierx.core.snapshots import Snapshots
from atelierx.core.works import Work


def install(client, tmp_path):
    wid = client.post('/api/samples/single/install').json()['id']
    folder = next(p for p in (tmp_path / 'data' / 'works').iterdir() if p.is_dir())
    sid = client.get(f'/api/works/{wid}/snapshots').json()[0]['id']
    return wid, folder, sid


def test_compare_reads_only_files_in_the_work(unlocked, tmp_path):
    wid, folder, sid = install(unlocked, tmp_path)
    secret = tmp_path / 'outside.md'
    secret.write_text('not part of the work', encoding='utf-8')
    url = f'/api/works/{wid}/snapshots/{sid}/file'

    ok = unlocked.get(url, params={'path': '메인.md'})
    assert ok.status_code == 200 and ok.json()['current'] == (folder / '메인.md').read_text(encoding='utf-8')
    for bad in (
        str(secret),
        '../../outside.md',
        '..\\..\\outside.md',
        'C:outside.md',
        '/outside.md',
        '.atelierx/history/x',
    ):
        response = unlocked.get(url, params={'path': bad})
        assert response.status_code == 400, bad
        assert 'not part of the work' not in response.text


def test_snapshot_ids_cannot_name_other_files(unlocked, tmp_path):
    wid, folder, _ = install(unlocked, tmp_path)
    (folder / '.atelierx' / 'history' / 'outside.json').write_text(
        json.dumps({'files': {}}), encoding='utf-8'
    )
    for sid in ('..%5Coutside', '%2E%2E%5Coutside'):
        assert unlocked.get(f'/api/works/{wid}/snapshots/{sid}/diff').status_code in (400, 404)


def test_restore_refuses_a_damaged_snapshot_before_writing(unlocked, tmp_path):
    wid, folder, sid = install(unlocked, tmp_path)
    snaps = Snapshots(Work(folder))
    path = snaps.root / 'snapshots' / f'{sid}.json'
    doc = json.loads(path.read_text(encoding='utf-8'))
    digest = doc['files']['메인.md']
    before = len(snaps.list())

    for files in ({**doc['files'], '../../escaped.md': digest}, {**doc['files'], '메인.md': '../../x'}):
        path.write_text(json.dumps({**doc, 'files': files}), encoding='utf-8')
        assert unlocked.post(f'/api/works/{wid}/snapshots/{sid}/restore', json={}).status_code == 400
    assert not (tmp_path / 'data' / 'escaped.md').exists() and not (tmp_path / 'escaped.md').exists()
    assert len(snaps.list()) == before  # no "before restore" snapshot either

    path.write_text(json.dumps(doc), encoding='utf-8')
    response = unlocked.post(f'/api/works/{wid}/snapshots/{sid}/restore', json={'paths': ['../메인.md']})
    assert response.status_code == 400


def test_restore_still_brings_a_file_back(unlocked, tmp_path):
    wid, folder, sid = install(unlocked, tmp_path)
    original = (folder / '메인.md').read_text(encoding='utf-8')
    item = unlocked.get(f'/api/works/{wid}/file', params={'path': '메인.md'}).json()
    unlocked.put(
        f'/api/works/{wid}/file', params={'path': '메인.md'}, json={'body': '바뀜', 'base_hash': item['hash']}
    )
    restored = unlocked.post(f'/api/works/{wid}/snapshots/{sid}/restore', json={'paths': ['메인.md']}).json()
    assert restored == ['메인.md'] and (folder / '메인.md').read_text(encoding='utf-8') == original
