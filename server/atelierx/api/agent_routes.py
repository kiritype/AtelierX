"""Agent panel API (11-agent): modes, conversations, streaming answers, proposals → review, and the global guidelines."""

import asyncio
import json

from starlette.responses import JSONResponse, StreamingResponse

from ..core import agent, guidelines
from ..core.drafts import Drafts
from ..core.fsutil import sha256_text
from ..core.i18n import AppError, Msg, wire
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
    s, work = _state(request), _work(request)
    sessions = agent.Sessions(work)
    session = sessions.read(request.path_params['sid'])
    effective, linked = _linked(s, work)
    provider, model, _ = s.llm.resolve('agent', data.get('llm'))
    attachments = [a for a in data.get('attachments') or [] if isinstance(a, dict) and a.get('path')]
    for attachment in attachments:
        work.resolve(attachment['path'])  # an attachment never reaches outside the work
    messages, summary = agent.build(
        work,
        s.paths,
        effective,
        linked,
        session,
        str(data.get('message') or ''),
        attachments,
        agent.context_budget(provider, model),
    )
    return (
        s,
        work,
        sessions,
        session,
        messages,
        summary,
        attachments,
        {'provider': provider['id'], 'name': model},
    )


async def preview(request):
    data = await _body(request)
    *_, summary, _, _ = _prepare(request, data)
    return _ok(summary)


async def send(request):
    data = await _body(request)
    message = str(data.get('message') or '').strip()
    if not message:
        raise AppError(Msg('server.agent.empty', 'Write a message first.'), 400)
    s, work, sessions, session, messages, summary, attachments, model = _prepare(request, data)
    s.llm.require_consent(work, 'agent', data.get('llm'))
    sid = request.path_params['sid']
    sessions.append(sid, {'type': 'user', 'text': message, 'attachments': attachments})
    if not session['title']:
        sessions.append(sid, {'type': 'meta', 'title': message.splitlines()[0][:40]})
    turn = len(session['turns']) + 2  # the user turn just written is len + 1

    async def stream():
        parts, finish, error, saved = [], None, None, False

        def save():
            text = ''.join(parts)
            found = agent.proposals(work, text, summary.get('seen'))
            event = {
                'type': 'assistant',
                'text': text,
                'model': model,
                'finish_reason': finish,
                'context': summary,
                'proposals': [agent.public(p) for p in found],
            }
            if error:
                event['error'] = error
            sessions.append(sid, event)
            return event

        yield f'event: context\ndata: {json.dumps({**summary, "turn": turn}, ensure_ascii=False)}\n\n'
        try:
            async for event in s.llm.stream('agent', messages, work_id=work.id, override=data.get('llm')):
                if event['type'] == 'thinking':
                    yield f'event: thinking\ndata: {event["chars"]}\n\n'
                elif event['type'] == 'waiting':
                    yield f'event: waiting\ndata: {json.dumps(wire(event["holder"]), ensure_ascii=False)}\n\n'
                elif event['type'] == 'text':
                    parts.append(event['text'])
                    yield f'event: delta\ndata: {json.dumps(event["text"], ensure_ascii=False)}\n\n'
                elif event['type'] == 'done':
                    finish = event.get('finish_reason')
        except AppError as exc:
            error = exc.msg.as_dict()
            yield f'event: error\ndata: {json.dumps(error, ensure_ascii=False)}\n\n'
        except (asyncio.CancelledError, GeneratorExit):
            finish = 'stopped'  # the user pressed stop; keep what came so far
            save()
            saved = True
            raise
        finally:
            if not saved:
                saved_event = save()
                saved = True
                done = {'turn': turn, 'finish_reason': finish, 'proposals': saved_event['proposals']}
                yield f'event: end\ndata: {json.dumps(done, ensure_ascii=False)}\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream')


async def proposal_review(request):
    """Turn one proposal of an answer into a draft (kind ``agent_file``) for the review tab."""
    work = _work(request)
    sessions = agent.Sessions(work)
    sid = request.path_params['sid']
    session = sessions.read(sid)
    turn_no, n = int(request.path_params['turn']), int(request.path_params['n'])
    turn = next((t for t in session['turns'] if t['turn'] == turn_no and t['role'] == 'assistant'), None)
    if turn is None:
        raise AppError(Msg('server.agent.no_proposal', 'This proposal does not exist.'), 404)
    stored = next((p for p in turn.get('proposals', []) if p['n'] == n), None)
    drafts = Drafts(work)
    if stored and stored.get('draft_id'):
        try:
            if drafts.get(stored['draft_id'])['status'] == 'pending':
                return _ok({'draft_id': stored['draft_id']})
        except AppError:
            pass
    proposal = next(
        (
            p
            for p in agent.proposals(work, turn.get('text') or '', (turn.get('context') or {}).get('seen'))
            if p['n'] == n
        ),
        None,
    )
    if proposal is None:
        raise AppError(Msg('server.agent.no_proposal', 'This proposal does not exist.'), 404)
    if proposal['rejected']:
        raise AppError(
            Msg('server.agent.rejected', 'This proposal names a path that cannot be written.'), 400
        )
    if proposal['truncated']:
        raise AppError(
            Msg('server.agent.truncated', 'This proposal was cut off. Ask the agent to continue.'), 400
        )
    # The draft keeps the file as the model saw it (or, for older answers, as it was when the answer came); any edit
    # since then is caught here and again when adopting.
    base_hash = stored.get('base_hash') if stored else proposal['base_hash']
    current = (
        sha256_text(work.resolve(proposal['path']).read_text(encoding='utf-8'))
        if not proposal['new']
        else None
    )
    if not proposal['new'] and base_hash != current:
        raise AppError(
            Msg('server.agent.stale', 'The file changed after this answer. Ask again for a fresh proposal.'),
            409,
        )
    head, _ = agent._head(proposal['text'], '.' + proposal['path'].rsplit('.', 1)[-1])
    draft = drafts.create(
        'agent_file',
        {'path': proposal['path'], 'id': head.get('id'), 'base_hash': base_hash, 'new': proposal['new']},
        {
            'session': sid,
            'turn': turn_no,
            'n': n,
            'warnings': proposal['warnings'],
            # The file as the answer saw it; the review compares against it and adoption checks it is unchanged.
            'original': '' if proposal['new'] else work.resolve(proposal['path']).read_text(encoding='utf-8'),
        },
        [{'text': proposal['text']}],
        model=turn.get('model'),
    )
    sessions.append(sid, {'type': 'proposal', 'turn': turn_no, 'n': n, 'draft_id': draft['id']})
    return _ok({'draft_id': draft['id']})


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
