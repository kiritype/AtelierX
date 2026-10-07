"""Agent panel API (11-agent): modes, conversations, streaming answers, proposals → review, and the global guidelines."""

from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from ..core import agent, agent_turns, guidelines
from ..core.drafts import Drafts
from ..core.i18n import AppError, Msg
from ..core.snapshots import Snapshots


def _ok(value):
    return JSONResponse(value)


async def _body(request):
    return await request.json()


def _state(request):
    return request.app.state.app


def _work(request):
    return _state(request).works.get(request.path_params['wid'])


def _linked(s, work):
    effective = s.presets.effective(work.doc())
    return effective, effective['linked']


# --- modes and conversations -------------------------------------------------------------------------------------
async def modes(request):
    s, work = _state(request), _work(request)
    return _ok(agent.modes(work, s.paths, _linked(s, work)[1]))


async def sessions_list(request):
    return _ok(agent.Sessions(_work(request)).list())


async def sessions_create(request):
    data = await _body(request)
    return _ok(agent.Sessions(_work(request)).create(str(data.get('mode') or 'free'), data.get('scope')))


async def session_get(request):
    work = _work(request)
    doc = agent.Sessions(work).read(request.path_params['sid'])
    # What became of each proposal sent to review: pending, applied or discarded (its draft may be gone).
    drafts = Drafts(work)
    for turn in doc['turns']:
        for proposal in turn.get('proposals') or []:
            if proposal.get('draft_id'):
                try:
                    proposal['draft_status'] = drafts.get(proposal['draft_id'])['status']
                except AppError:
                    proposal['draft_status'] = None
    return _ok(doc)


async def session_patch(request):
    return _ok(agent.Sessions(_work(request)).update(request.path_params['sid'], await _body(request)))


async def session_delete(request):
    agent.Sessions(_work(request)).delete(request.path_params['sid'])
    return _ok({'ok': True})


def _prepare(request, data):
    s = _state(request)
    return agent_turns.prepare(_work(request), s.paths, s.llm, s.presets, request.path_params['sid'], data)


async def preview(request):
    return _ok(_prepare(request, await _body(request))['summary'])


async def send(request):
    data = await _body(request)
    s, sid = _state(request), request.path_params['sid']
    events = agent_turns.start(_work(request), s.llm, sid, data, _prepare(request, data))
    return StreamingResponse(events, media_type='text/event-stream')


async def proposal_review(request):
    p = request.path_params
    return _ok(agent_turns.review_proposal(_work(request), p['sid'], int(p['turn']), int(p['n'])))


async def draft_apply(request):
    """Write the hunks the user adopted (`text` is the whole resulting file) after a save point."""
    data = await _body(request)
    work = _work(request)
    drafts = Drafts(work)
    draft_id = request.path_params['did']
    draft = drafts.get(draft_id)
    if draft['kind'] != 'agent_file' or draft.get('status') != 'pending':
        raise AppError(Msg('server.drafts.not_pending', 'This draft has already been handled.'), 409)
    text = data.get('text')
    if not isinstance(text, str):
        raise AppError(Msg('server.agent.no_text', 'The adopted text is missing.'), 400)
    target = draft['target']
    Snapshots(work).create('before_llm', 'LLM 결과 채택 전', force=True)
    saved = work.write_whole(target['path'], text, target.get('base_hash'), new=bool(target.get('new')))
    drafts.set_status(draft_id, 'applied')
    return _ok({'path': saved['path'], 'hash': saved['hash']})


# --- Settings → 지침 -----------------------------------------------------------------------------------------------
async def guidelines_list(request):
    return _ok(
        {'items': guidelines.list_global(_state(request).paths), 'fixed': {'agent': agent.FIXED_RULES}}
    )


async def guideline_get(request):
    return _ok(guidelines.global_file(_state(request).paths, request.query_params.get('name')))


async def guideline_put(request):
    return _ok(
        guidelines.save_global(_state(request).paths, request.query_params.get('name'), await _body(request))
    )


async def guideline_delete(request):
    return _ok(guidelines.delete_global(_state(request).paths, request.query_params.get('name')))


def routes():
    w = '/api/works/{wid}'
    return [
        Route('/api/guidelines', guidelines_list),
        Route('/api/guidelines/file', guideline_get),
        Route('/api/guidelines/file', guideline_put, methods=['PUT']),
        Route('/api/guidelines/file', guideline_delete, methods=['DELETE']),
        Route(f'{w}/agent/modes', modes),
        Route(f'{w}/agent/sessions', sessions_list),
        Route(f'{w}/agent/sessions', sessions_create, methods=['POST']),
        Route(f'{w}/agent/sessions/{{sid}}', session_get),
        Route(f'{w}/agent/sessions/{{sid}}', session_patch, methods=['PATCH']),
        Route(f'{w}/agent/sessions/{{sid}}', session_delete, methods=['DELETE']),
        Route(f'{w}/agent/sessions/{{sid}}/preview', preview, methods=['POST']),
        Route(f'{w}/agent/sessions/{{sid}}/send', send, methods=['POST']),
        Route(
            f'{w}/agent/sessions/{{sid}}/proposals/{{turn:int}}/{{n:int}}/review',
            proposal_review,
            methods=['POST'],
        ),
        Route(f'{w}/agent-drafts/{{did}}/apply', draft_apply, methods=['POST']),
    ]
