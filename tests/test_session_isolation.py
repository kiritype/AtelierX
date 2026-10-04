from starlette.testclient import TestClient

from atelierx.api.app import build_app
from atelierx.core.paths import AppPaths
from conftest import FAST_KDF


def test_two_portable_roots_do_not_overwrite_each_others_cookie(tmp_path):
    first = build_app(AppPaths.for_dev(tmp_path / 'a'), kdf=FAST_KDF)
    second = build_app(AppPaths.for_dev(tmp_path / 'b'), kdf=FAST_KDF)
    with TestClient(first) as a, TestClient(second) as b:
        a.post('/api/auth/setup', json={'password': 'demo'})
        b.cookies.update(a.cookies)
        b.post('/api/auth/setup', json={'password': 'demo'})
        a.cookies.update(b.cookies)
        assert a.get('/api/auth/status').json()['unlocked']
        assert b.get('/api/auth/status').json()['unlocked']
        b.post('/api/auth/lock')
        assert a.get('/api/auth/status').json()['unlocked']
        assert first.state.app.cookie_name != second.state.app.cookie_name
