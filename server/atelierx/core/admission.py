"""Keep update shutdown and incoming work on the same admission boundary."""

import threading
from contextlib import contextmanager

from starlette.responses import JSONResponse

from .i18n import AppError, Msg


def busy_error(what):
    return AppError(Msg('server.update.busy', 'Finish or stop first: {what}.', what=what), 409)


class Admission:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.stopping = False

    @contextmanager
    def enter(self):
        with self.lock:
            if self.stopping:
                raise AppError(
                    Msg(
                        'server.update.restarting',
                        'The update is restarting the app. Try again after restart.',
                    ),
                    409,
                )
            self.active += 1
        try:
            yield
        finally:
            with self.lock:
                self.active -= 1

    @contextmanager
    def stop(self, busy):
        with self.lock:
            if self.stopping or self.active:
                raise AppError(
                    Msg(
                        'server.update.active_requests',
                        'Wait for active requests or the update restart to finish.',
                    ),
                    409,
                )
            pending = busy()
            if pending:
                raise busy_error(', '.join(str(value) for value in pending))
            self.stopping = True
        try:
            yield
        except BaseException:
            with self.lock:
                self.stopping = False
            raise


class AdmissionMiddleware:
    def __init__(self, app, admission):
        self.app, self.admission = app, admission

    async def __call__(self, scope, receive, send):
        # Hold admission through streaming responses too, including direct LLM calls.
        guarded = (
            scope['type'] == 'http'
            and scope['path'].startswith('/api/')
            and scope['path'] not in ('/api/update/apply', '/api/update/status', '/api/events')
        )
        if not guarded:
            return await self.app(scope, receive, send)
        try:
            with self.admission.enter():
                await self.app(scope, receive, send)
        except AppError as error:
            await JSONResponse({'error': error.msg.as_dict()}, status_code=error.status)(scope, receive, send)
