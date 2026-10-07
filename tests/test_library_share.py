"""Prompt library items exported to one file and imported elsewhere (#154)."""

import pytest
from starlette.testclient import TestClient

from atelierx.api.app import build_app
from atelierx.core.paths import REPO_ROOT, AppPaths

from conftest import FAST_KDF


def _put(c, kind, ident, scope='global', wid=None, **item):
    body = {'scope': scope, 'work': wid, 'item': {'name': ident, 'prompt': [f'{ident} tag'], **item}}
    assert c.put(f'/api/image/library/{kind}/{ident}', json=body).status_code == 200


@pytest.fixture
def other(tmp_path):
    """A second app with its own root: the other PC."""
    root = tmp_path / 'other'
    paths = AppPaths(root=root, defaults=REPO_ROOT / 'defaults', samples=REPO_ROOT / 'samples', web=root / 'web')
    with TestClient(build_app(paths, kdf=FAST_KDF), base_url='http://127.0.0.1:8765') as c:
        assert c.post('/api/auth/setup', json={'password': 'pass1234', 'language': 'ko'}).status_code == 200
        yield c


def test_chosen_items_move_to_another_root_unchanged(unlocked, other):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    _put(c, 'compositions', 'wide', group='scene', targets=['anima'], suggest_slots=['full'], hide_outfit=True)
    _put(c, 'compositions', 'close', scope='work', wid=wid)
    _put(c, 'compositions', 'left_out')
    res = c.get(f'/api/image/library-share/compositions/export?work={wid}&ids=wide,close')
    assert res.status_code == 200
    assert 'attachment' in res.headers['content-disposition']
    doc = res.json()
    assert doc['kind'] == 'atelierx-prompt-library' and doc['library'] == 'compositions' and doc['app_version']
    assert set(doc['items']) == {'wide', 'close'}
    assert doc['items']['wide']['scope'] == 'global' and doc['items']['close']['scope'] == 'work'

    preview = other.post('/api/image/library-share/compositions/preview', json={'file': doc, 'scope': 'global'})
    assert preview.status_code == 200
    rows = {r['id']: r for r in preview.json()['items']}
    assert not rows['wide']['exists'] and not rows['close']['exists']
    done = other.post('/api/image/library-share/compositions/import', json={'file': doc, 'scope': 'global'}).json()
    assert sorted(done['written']) == ['close', 'wide']
    mine = c.get(f'/api/image/library/compositions?work={wid}').json()
    theirs = other.get('/api/image/library/compositions').json()
    for ident in ('wide', 'close'):
        drop = ('scope', 'overrides')
        assert {k: v for k, v in theirs[ident].items() if k not in drop} == {
            k: v for k, v in mine[ident].items() if k not in drop
        }


def test_same_id_shows_the_changes_and_overwrite_or_skip_follow_the_choice(unlocked):
    c = unlocked
    _put(c, 'expressions', 'smile', prompt=['smile'], code='001')
    _put(c, 'expressions', 'cry', prompt=['tears'])
    doc = c.get('/api/image/library-share/expressions/export?ids=smile,cry').json()
    doc['items']['smile']['prompt'] = ['grin']
    doc['items']['cry']['prompt'] = ['sobbing']
    doc['items']['wink'] = {'name': 'wink', 'prompt': ['one eye closed']}

    rows = {
        r['id']: r
        for r in c.post('/api/image/library-share/expressions/preview', json={'file': doc, 'scope': 'global'}).json()[
            'items'
        ]
    }
    assert rows['smile']['exists'] and rows['smile']['changes'] == [
        {'field': 'prompt', 'old': ['smile'], 'new': ['grin']}
    ]
    assert not rows['wink']['exists']

    choices = {'smile': 'overwrite', 'cry': 'skip'}
    done = c.post(
        '/api/image/library-share/expressions/import', json={'file': doc, 'scope': 'global', 'choices': choices}
    ).json()
    assert sorted(done['written']) == ['smile', 'wink']
    items = c.get('/api/image/library/expressions').json()
    assert items['smile']['prompt'] == ['grin'] and items['smile']['code'] == '001'
    assert items['cry']['prompt'] == ['tears']
    # Not named: a new item is added, one already here is left alone.
    again = c.post('/api/image/library-share/expressions/import', json={'file': doc, 'scope': 'global'}).json()
    assert again['written'] == []


