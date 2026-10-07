"""Sessions issued after the vault is unlocked, plus the unlock back-off (#82: kept across restarts)."""

import secrets
import time

from .fsutil import read_json, write_json

COOKIE = 'atelierx_session'
# From the 4th failed unlock on, wait 2, 4, 8 … seconds: up to 30 s, and up to 5 min after 10 failures.
FREE_TRIES = 3
SHORT_CAP, LONG_CAP, LONG_AFTER = 30, 300, 10


class Sessions:
    def __init__(self, state_file=None, clock=time.time):
        self._tokens = set()
        self._file = state_file
        self._clock = clock
        doc = (read_json(state_file) if state_file else None) or {}
        # The back-off survives a restart: restarting the app is not a way around it.
        self._failures = int(doc.get('failures') or 0)
        self._next_try = float(doc.get('next_try') or 0.0)

    def _save(self):
        if self._file:
            write_json(self._file, {'failures': self._failures, 'next_try': self._next_try})

    def issue(self):
        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        if self._failures or self._next_try:
            self._failures, self._next_try = 0, 0.0
            self._save()
        return token

    def valid(self, token):
        return bool(token) and token in self._tokens

    def clear(self):
        self._tokens.clear()

    def wait_seconds(self):
        return max(0.0, self._next_try - self._clock())

    def failed(self):
        self._failures += 1
        if self._failures <= FREE_TRIES:
            delay = 0
        else:
            cap = LONG_CAP if self._failures > LONG_AFTER else SHORT_CAP
            delay = min(cap, 2 ** (self._failures - FREE_TRIES))
        self._next_try = self._clock() + delay
        self._save()
