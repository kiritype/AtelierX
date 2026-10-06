"""One agent turn (11-agent) without the HTTP around it (#90): what the next message would send, the streamed
answer as server-sent events (kept in the conversation even when stopped), and a proposal turned into a draft."""

import asyncio
import json

from . import agent
from .drafts import Drafts
from .fsutil import sha256_text
from .i18n import AppError, Msg, wire


def prepare(work, paths, llm, presets, sid, data):
    """The conversation and what the next message (``data``) would send: messages, summary, attachments, model."""
    sessions = agent.Sessions(work)
    session = sessions.read(sid)
    effective = presets.effective(work.doc())
    provider, model, _ = llm.resolve('agent', data.get('llm'))
    attachments = [a for a in data.get('attachments') or [] if isinstance(a, dict) and a.get('path')]
    for attachment in attachments:
        work.resolve(attachment['path'])  # an attachment never reaches outside the work
    messages, summary = agent.build(
        work,
        paths,
        effective,
        effective['linked'],
        session,
        str(data.get('message') or ''),
        attachments,
        agent.context_budget(provider, model, llm.doc().get('context_cap')),
    )
    return {
        'sessions': sessions,
        'session': session,
        'messages': messages,
        'summary': summary,
        'attachments': attachments,
        'model': {'provider': provider['id'], 'name': model},
    }


def start(work, llm, sid, data, prepared):
    """Write the user's message to the conversation; returns the events of the answer to stream."""
    message = str(data.get('message') or '').strip()
    if not message:
        raise AppError(Msg('server.agent.empty', 'Write a message first.'), 400)
    llm.require_consent(work, 'agent', data.get('llm'))
    sessions, session = prepared['sessions'], prepared['session']
    sessions.append(sid, {'type': 'user', 'text': message, 'attachments': prepared['attachments']})
    if not session['title']:
        sessions.append(sid, {'type': 'meta', 'title': message.splitlines()[0][:40]})
    turn = len(session['turns']) + 2  # the user turn just written is len + 1
    return _stream(work, llm, sid, data, prepared, turn)


async def _stream(work, llm, sid, data, prepared, turn):
    sessions, messages, summary, model = (
        prepared['sessions'],
        prepared['messages'],
        prepared['summary'],
        prepared['model'],
    )
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
        async for event in llm.stream('agent', messages, work_id=work.id, override=data.get('llm')):
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


def review_proposal(work, sid, turn_no, n):
    """Turn one proposal of an answer into a draft (kind ``agent_file``) for the review tab."""
    sessions = agent.Sessions(work)
    session = sessions.read(sid)
    turn = next((t for t in session['turns'] if t['turn'] == turn_no and t['role'] == 'assistant'), None)
    if turn is None:
        raise AppError(Msg('server.agent.no_proposal', 'This proposal does not exist.'), 404)
    stored = next((p for p in turn.get('proposals', []) if p['n'] == n), None)
    drafts = Drafts(work)
    if stored and stored.get('draft_id'):
        try:
            if drafts.get(stored['draft_id'])['status'] == 'pending':
                return {'draft_id': stored['draft_id']}
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
    if 'deleted_since' in proposal['warnings']:
        raise AppError(
            Msg(
                'server.agent.deleted',
                'The file was deleted or moved after the request. Ask again if it should come back.',
            ),
            409,
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
    return {'draft_id': draft['id']}
