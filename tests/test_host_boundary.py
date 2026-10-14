import pytest


@pytest.mark.parametrize(
    'host', ['external.invalid', 'localhost.external.invalid', '127.0.0.1.external.invalid']
)
def test_foreign_host_is_rejected_before_auth_or_static(client, host):
    headers = {'host': f'{host}:8765', 'origin': f'http://{host}:8765'}
    assert client.get('/api/auth/status', headers=headers).status_code == 400
    assert client.get('/preview.html', headers=headers).status_code == 400
    assert (
        client.post(
            '/api/auth/reset',
            headers=headers,
            json={
                'confirm': 'RESET',
                'password': 'synthetic-pass',
            },
        ).status_code
        == 400
    )
    assert not client.app.state.app.vault.initialized


@pytest.mark.parametrize('host', ['127.0.0.1:8765', 'localhost:8765', '[::1]:8765'])
def test_loopback_hosts_remain_available(client, host):
    assert (
        client.get(
            '/api/auth/status',
            headers={
                'host': host,
                'origin': f'http://{host}',
            },
        ).status_code
        == 200
    )


def test_foreign_origin_and_opaque_preview_cannot_call_api(client):
    for origin in ('http://external.invalid:8765', 'null'):
        assert client.get('/api/auth/status', headers={'origin': origin}).status_code == 403