def test_items_go_to_the_chosen_scope(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    _put(c, 'common', 'quality', target='positive')
    doc = c.get('/api/image/library-share/common/export?ids=quality').json()
    doc['items']['quality']['prompt'] = ['best quality']
    rows = c.post(
        '/api/image/library-share/common/preview', json={'file': doc, 'scope': 'work', 'work': wid}
    ).json()['items']
    # Nothing stored in the work yet: compared with the global item the list shows.
    assert rows[0]['exists'] and rows[0]['here_scope'] == 'global'
    c.post(
        '/api/image/library-share/common/import',
        json={'file': doc, 'scope': 'work', 'work': wid, 'choices': {'quality': 'overwrite'}},
    )
    merged = c.get(f'/api/image/library/common?work={wid}').json()['quality']
    assert merged['scope'] == 'work' and merged['overrides'] and merged['prompt'] == ['best quality']
    assert c.get('/api/image/library/common').json()['quality']['prompt'] == ['quality tag']
    # A work with no id cannot take items.
    assert c.post('/api/image/library-share/common/preview', json={'file': doc, 'scope': 'work'}).status_code == 400


def test_values_this_pc_lacks_are_named_and_kept(unlocked):
    c = unlocked
    doc = {
        'kind': 'atelierx-prompt-library',
        'library': 'outfits',
        'items': {'cape': {'name': 'cape', 'prompt': ['red cape'], 'slot': 'back', 'targets': ['anima', 'flux']}},
    }
    rows = c.post('/api/image/library-share/outfits/preview', json={'file': doc, 'scope': 'global'}).json()['items']
    assert {(u['field'], u['value']) for u in rows[0]['unknown']} == {('slot', 'back'), ('targets', 'flux')}
    c.post('/api/image/library-share/outfits/import', json={'file': doc, 'scope': 'global'})
    stored = c.get('/api/image/library-share/outfits/export?ids=cape').json()['items']['cape']
    assert stored['slot'] == 'back' and stored['targets'] == ['anima', 'flux']

    doc = {
        'kind': 'atelierx-prompt-library',
        'library': 'expressions',
        'items': {'pose': {'name': 'pose', 'prompt': ['x'], 'composition': 'nowhere', 'rating': 'odd'}},
    }
    rows = c.post('/api/image/library-share/expressions/preview', json={'file': doc, 'scope': 'global'}).json()['items']
    assert {(u['field'], u['value']) for u in rows[0]['unknown']} == {('composition', 'nowhere'), ('rating', 'odd')}


def test_other_kinds_and_broken_files_are_refused(unlocked):
    c = unlocked
    _put(c, 'compositions', 'wide')
    doc = c.get('/api/image/library-share/compositions/export').json()
    res = c.post('/api/image/library-share/expressions/preview', json={'file': doc, 'scope': 'global'})
    assert res.status_code == 400 and res.json()['error']['key'] == 'server.library.share.other_kind'
    for broken in (None, [], {'kind': 'something'}, {'kind': 'atelierx-prompt-library', 'library': 'x', 'items': {}},
                   {'kind': 'atelierx-prompt-library', 'library': 'compositions', 'items': {'bad id': {}}}):
        res = c.post('/api/image/library-share/compositions/preview', json={'file': broken, 'scope': 'global'})
        assert res.status_code == 400 and res.json()['error']['key'] == 'server.library.share.bad', broken
    res = c.post(
        '/api/image/library-share/compositions/import',
        json={'file': doc, 'scope': 'global', 'choices': {'wide': 'merge'}},
    )
    assert res.status_code == 400
    assert c.get('/api/image/library-share/compositions/export?ids=missing').status_code == 400
