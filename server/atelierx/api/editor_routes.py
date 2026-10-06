"""API actions for editor content review, consistency review and Markdown formatting."""

from starlette.responses import JSONResponse

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


async def run_action(request):
    s = _state(request)
    return _ok(s.work_jobs.editor_action(_work(request), request.path_params['action'], await _body(request)))


async def apply_edit(request):
    data = await _body(request)
    work = _work(request)
    drafts = Drafts(work)
    draft_id = request.path_params['did']
    draft = drafts.get(draft_id)
    if draft['kind'] != 'text_edit' or draft.get('status') != 'pending':
        raise AppError(Msg('server.editor.not_editable', 'This draft is not a pending text edit.'), 409)
    index = data.get('candidate', 0)
    try:
        candidate = draft['candidates'][int(index)]
    except (ValueError, TypeError, IndexError):
        raise AppError(Msg('server.editor.bad_candidate', 'Choose a valid edit candidate.'), 400)
    target = draft['target']
    item = work.get_item(target['path'])
    if item['hash'] != target['base_hash']:
        raise AppError(Msg('server.editor.stale_edit', 'The item changed after this draft was created.'), 409)
    Snapshots(work).create('before_bulk', f'편집기 적용 전: {target["path"]}', force=True)
    saved = work.save_item(target['path'], {}, candidate['text'], target['base_hash'])
    drafts.set_status(draft_id, 'applied')
    return _ok({'path': saved['path'], 'hash': saved['hash']})
