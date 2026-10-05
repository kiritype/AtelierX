"""Work and settings packages (#46, #47)."""

import io
import json
import zipfile

from starlette.testclient import TestClient

from atelierx.api.app import build_app
from atelierx.core.paths import REPO_ROOT, AppPaths
from conftest import FAST_KDF
from test_image import FakeComfy


def _other_app(tmp_path, password='other-pass-99'):
    root = tmp_path / 'other-app'
    paths = AppPaths(
        root=root, defaults=REPO_ROOT / 'defaults', samples=REPO_ROOT / 'samples', web=root / 'web'
    )
    client = TestClient(build_app(paths, kdf=FAST_KDF), base_url='http://127.0.0.1:8765')
    client.__enter__()
    assert client.post('/api/auth/setup', json={'password': password, 'language': 'ko'}).status_code == 200
    return client, paths


def _work_with_an_adopted_image(c):
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = FakeComfy()
    runtime.set_paused(True)
    c.post(
        f'/api/works/{wid}/image/jobs',
        json={
            'targets': [{'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}],
            'count': 2,
        },
    )
    for job in list(runtime.jobs):
        job['status'] = 'running'
        runtime.run_job(job)
    first = c.get('/api/image/gallery', params={'work': wid, 'sort': 'code'}).json()['results'][0]['path']
    c.post('/api/image/gallery/review', json={'verdict': 'pass', 'items': [{'path': first}]})
    return wid, first


def _upload(c, data):
    return c.post('/api/packages/upload', content=data, headers={'Content-Type': 'application/zip'})


def test_a_work_package_comes_back_under_a_new_id_with_its_adopted_image(unlocked, tmp_path):
    c = unlocked
    wid, adopted = _work_with_an_adopted_image(c)
    work = c.app.state.app.works.get(wid)
    c.post(f'/api/works/{wid}/snapshots', json={})
    plan = c.post('/api/packages/works/plan', json={'ids': [wid], 'options': {'images': 'adopted'}}).json()
    assert plan['works'][0]['images'] == 1 and plan['bytes'] > 0

    package = c.post('/api/packages/works/export', json={'ids': [wid], 'options': {'images': 'adopted'}})
    assert package.status_code == 200 and package.headers['content-type'] == 'application/zip'
    names = zipfile.ZipFile(io.BytesIO(package.content)).namelist()
    assert 'atelierx-package.json' in names and f'works/0/output/{adopted}' in names
    assert not any('/.atelierx/history/' in n for n in names)  # no history unless asked
    assert sum(n.startswith('works/0/output/') and n.endswith('.png') for n in names) == 1

    seen = _upload(c, package.content).json()
    assert seen['kind'] == 'works' and seen['works'][0]['id_taken'] and seen['works'][0]['name_taken']
    done = c.post('/api/packages/works/import', json={'token': seen['token'], 'works': [{'index': 0}]}).json()
    (imported,) = done['imported']
    assert imported['renumbered'] and imported['id'] != wid and imported['name'] == f'{work.name} (2)'
    new_id = imported['id']
    copied = adopted.replace(f'{wid}/', f'{new_id}/', 1)
    output = c.app.state.app.paths.output
    assert (output / copied).is_file()
    assert json.loads((output / copied).with_suffix('.json').read_text(encoding='utf-8'))['work_id'] == new_id
    board = c.get(f'/api/works/{new_id}/image/board').json()
    assert board['characters'][0]['cells']['o01/smile']['state'] == 'adopted'
    assert c.get(f'/api/works/{wid}/image/board').json()['adopted'] == 1  # the original is untouched
    # The token is used up.
    again = c.post('/api/packages/works/import', json={'token': seen['token'], 'works': [{'index': 0}]})
    assert again.status_code == 404


def test_a_work_package_keeps_its_id_in_another_app(unlocked, tmp_path):
    c = unlocked
    wid, adopted = _work_with_an_adopted_image(c)
    package = c.post(
        '/api/packages/works/export', json={'ids': [wid], 'options': {'images': 'all', 'history': True}}
    ).content
    other, other_paths = _other_app(tmp_path)
    try:
        seen = _upload(other, package).json()
        assert not seen['works'][0]['id_taken']
        done = other.post(
            '/api/packages/works/import', json={'token': seen['token'], 'works': [{'index': 0}]}
        ).json()
        assert done['imported'][0]['id'] == wid and not done['imported'][0]['renumbered']
        assert (other_paths.output / adopted).is_file()
        items = other.get(f'/api/works/{wid}/tree').json()
        assert items  # the work opens
        page = other.get('/api/image/gallery', params={'work': wid}).json()
        assert page['total'] == 2 and sum(i['adopted'] for i in page['results']) == 1
    finally:
        other.__exit__(None, None, None)


def test_a_package_cannot_write_outside_where_it_goes(unlocked):
    c = unlocked
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(
            'atelierx-package.json',
            json.dumps(
                {'format': 'atelierx-package', 'kind': 'works', 'works': [{'id': 'W009', 'name': 'x'}]}
            ),
        )
        archive.writestr('works/0/work/../../../evil.txt', 'x')
    assert _upload(c, buffer.getvalue()).status_code == 400
    assert _upload(c, b'not a zip').status_code == 400


def test_settings_travel_with_or_without_the_vault(unlocked, tmp_path):
    c = unlocked
    c.post(
        '/api/vault', json={'name': 'gemini', 'kind': 'llm_api_key', 'value': 'secret-value-123', 'note': ''}
    )
    personas = c.get('/api/personas').json()
    saved = c.put(
        '/api/personas',
        json={
            'base_revision': personas['revision'],
            'personas': [{'name': '도윤', 'description': '여러 줄\n설명'}],
        },
    )
    assert saved.status_code == 200, saved.text
    package = c.post(
        '/api/packages/settings/export', json={'areas': ['personas', 'providers', 'vault', 'nope']}
    )
    names = zipfile.ZipFile(io.BytesIO(package.content)).namelist()
    assert 'settings/personas/personas.json' in names and 'settings/vault/vault.json' in names

    other, other_paths = _other_app(tmp_path)
    try:
        mine = other.get('/api/personas').json()
        other.put(
            '/api/personas',
            json={'base_revision': mine['revision'], 'personas': [{'name': '원래', 'description': ''}]},
        )
        seen = _upload(other, package.content).json()
        assert {a['area'] for a in seen['areas']} == {'personas', 'providers', 'vault'}
        wrong = other.post(
            '/api/packages/settings/import',
            json={'token': seen['token'], 'areas': ['vault'], 'vault_password': 'nope'},
        )
        assert wrong.status_code == 401 and wrong.json()['error']['key'] == 'server.package.vault_password'
        done = other.post(
            '/api/packages/settings/import',
            json={'token': seen['token'], 'areas': ['personas', 'vault'], 'vault_password': 'pass1234'},
        ).json()
        assert set(done['applied']) == {'personas', 'vault'} and done['backup']
        assert [p['name'] for p in other.get('/api/personas').json()['personas']] == ['도윤']
        assert other.app.state.app.vault.reveal('gemini') == 'secret-value-123'
        assert (other_paths.state / 'packages' / 'backups' / done['backup']).is_file()
    finally:
        other.__exit__(None, None, None)
