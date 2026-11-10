import pytest

from atelierx.core.fsutil import read_json, write_json


@pytest.mark.parametrize('version', [None, 1])
def test_legacy_settings_follow_system(paths, client, version):
    settings = {'language': 'en', 'autosave': {'enabled': False}}
    if version is not None:
        settings['schema_version'] = version
    write_json(paths.settings_file, settings)

    status = client.get('/api/auth/status').json()
    assert status['theme'] == 'system'
    assert status['language'] == 'en'
    assert read_json(paths.settings_file, {}) == settings

    assert client.post('/api/auth/setup', json={'password': 'pass1234', 'language': 'en'}).status_code == 200
    saved = read_json(paths.settings_file, {})
    assert saved == {**settings, 'theme': 'system', 'schema_version': 2}


@pytest.mark.parametrize('theme', ['light', 'dark', 'system'])
def test_saved_theme_is_available_before_unlock(paths, unlocked, theme):
    saved = unlocked.patch('/api/settings', json={'theme': theme})
    assert saved.status_code == 200
    assert saved.json()['theme'] == theme
    assert read_json(paths.settings_file, {})['theme'] == theme

    assert unlocked.post('/api/auth/lock').status_code == 200
    status = unlocked.get('/api/auth/status').json()
    assert status['unlocked'] is False
    assert status['theme'] == theme


def test_invalid_theme_keeps_saved_preference(unlocked):
    assert unlocked.patch('/api/settings', json={'theme': 'dark'}).status_code == 200

    invalid = unlocked.patch('/api/settings', json={'theme': ['light']})

    assert invalid.status_code == 400
    assert invalid.json()['error']['key'] == 'server.settings.invalid_theme'
    assert unlocked.get('/api/settings').json()['theme'] == 'dark'
