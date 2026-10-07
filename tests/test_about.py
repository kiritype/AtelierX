"""Help menu: version information and the update check (GitHub is faked, nothing leaves the machine)."""

import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from atelierx import __version__
from atelierx.api import about_routes
from atelierx.api.app import build_app
from atelierx.core import about
from atelierx.core.i18n import AppError
from conftest import FAST_KDF


def test_about_reports_a_development_run_without_a_manifest(unlocked):
    data = unlocked.get('/api/about').json()
    assert data['version'] == __version__
    assert data['packaged'] is False and data['commit'] is None
    assert data['notices'] is False
    assert unlocked.get('/api/about/notices').status_code == 404


def test_about_reads_the_build_manifest_and_notices(unlocked, paths):
    (paths.root / 'BUILD-MANIFEST.json').write_text(
        json.dumps({'version': __version__, 'built_at': '2026-10-05T01:02:03Z', 'commit': 'abc1234def'}),
        encoding='utf-8',
    )
    (paths.root / 'THIRD_PARTY_NOTICES.md').write_text('# notices\n', encoding='utf-8')
    data = unlocked.get('/api/about').json()
    assert data['packaged'] is True and data['commit'] == 'abc1234def'
    assert unlocked.get('/api/about/notices').text == '# notices\n'


def test_version_key_ignores_prereleases():
    assert about.version_key('v0.0.10') > about.version_key('0.0.9')
    assert about.version_key('v0.0.3-rc.1') is None


REAL_CLIENT = httpx.AsyncClient


def _fake(monkeypatch, handler):
    def client(**kwargs):
        return REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(about.httpx, 'AsyncClient', client)


def test_check_update_compares_the_latest_release(monkeypatch):
    _fake(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={'tag_name': 'v0.1.0', 'html_url': 'https://example.test/r', 'body': 'notes'}
        ),
    )
    result = asyncio.run(about.check_update(current='0.0.3'))
    assert (
        result['newer'] is True and result['url'] == 'https://example.test/r' and result['notes'] == 'notes'
    )
    assert asyncio.run(about.check_update(current='0.1.0'))['newer'] is False


def test_check_update_reports_failures(monkeypatch):
    _fake(monkeypatch, lambda request: httpx.Response(404))
    with pytest.raises(AppError) as failed:
        asyncio.run(about.check_update(current='0.0.3'))
    assert failed.value.msg.key == 'server.about.update_failed'

    def down(request):
        raise httpx.ConnectError('offline')

    _fake(monkeypatch, down)
    with pytest.raises(AppError) as unreachable:
        asyncio.run(about.check_update(current='0.0.3'))
    assert unreachable.value.msg.key == 'server.about.update_unreachable'


def test_only_the_desktop_window_opens_the_app_in_a_browser(unlocked, paths, monkeypatch):
    assert unlocked.get('/api/about').json()['desktop'] is False
    assert unlocked.post('/api/open-in-browser', json={}).status_code == 400

    opened = []
    monkeypatch.setattr(about_routes.webbrowser, 'open', opened.append)
    with TestClient(
        build_app(paths, kdf=FAST_KDF, desktop=True), base_url='http://127.0.0.1:8765'
    ) as desktop:
        assert desktop.post('/api/open-in-browser', json={}).status_code == 401
        assert desktop.post('/api/auth/unlock', json={'password': 'pass1234'}).status_code == 200
        assert desktop.get('/api/about').json()['desktop'] is True
        assert desktop.post('/api/open-in-browser', json={}).json()['url'] == 'http://127.0.0.1:8765/'
    assert opened == ['http://127.0.0.1:8765/']
