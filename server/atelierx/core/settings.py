"""User settings in config/settings.json with defaults filled in."""

import copy

from .fsutil import read_json, write_json

DEFAULTS = {
    'schema_version': 1,
    'language': 'ko',
    'autosave': {'enabled': True, 'delay_ms': 1000},
    'autolock_minutes': None,
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

    def load(self):
        return _merge(DEFAULTS, read_json(self.path, {}))

    def update(self, changes):
        current = read_json(self.path, {})
        merged = _merge(current, changes)
        write_json(self.path, merged)
        return _merge(DEFAULTS, merged)
