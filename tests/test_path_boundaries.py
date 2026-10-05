"""Item paths from requests stay in the user tree on Windows spellings too: no app folder, no drive, no stream."""

import pytest

from atelierx.core.i18n import AppError
from atelierx.core.snapshots import Snapshots
from atelierx.core.works import Work

BAD = [
    '.atelierx\\work.json',
    '.ATELIERX/work.json',
    '.Atelierx/x.md',
    '.atelierx./x.md',
    '.atelierx /x.md',
    '인물\\..\\..\\x.md',
    'C:x.md',
    '메인.md:hidden',
    '메인.md.',
    '../x.md',
]


@pytest.fixture
def work(unlocked, tmp_path):
    wid = unlocked.post('/api/samples/single/install').json()['id']
    folder = next(p for p in (tmp_path / 'data' / 'works').iterdir() if p.is_dir())
    return wid, folder


@pytest.mark.parametrize('bad', BAD)
def test_item_api_rejects_other_spellings_of_inside_and_outside(unlocked, work, bad):
    wid, folder = work
    before = (folder / '.atelierx' / 'work.json').read_bytes()
    assert unlocked.get(f'/api/works/{wid}/file', params={'path': bad}).status_code == 400
    assert unlocked.post(f'/api/works/{wid}/file', json={'path': bad}).status_code == 400
    assert unlocked.put(f'/api/works/{wid}/file', params={'path': bad}, json={'body': 'x'}).status_code == 400
    assert unlocked.post(f'/api/works/{wid}/move', json={'from': '메인.md', 'to': bad}).status_code == 400
    assert (folder / '.atelierx' / 'work.json').read_bytes() == before
    assert (folder / '메인.md').is_file()


def test_snapshot_paths_reject_other_spellings_of_the_history(work):
    _, folder = work
    snaps = Snapshots(Work(folder))
    for bad in ('.ATELIERX/history/x', '.atelierx/HISTORY/x', '.atelierx/trash./x'):
        with pytest.raises(AppError):
            snaps.path_in_work(bad)
    assert snaps.path_in_work('.atelierx/work.json') == folder / '.atelierx' / 'work.json'
