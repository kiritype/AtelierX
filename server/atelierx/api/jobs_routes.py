"""Background jobs, the activity list and the event stream."""

import asyncio

from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from .common import ok, st


async def jobs_list(request):
    s = st(request)
    return ok([s.jobs.public(j) for j in s.jobs.list()])


async def activity(request):
    """Unfinished work other than the LLM jobs, for the jobs panel (#89)."""
    return ok({'items': st(request).image.activity()})


async def jobs_cancel(request):
    return ok(st(request).jobs.cancel(request.path_params['jid']))


async def events(request: Request):
    s = st(request)
    queue = s.events.subscribe()

    async def stream():
        try:
            yield 'event: hello\ndata: {}\n\n'
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f'data: {message}\n\n'
                except TimeoutError:
                    yield ': ping\n\n'
                if await request.is_disconnected():
                    break
        finally:
            s.events.unsubscribe(queue)

    return StreamingResponse(stream(), media_type='text/event-stream')


def routes():
    return [
        Route('/api/jobs', jobs_list),
        Route('/api/activity', activity),
        Route('/api/jobs/{jid}/cancel', jobs_cancel, methods=['POST']),
        Route('/api/events', events),
    ]
