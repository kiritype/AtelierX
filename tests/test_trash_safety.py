"""Trash restore never replaces an existing file, and trash ids or entries never reach folders outside the trash."""

import json

import pytest

from atelierx.core.i18n import AppError
from atelierx.core.works import Work


@pytest.fixture
def work(unlocked, tmp_path):
    wid = unlocked.post('/api/samples/single/install').json()['id']
    folder = next(p for p in (tmp_path / 'data' / 'works').iterdir() if p.is_dir())
    return wid, folder


def trashed(client, wid):
    return client.get(f'/api/works/{wid}/trash').json()[0]['id']


def test_restore_picks_a_free_name_instead_of_overwriting(unlocked, work):
    wid, folder = work
    deleted = (folder / '메인.md').read_text(encoding='utf-8')
    unlocked.delete(f'/api/works/{wid}/file', params={'path': '메인.md'})
    (folder / '메인.md').write_text('지금의 메인\n', encoding='utf-8')
    (folder / '메인 (되살림).md').write_text('먼저 되살린 것\n', encoding='utf-8')

    assert unlocked.post(f'/api/works/{wid}/trash/{trashed(unlocked, wid)}/restore').status_code == 200
    assert (folder / '메인.md').read_text(encoding='utf-8') == '지금의 메인\n'
    assert (folder / '메인 (되살림).md').read_text(encoding='utf-8') == '먼저 되살린 것\n'
    assert (folder / '메인 (되살림 2).md').read_text(encoding='utf-8') == deleted


def test_trash_ids_cannot_name_folders_outside_the_trash(unlocked, work, tmp_path):
    wid, folder = work
    (folder / 'keep').mkdir()
    (folder / 'keep' / 'note.md').write_text('남아야 함\n', encoding='utf-8')
    for bid in ('..%5C..%5Ckeep', '%2E%2E%5C%2E%2E%5Ckeep', 'C%3Akeep', '...'):
        assert unlocked.delete(f'/api/works/{wid}/trash/{bid}').status_code in (400, 404), bid
        assert unlocked.post(f'/api/works/{wid}/trash/{bid}/restore').status_code in (400, 404), bid
    for bid in ('..%5Cworks', '%2E%2E%5Cworks'):
        assert unlocked.delete(f'/api/trash/{bid}').status_code in (400, 404), bid
    assert (folder / 'keep' / 'note.md').is_file()
    assert (tmp_path / 'data' / 'works').is_dir() and folder.is_dir()

    # Without the request check, the store refuses the same names itself.
    for bid in ('..\\..\\keep', '../keep', 'C:keep', '..'):
        with pytest.raises(AppError):
            Work(folder).purge_trash(bid)
    assert (folder / 'keep' / 'note.md').is_file()


def test_a_damaged_entry_restores_nothing(unlocked, work, tmp_path):
    wid, folder = work
    unlocked.delete(f'/api/works/{wid}/file', params={'path': '메인.md'})
    bid = trashed(unlocked, wid)
    entry_path = folder / '.atelierx' / 'trash' / bid / 'entry.json'
    entry = json.loads(entry_path.read_text(encoding='utf-8'))
    for bad in ('../outside.md', '.atelierx/history/x.md', '메인.md\\..\\..\\x.md'):
        entry_path.write_text(json.dumps({**entry, 'paths': ['메인.md', bad]}), encoding='utf-8')
        assert unlocked.post(f'/api/works/{wid}/trash/{bid}/restore').status_code == 400, bad
        assert not (folder / '메인.md').exists()
    assert not (tmp_path / 'data' / 'works' / 'outside.md').exists()
