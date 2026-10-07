"""The chat test and its test sets (#50)."""

import json

from starlette.responses import StreamingResponse
from starlette.routing import Route

from ..core import chat
from ..core.i18n import AppError, wire
from ..core.test_sets import TestSets
from .common import body, ok, st, work_of


async def chat_preview(request):
    data = await body(request)
    work = work_of(request)
    effective = st(request).presets.effective(work.doc())
    return ok(
        chat.assemble(work, effective, data.get('history', []), data.get('message', ''), data.get('persona'))
    )


async def chat_send(request):
    data = await body(request)
    work = work_of(request)
    st(request).llm.require_consent(work, 'chat_test', data.get('llm'))
    s = st(request)
    effective = s.presets.effective(work.doc())
    context = chat.assemble(work, effective, data.get('history', []), data['message'], data.get('persona'))
    messages = chat.messages(context, data.get('history', []), data['message'])

    async def stream():
        yield f'event: context\ndata: {json.dumps(context, ensure_ascii=False)}\n\n'
        try:
            async for event in s.llm.stream('chat_test', messages, work_id=work.id, override=data.get('llm')):
                if event['type'] == 'thinking':
                    yield f'event: thinking\ndata: {event["chars"]}\n\n'
                elif event['type'] == 'waiting':
                    yield f'event: waiting\ndata: {json.dumps(wire(event["holder"]), ensure_ascii=False)}\n\n'
                elif event['type'] == 'text':
                    yield f'event: delta\ndata: {json.dumps(event["text"], ensure_ascii=False)}\n\n'
        except AppError as error:
            yield f'event: error\ndata: {json.dumps(error.msg.as_dict(), ensure_ascii=False)}\n\n'
        yield 'event: end\ndata: {}\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream')


async def test_sets_get(request):
    return ok(TestSets(work_of(request)).load())


async def test_sets_put(request):
    return ok(TestSets(work_of(request)).save(await body(request)))


async def test_runs_list(request):
    return ok(TestSets(work_of(request)).list_runs(request.query_params.get('set')))


async def test_run_start(request):
    data = await body(request)
    s = st(request)
    work = work_of(request)
    provider, model, _ = s.llm.resolve('chat_test', data.get('llm'))
    found = {'provider': provider['id'], 'name': provider.get('name'), 'model': model or provider.get('type')}
    return ok(TestSets(work).start_run(str(data.get('set_id') or ''), found))


async def test_run_get(request):
    return ok(TestSets(work_of(request)).run(request.path_params['rid']))


async def test_run_put(request):
    return ok(TestSets(work_of(request)).record(request.path_params['rid'], await body(request)))


async def test_run_delete(request):
    return ok(TestSets(work_of(request)).delete_run(request.path_params['rid']))


def routes():
    w = '/api/works/{wid}'
    return [
        Route(f'{w}/chat/preview', chat_preview, methods=['POST']),
        Route(f'{w}/chat/send', chat_send, methods=['POST']),
        Route(f'{w}/tests/sets', test_sets_get),
        Route(f'{w}/tests/sets', test_sets_put, methods=['PUT']),
        Route(f'{w}/tests/runs', test_runs_list),
        Route(f'{w}/tests/runs', test_run_start, methods=['POST']),
        Route(f'{w}/tests/runs/{{rid}}', test_run_get),
        Route(f'{w}/tests/runs/{{rid}}', test_run_put, methods=['PUT']),
        Route(f'{w}/tests/runs/{{rid}}', test_run_delete, methods=['DELETE']),
    ]
