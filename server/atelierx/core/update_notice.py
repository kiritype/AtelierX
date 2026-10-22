"""Small persistent state for startup update notices, separate from user preferences."""

import asyncio
import threading
import time

from .. import __version__
from . import about
from .fsutil import read_json, write_json
from .i18n import AppError, Msg

DAY_MS = 24 * 60 * 60 * 1000
RETRIES = (5 * 60_000, 30 * 60_000, 2 * 60 * 60_000)


class UpdateNotices:
    def __init__(self, paths):
        self.path = paths.state / 'update' / 'notice.json'
        self.lock = threading.Lock()
        self.inflight = None
        self.clock = lambda: int(time.time() * 1000)
        self.started = False

    def _read(self):
        value = read_json(self.path, {})
        return {**value, 'schema_version': 2} if isinstance(value, dict) else {'schema_version': 2}

    def begin(self, now, current_version):
        with self.lock:
            state = self._read()
            if state.get('checked_version') != current_version:
                state['checked_version'] = current_version
                state['checked_at'] = 0
                state['last_success'] = None
                state['available_version'] = None
                state.pop('pending_notice', None)
            checked_at = state.get('last_success', 0)
            should_check = not checked_at or now < checked_at or now - checked_at >= DAY_MS
            if should_check:
                state['last_attempt'] = now
                write_json(self.path, state)
            return {
                'should_check': should_check,
                'available_version': state.get('available_version'),
                'current_version': current_version,
            }

    def record(self, result, now=None):
        with self.lock:
            state = self._read()
            state.setdefault('checked_version', result['current'])
            state.update(
                last_success=now if now is not None else state.get('last_attempt', self.clock()),
                status='latest',
                retries=0,
                next_retry=None,
                error=None,
                retryable=False,
                result=result,
            )
            latest = result.get('latest') if result.get('newer') else None
            state['available_version'] = latest
            if latest:
                state['status'] = 'available'
            if latest and latest != state.get('notified_version'):
                state['pending_notice'] = result
            else:
                state.pop('pending_notice', None)
            write_json(self.path, state)
            return {'available_version': latest}

    def status(self, enabled=False):
        with self.lock:
            state = self._read()
        return {
            **state,
            'status': 'checking' if self.inflight else state.get('status', 'unchecked'),
            'enabled': enabled,
            'next_retry': state.get('next_retry') if enabled else None,
        }

    async def check(self, *, manual=False, startup=False):
        # One server-owned task for all browser windows and automatic/manual callers.
        if self.inflight:
            return await asyncio.shield(self.inflight)
        now = self.clock()
        with self.lock:
            state = self._read()
            if state.get('checked_version') != __version__:
                state.update(
                    checked_version=__version__,
                    last_success=None,
                    available_version=None,
                    result=None,
                    status='unchecked',
                )
            if now < state.get('server_not_before', 0):
                return self._blocked(state)
            if not manual:
                if state.get('next_retry'):
                    if now < state['next_retry']:
                        return None
                elif (
                    not startup
                    or state.get('last_success')
                    and 0 <= now - state['last_success'] < DAY_MS
                    or (
                        state.get('last_attempt')
                        and state.get('error')
                        and now - state['last_attempt'] < DAY_MS
                    )
                ):
                    return None
                else:
                    state['retries'] = 0
                if state.get('next_retry'):
                    state['retries'] = state.get('retries', 0) + 1
                    state['next_retry'] = None
            state['last_attempt'] = now
            write_json(self.path, state)
        self.inflight = asyncio.create_task(self._request())
        try:
            return await asyncio.shield(self.inflight)
        finally:
            # Cancellation of an HTTP caller must not cancel or release the shared task.
            if self.inflight and self.inflight.done():
                self.inflight = None

    def _blocked(self, state):
        raise AppError(
            Msg('server.about.update_wait', 'Wait until the server allows another update check.'), 429
        )

    async def _request(self):
        try:
            result = await about.check_update()
            self.record(result, self.clock())
            return result
        except AppError as exc:
            with self.lock:
                state = self._read()
                now = self.clock()
                retryable = getattr(exc, 'retryable', False)
                server_time = getattr(exc, 'retry_at', 0)
                state.update(
                    status='failed',
                    error=exc.msg.as_dict(),
                    retryable=retryable,
                    server_not_before=max(state.get('server_not_before', 0), server_time),
                )
                retries = state.get('retries', 0)
                if retryable and retries < len(RETRIES):
                    # Manual failures cannot reset or shorten an existing automatic budget.
                    state['next_retry'] = max(
                        now + RETRIES[retries], server_time, state.get('next_retry') or 0
                    )
                else:
                    state['next_retry'] = None
                write_json(self.path, state)
            raise
        finally:
            self.inflight = None

    async def run(self, enabled):
        previous = False
        try:
            while True:
                on = bool(enabled())
                startup = on and not previous and not self.started
                if on:
                    self.started = True
                    try:
                        await self.check(startup=startup)
                    except AppError:
                        pass
                previous = on
                await asyncio.sleep(1)
        finally:
            if self.inflight:
                self.inflight.cancel()

    def consume(self):
        with self.lock:
            state = self._read()
            result = state.pop('pending_notice', None)
            if result and result.get('latest') != state.get('notified_version'):
                state['notified_version'] = result['latest']
                write_json(self.path, state)
                return result
            if result:
                write_json(self.path, state)
            return None

    def claim_result(self, key):
        with self.lock:
            state = self._read()
            if state.get('reported_result') == key:
                return False
            state['reported_result'] = key
            write_json(self.path, state)
            return True
