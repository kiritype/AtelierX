import pytest
from starlette.testclient import TestClient

from atelierx.api.app import build_app
from atelierx.core.paths import REPO_ROOT, AppPaths

FAST_KDF = {'name': 'scrypt', 'n': 2**10, 'r': 8, 'p': 1}


@pytest.fixture
def paths(tmp_path):
    return AppPaths(
        root=tmp_path, defaults=REPO_ROOT / 'defaults', samples=REPO_ROOT / 'samples', web=tmp_path / 'web'
    )


@pytest.fixture
def client(paths):
    app = build_app(paths, kdf=FAST_KDF)
    with TestClient(app, base_url='http://127.0.0.1:8765') as c:
        yield c


@pytest.fixture
def unlocked(client):
    assert client.post('/api/auth/setup', json={'password': 'pass1234', 'language': 'ko'}).status_code == 200
    # Never reach a real LLM server from tests.
    providers = client.get('/api/providers').json()
    providers['providers']['local'] = {'name': 'mock', 'type': 'mock', 'models': {}}
    client.put('/api/providers', json=providers)
    return client
