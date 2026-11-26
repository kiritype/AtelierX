"""Work cover selection, storage, and portability (#349)."""

import io
import json
import zipfile

from PIL import Image

COVERS_PATH = '.atelierx/covers.zip'


def _png(color):
    buffer = io.BytesIO()
    with Image.new('RGB', (48, 32), color) as image:
        image.save(buffer, 'PNG')
    return buffer.getvalue()


def _work(client, name):
    return client.post('/api/works', json={'name': name}).raise_for_status().json()['id']


def _covers_url(wid):
    return f'/api/works/{wid}/covers'


def _covers(client, wid):
    return client.get(_covers_url(wid)).raise_for_status().json()


def _add_file(client, wid, color, name, revision):
    return (
        client.post(
            _covers_url(wid) + '/upload',
            params={'filename': name, 'base_revision': revision},
            content=_png(color),
            headers={'content-type': 'image/png'},
        )
        .raise_for_status()
        .json()
    )


def _update(client, wid, ids, primary_id, revision):
    return client.put(
        _covers_url(wid), json={'ids': ids, 'primary_id': primary_id, 'base_revision': revision}
    )


def _card(client, wid):
    return next(
        work for work in client.get('/api/works').raise_for_status().json()['works'] if work['id'] == wid
    )


def _image_response(client, url):
    response = client.get(url).raise_for_status()
    assert response.headers['content-type'] == 'image/webp'
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.format == 'WEBP'
        image.load()
    return response.content


def test_cover_order_primary_and_gallery_copy_survive_source_removal(unlocked, paths):
    client = unlocked
    wid = _work(client, 'Cover work')
    initial = _covers(client, wid)
    assert initial['items'] == [] and initial['primary_id'] is None
    assert not _card(client, wid).get('cover_url')

    first = _add_file(client, wid, 'tomato', 'local.png', initial['revision'])
    (local_cover,) = first['items']
    local_id = local_cover['id']
    assert local_cover['name'] == 'local.png' and first['primary_id'] == local_id

    gallery_path = paths.output / wid / 'C001' / 'images' / 'o01' / 'smile' / 'generated.png'
    gallery_path.parent.mkdir(parents=True)
    gallery_path.write_bytes(_png('navy'))
    both = (
        client.post(
            _covers_url(wid),
            json={
                'gallery_path': gallery_path.relative_to(paths.output).as_posix(),
                'base_revision': first['revision'],
            },
        )
        .raise_for_status()
        .json()
    )
    original, gallery_cover = both['items']
    gallery_id = gallery_cover['id']
    assert original['id'] == local_id and both['primary_id'] == local_id
    gallery_image = _image_response(client, gallery_cover['url'])
    gallery_path.unlink()
    assert _image_response(client, gallery_cover['url']) == gallery_image

    reordered = (
        _update(client, wid, [gallery_id, local_id], gallery_id, both['revision']).raise_for_status().json()
    )
    assert [entry['id'] for entry in reordered['items']] == [gallery_id, local_id]
    assert reordered['primary_id'] == gallery_id
    assert _covers(client, wid) == reordered
    assert _image_response(client, _card(client, wid)['cover_url']) == gallery_image

    stale = _update(client, wid, [local_id], local_id, both['revision'])
    assert stale.status_code == 409
    assert stale.json()['error']['key'] == 'server.save.stale'
    assert _covers(client, wid) == reordered

    fallback = _update(client, wid, [local_id], None, reordered['revision']).raise_for_status().json()
    assert fallback['primary_id'] == local_id
    assert client.get(gallery_cover['url']).status_code == 404
    empty = _update(client, wid, [], None, fallback['revision']).raise_for_status().json()
    assert empty['items'] == [] and empty['primary_id'] is None
    assert not _card(client, wid).get('cover_url')


def test_covers_reject_other_works_invalid_images_and_locked_requests(unlocked, paths):
    client = unlocked
    wid = _work(client, 'Own work')
    other = _work(client, 'Another work')
    original = _covers(client, wid)
    foreign_path = paths.output / other / 'C001' / 'images' / 'o01' / 'smile' / 'other.png'
    foreign_path.parent.mkdir(parents=True)
    foreign_path.write_bytes(_png('purple'))

    denied = client.post(
        _covers_url(wid),
        json={
            'gallery_path': foreign_path.relative_to(paths.output).as_posix(),
            'base_revision': original['revision'],
        },
    )
    assert denied.status_code in (400, 403, 404)
    invalid = client.post(
        _covers_url(wid) + '/upload',
        params={'filename': 'not-an-image.png', 'base_revision': original['revision']},
        content=b'This is not an image.',
        headers={'content-type': 'image/png'},
    )
    assert invalid.status_code in (400, 415, 422)
    assert _covers(client, wid) == original

    added = _add_file(client, wid, 'teal', 'cover.png', original['revision'])
    assert client.post('/api/auth/lock').status_code == 200
    assert client.get(_covers_url(wid)).status_code == 401
    assert client.get(added['items'][0]['url']).status_code == 401


