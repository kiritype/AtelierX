from starlette.testclient import TestClient

from atelierx.api.app import build_app
from atelierx.core import vault as vault_module
from atelierx.core.auth import Sessions

FAST_KDF = {'name': 'scrypt', 'n': 2**10, 'r': 8, 'p': 1}


def _client(paths):
    return TestClient(build_app(paths, kdf=FAST_KDF), base_url='http://127.0.0.1:8765')


def test_new_passwords_need_eight_characters(paths):
    with _client(paths) as c:
        short = c.post('/api/auth/setup', json={'password': 'abc1234'})
        assert short.status_code == 400 and short.json()['error']['key'] == 'server.vault.password_too_short'
        assert c.post('/api/auth/setup', json={'password': 'abcd1234'}).status_code == 200
        changed = c.post('/api/vault/password', json={'old': 'abcd1234', 'new': 'short'})
        assert changed.status_code == 400


def test_a_shorter_old_password_unlocks_and_is_suggested_to_change(paths, monkeypatch):
    monkeypatch.setattr(vault_module, 'MIN_PASSWORD', 4)
    with _client(paths) as c:
        c.post('/api/auth/setup', json={'password': 'abcd'})
    monkeypatch.setattr(vault_module, 'MIN_PASSWORD', 8)
    with _client(paths) as c:
        unlocked = c.post('/api/auth/unlock', json={'password': 'abcd'}).json()
        assert unlocked['password_change_suggested'] is True
        assert c.get('/api/auth/status').json()['password_change_suggested'] is True
        assert c.post('/api/vault/password', json={'old': 'abcd', 'new': 'longer-pass'}).status_code == 200
        assert c.get('/api/auth/status').json()['password_change_suggested'] is False


def test_the_unlock_back_off_survives_a_restart_and_grows(tmp_path):
    now = [1000.0]
    file = tmp_path / 'auth.json'
    sessions = Sessions(file, clock=lambda: now[0])
    for _ in range(3):
        sessions.failed()
    assert sessions.wait_seconds() == 0
    sessions.failed()
    assert sessions.wait_seconds() == 2
    assert Sessions(file, clock=lambda: now[0]).wait_seconds() == 2
    for _ in range(8):
        sessions.failed()
    # 12 failures: past 10 the wait may reach 5 minutes.
    assert 30 < sessions.wait_seconds() <= 300
    sessions.issue()
    assert Sessions(file, clock=lambda: now[0]).wait_seconds() == 0
