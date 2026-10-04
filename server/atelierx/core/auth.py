"""Sessions issued after the vault is unlocked, plus the unlock back-off."""

import secrets
import time

COOKIE = 'atelierx_session'


class Sessions:
    def __init__(self):
        self._tokens = set()
        self._failures = 0
        self._next_try = 0.0

    def issue(self):
        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        self._failures = 0
        self._next_try = 0.0
        return token

    def valid(self, token):
        return bool(token) and token in self._tokens

    def clear(self):
        self._tokens.clear()

    def wait_seconds(self):
        return max(0.0, self._next_try - time.monotonic())

    def failed(self):
        self._failures += 1
        delay = min(30, 2 ** (self._failures - 3)) if self._failures > 3 else 0
        self._next_try = time.monotonic() + delay