def test_cover_gallery_scope_with_reserved_work_id(unlocked, paths):
    client = unlocked
    wid = (
        client.post('/api/works', json={'name': 'Reserved', 'id': '_single'}).raise_for_status().json()['id']
    )
    other = _work(client, 'Other')
    initial = _covers(client, wid)

    def generate(work_id):
        path = paths.output / '_single' / work_id / '2026-11-26' / 'single.png'
        path.parent.mkdir(parents=True)
        path.write_bytes(_png('teal'))
        path.with_suffix('.json').write_text(json.dumps({'work_id': work_id}), encoding='utf-8')
        return path.relative_to(paths.output).as_posix()

    rejected = client.post(
        _covers_url(wid), json={'gallery_path': generate(other), 'base_revision': initial['revision']}
    )
    assert rejected.status_code == 400 and rejected.json()['error']['key'] == 'server.covers.gallery_scope'
    added = (
        client.post(
            _covers_url(wid), json={'gallery_path': generate(wid), 'base_revision': initial['revision']}
        )
        .raise_for_status()
        .json()
    )
    assert added['primary_id'] == added['items'][0]['id']


def test_cover_backup(unlocked):
    client = unlocked
    wid = _work(client, 'Portable')
    empty = _covers(client, wid)
    first = _add_file(client, wid, 'orange', 'first.png', empty['revision'])
    both = _add_file(client, wid, 'green', 'second.png', first['revision'])
    first_id, second_id = [entry['id'] for entry in both['items']]
    selected = (
        _update(client, wid, [second_id, first_id], second_id, both['revision']).raise_for_status().json()
    )
    original_image = _image_response(client, _card(client, wid)['cover_url'])

    history = f'/api/works/{wid}/snapshots'
    snapshot = client.post(history, json={}).raise_for_status().json()
    _update(client, wid, [first_id], first_id, selected['revision']).raise_for_status()
    compared = (
        client.get(f'{history}/{snapshot["id"]}/file', params={'path': COVERS_PATH}).raise_for_status().json()
    )
    assert compared['binary'] is True and compared['snapshot'] is None and compared['current'] is None
    assert (
        client.get(f'{history}/{snapshot["id"]}/file', params={'path': COVERS_PATH.upper()})
        .raise_for_status()
        .json()
        == compared
    )
    restored = client.post(
        f'{history}/{snapshot["id"]}/restore', json={'paths': [COVERS_PATH]}
    ).raise_for_status()
    assert COVERS_PATH in restored.json()
    assert _covers(client, wid) == selected

    duplicate = (
        client.post(f'/api/works/{wid}/duplicate', json={'name': 'Duplicate covers'})
        .raise_for_status()
        .json()
    )
    copied = _covers(client, duplicate['id'])
    assert [entry['id'] for entry in copied['items']] == [second_id, first_id]
    assert copied['primary_id'] == second_id
    assert _image_response(client, duplicate['cover_url']) == original_image

    copied_id = duplicate['id']
    deleted = client.delete(f'/api/works/{copied_id}').raise_for_status().json()
    client.post(f'/api/trash/{deleted["bundle"]}/restore').raise_for_status()
    assert _covers(client, copied_id) == copied

    package = client.post(
        '/api/packages/works/export', json={'ids': [wid], 'options': {'images': 'none'}}
    ).raise_for_status()
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert f'works/0/work/{COVERS_PATH}' in archive.namelist()
        assert not any(name.startswith('works/0/output/') for name in archive.namelist())
    upload = (
        client.post(
            '/api/packages/upload', content=package.content, headers={'content-type': 'application/zip'}
        )
        .raise_for_status()
        .json()
    )
    done = (
        client.post('/api/packages/works/import', json={'token': upload['token'], 'works': [{'index': 0}]})
        .raise_for_status()
        .json()
    )
    (imported,) = done['imported']
    assert imported['id'] != wid
    imported_covers = _covers(client, imported['id'])
    assert [entry['id'] for entry in imported_covers['items']] == [second_id, first_id]
    assert imported_covers['primary_id'] == second_id
    assert _image_response(client, _card(client, imported['id'])['cover_url']) == original_image


def test_missing_cover_member_leaves_other_covers_and_uses_default_card(unlocked):
    client = unlocked
    wid = _work(client, 'Missing cover')
    initial = _covers(client, wid)
    first = _add_file(client, wid, 'orange', 'first.png', initial['revision'])
    both = _add_file(client, wid, 'navy', 'second.png', first['revision'])
    primary, surviving = both['items']
    work = client.app.state.app.works.get(wid)
    archive_path = work.folder / COVERS_PATH
    missing_name = f'{primary["id"]}.webp'
    with zipfile.ZipFile(archive_path) as archive:
        members = {name: archive.read(name) for name in archive.namelist() if name != missing_name}
        assert missing_name in archive.namelist()
    with zipfile.ZipFile(archive_path, 'w') as archive:
        for name, value in members.items():
            archive.writestr(name, value)

    missing = _covers(client, wid)
    assert missing['primary_id'] is None
    assert missing['items'] == [surviving]
    assert client.get(primary['url']).status_code == 404
    assert not _card(client, wid).get('cover_url')
