"""API actions for editor content review, consistency review and Markdown formatting."""

from starlette.responses import JSONResponse

from ..core import editor_tasks, guidelines, llm_tasks
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


def _guideline(s, work, name):
    linked = s.presets.effective(work.doc())['linked']
    return guidelines.find(work, s.paths, linked, name)


def _item(work, path):
    item = work.get_item(path)
    if item['meta_error']:
        raise AppError(
            Msg('server.editor.invalid_metadata', 'Fix the item metadata before using this action.'), 400
        )
    if not path.lower().endswith('.md'):
        raise AppError(Msg('server.editor.markdown_only', 'This action supports Markdown content only.'), 400)
    return item


async def run_action(request):
    action = request.path_params['action']
    action = {'content_review': 'content-review'}.get(action, action)
    if action not in ('content-review', 'format', 'consistency'):
        raise AppError(Msg('server.editor.unknown_action', 'Unknown editor action.'), 404)
    data = await _body(request)
    work = _work(request)
    s = _state(request)
    task = 'compression' if action == 'format' else 'consistency'
    s.llm.require_consent(work, task, data.get('llm'))
    mode = data.get('mode', 'tidy')
    if action == 'format' and mode not in ('tidy', 'template'):
        raise AppError(Msg('server.editor.bad_format_mode', 'Format mode must be tidy or template.'), 400)
    guideline = _guideline(s, work, 'consistency.md' if task == 'consistency' else 'platform.md')
    instruction = str(data.get('instruction') or '')

    if action == 'consistency':
        paths = data.get('compare_paths')
        if not isinstance(paths, list) or len(paths) < 2 or any(not isinstance(p, str) for p in paths):
            raise AppError(
                Msg(
                    'server.editor.compare_paths_required', 'Choose at least two paths to compare explicitly.'
                ),
                400,
            )
        if len(set(paths)) != len(paths):
            raise AppError(
                Msg('server.editor.compare_paths_duplicate', 'Comparison paths must be unique.'), 400
            )
        items = [_item(work, path) for path in paths]
    else:
        item = _item(work, data.get('path', ''))
        items = [item]

    async def runner(progress):
        model = None
        provider, _, _ = s.llm.resolve(task, data.get('llm'))
        if provider.get('type') == 'mock':
            await progress(50)
            if action == 'format':
                result = {'text': items[0]['body'], 'note': '모의 형식 정리 결과'}
            else:
                result = {'issues': []}
        else:
            if action == 'content-review':
                messages = editor_tasks.review_messages(
                    items[0]['path'], items[0]['body'], guideline, instruction
                )
                check = editor_tasks.issues_ok
            elif action == 'consistency':
                messages = editor_tasks.consistency_messages(items, guideline, instruction)
                check = editor_tasks.issues_ok
            else:
                messages = editor_tasks.format_messages(
                    items[0]['path'],
                    items[0]['body'],
                    mode,
                    str(data.get('template') or ''),
                    str(data.get('instruction') or ''),
                    guideline,
                )
                check = editor_tasks.edit_ok
            result, answer = await llm_tasks.ask_json(
                s.llm, task, messages, work.id, check, override=data.get('llm')
            )
            model = {'provider': answer['provider'], 'name': answer['model']}

        if action == 'format' and not editor_tasks.preserves_protected(items[0]['body'], result['text']):
            raise AppError(
                Msg(
                    'server.editor.protected_syntax_changed',
                    'Formatting removed or changed a reserved placeholder or JSX tag.',
                ),
                422,
            )

        if action == 'content-review':
            target = {
                'scope': 'item',
                'id': items[0]['meta'].get('id'),
                'path': items[0]['path'],
                'base_hash': items[0]['hash'],
            }
            candidates = [
                {
                    'issues': [
                        {**issue, 'path': issue.get('path') or items[0]['path']} for issue in result['issues']
                    ]
                }
            ]
            draft_kind = 'content_review'
        elif action == 'consistency':
            target = {'scope': 'items', 'paths': paths, 'base_hashes': {i['path']: i['hash'] for i in items}}
            candidates = [{'issues': result['issues']}]
            draft_kind = 'content_review'
        else:
            target = {
                'scope': 'item',
                'id': items[0]['meta'].get('id'),
                'path': items[0]['path'],
                'base_hash': items[0]['hash'],
            }
            candidates = [{'text': result['text'], 'note': result.get('note', '')}]
            draft_kind = 'text_edit'
        draft = Drafts(work).create(
            draft_kind,
            target,
            {
                'action': action,
                'original': items[0]['body'] if action != 'consistency' else None,
                'compare_paths': paths if action == 'consistency' else None,
                'mode': data.get('mode'),
                'template': data.get('template'),
                'instruction': instruction,
            },
            candidates,
            model=model,
            guidelines=['consistency.md' if task == 'consistency' else 'platform.md'],
        )
        s.events.publish('draft', {'work': work.id, 'id': draft['id']})
        return {'draft': draft['id']}

    return _ok(
        s.jobs.submit(task, f'편집기 · {work.name}', runner, gpu=(action == 'format'), work_id=work.id)
    )


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
