"""User settings in config/settings.json with defaults filled in."""

import copy

from .fsutil import read_json, write_json

THEMES = ('system', 'light', 'dark')

DEFAULTS = {
    'schema_version': 2,
    'language': 'ko',
    'theme': 'system',
    'autosave': {'enabled': True, 'delay_ms': 1000},
    'snapshot_interval_minutes': 10,
    'history_prune': {'keep_recent': 200, 'daily_days': 30},
    'jobs': {'api_concurrency': 2},
    'chat_runs_keep': 100,
    'default_platform_preset': None,
    # Ask GitHub for a newer release when the app starts (Help → Check for updates works either way).
    'update_check_on_start': False,
    'image': {},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Settings:
    def __init__(self, path):
        self.path = path

    def _read(self):
        settings = read_json(self.path, {})
        if settings.get('schema_version', 1) == 1:
            settings['schema_version'] = 2
        if settings.get('theme') not in THEMES:
            settings['theme'] = DEFAULTS['theme']
        return settings

    def load(self):
        return _merge(DEFAULTS, self._read())

    def update(self, changes):
        merged = _merge(self._read(), changes)
        write_json(self.path, merged)
        return _merge(DEFAULTS, merged)
