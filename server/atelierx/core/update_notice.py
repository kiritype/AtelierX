"""Small persistent state for startup update notices, separate from user preferences."""

import math
import threading

from .fsutil import read_json, write_json

DAY_MS = 24 * 60 * 60 * 1000


class UpdateNotices:
    def __init__(self, paths):
        self.path = paths.state / 'update' / 'notice.json'
        self.lock = threading.Lock()

    def _read(self):
        value = read_json(self.path, {})
        return value if isinstance(value, dict) else {}

    def begin(self, now):
        with self.lock:
            state = self._read()
            checked_at = state.get('checked_at', 0)
            valid_time = isinstance(checked_at, (int, float)) and math.isfinite(checked_at) and checked_at > 0
            should_check = not valid_time or now - checked_at >= DAY_MS
            if should_check:
                state['checked_at'] = now
                write_json(self.path, state)
            return {'should_check': should_check, 'available_version': state.get('available_version')}

    def record(self, result):
        with self.lock:
            state = self._read()
            latest = result.get('latest') if result.get('newer') else None
            state['available_version'] = latest
            if latest and latest != state.get('notified_version'):
                state['pending_notice'] = result
            elif latest:
                state.pop('pending_notice', None)
            elif not latest:
                state.pop('pending_notice', None)
            write_json(self.path, state)
            return {'available_version': latest}

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
