def test_platform_settings_crud_and_usage_guard(unlocked):
    c = unlocked
    created = c.post('/api/platforms', json={'id': 'my_platform', 'name': 'Mine'} )
    assert created.status_code == 200
    assert created.json()['count'] == 'utf8_bytes'

    doc = created.json()
    doc['custom_rule'] = {'kept': True}
    c.put('/api/platforms/my_platform', json=doc)
    saved = c.put('/api/platforms/my_platform', json={
        'name': 'Renamed', 'limits': {'main': {'max': 0}, 'lorebook_entry': {'max': 120}},
    })
    assert saved.status_code == 200
    assert saved.json()['count'] == 'utf8_bytes'
    assert saved.json()['custom_rule'] == {'kept': True}
    assert saved.json()['limits']['main']['max'] == 0
    assert saved.json()['limits']['lorebook_entry']['max'] == 120

    wid = c.post('/api/works', json={'name': 'Uses preset', 'tags': ['my_platform']}).json()['id']
    blocked = c.delete('/api/platforms/my_platform')
    assert blocked.status_code == 409
    assert wid in blocked.json()['error']['values']['uses']

    c.patch('/api/works/' + wid, json={'tags': []})
    assert c.delete('/api/platforms/my_platform').status_code == 200


def test_platform_byte_limits_and_unset_limit(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    doc = c.get('/api/platforms/generic').json()
    doc['limits']['main']['max'] = 0
    doc['limits']['lorebook_entry']['max'] = None
    c.post('/api/platforms', json={'id': 'byte_limit', 'name': 'Bytes'})
    c.put('/api/platforms/byte_limit', json=doc)
    c.patch(f'/api/works/{wid}', json={'tags': ['byte_limit']})
    issues = c.get(f'/api/works/{wid}/check').json()
    over = next(i for i in issues if i['message']['key'] == 'check.too_big')
    assert over['message']['values']['max'] == 0


def test_lorebook_entry_limit_only_checks_lorebook_and_character(unlocked):
    c = unlocked
    wid = c.post('/api/works', json={'name': 'Limit kinds'}).json()['id']
    c.post('/api/platforms', json={'id': 'kind_limits', 'name': 'Kind limits'})
    c.put('/api/platforms/kind_limits', json={'limits': {
        'main': {'max': 1}, 'lorebook_entry': {'max': 1},
    }})
    c.patch(f'/api/works/{wid}', json={'tags': ['kind_limits']})
    for path, kind, ident in (
        ('main.md', 'main', 'M001'),
        ('entry.md', 'lorebook', 'L001'),
        ('person.md', 'character', 'C001'),
        ('start.md', 'start', 'S001'),
        ('widget.jsx', 'jsx', 'J001'),
    ):
        c.post(f'/api/works/{wid}/file', json={'path': path, 'kind': kind})
        current = c.get(f'/api/works/{wid}/file', params={'path': path}).json()
        c.put(f'/api/works/{wid}/file', params={'path': path}, json={
            'meta': {'id': ident}, 'body': 'long enough to exceed one byte', 'base_hash': current['hash'],
        })
    errors = {
        issue['path'] for issue in c.get(f'/api/works/{wid}/check').json()
        if issue['message']['key'] == 'check.too_big'
    }
    assert errors == {'main.md', 'entry.md', 'person.md'}


def test_platform_malformed_limits_and_non_gui_count_preserved(unlocked):
    c = unlocked
    assert c.post('/api/platforms', json={'id': '../outside'}).status_code == 400
    c.post('/api/platforms', json={'id': 'legacy', 'name': 'Legacy'})
    malformed = c.put('/api/platforms/legacy', json={'limits': []})
    assert malformed.status_code == 400
    saved = c.put('/api/platforms/legacy', json={'count': 'chars', 'limits': {
        'main': {'max': None}, 'lorebook_entry': {'max': 200},
    }})
    assert saved.status_code == 200
    assert saved.json()['count'] == 'chars'


def test_platform_delete_rejects_traversal_and_external_symlink(paths, tmp_path):
    import pytest

    from atelierx.core.i18n import AppError
    from atelierx.core.presets import Presets

    presets = Presets(paths)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('keep', encoding='utf-8')
    with pytest.raises(AppError):
        presets.delete('../outside', [], {})
    paths.platforms.mkdir(parents=True, exist_ok=True)
    link = paths.platforms / 'escape'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlinks are not enabled on this host')
    with pytest.raises(AppError):
        presets.delete('escape', [], {})
    assert (outside / 'keep.txt').read_text(encoding='utf-8') == 'keep'

