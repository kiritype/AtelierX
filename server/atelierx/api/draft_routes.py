"""Drafts and the LLM jobs that make them: compression, authoring, relation extraction, consistency, JSX prompt text."""

from starlette.routing import Route

from ..core import authoring, guidelines, review
from ..core import draft_apply as draft_apply_module
from ..core.drafts import Drafts
from ..core.i18n import AppError, Msg
from ..core.snapshots import Snapshots
from . import editor_routes
from .common import body, ok, st, work_of


async def drafts_list(request):
    return ok(Drafts(work_of(request)).list(request.query_params.get('status')))


async def draft_get(request):
    return ok(Drafts(work_of(request)).get(request.path_params['did']))


async def draft_composition(request):
    drafts = Drafts(work_of(request))
    doc = drafts.get(request.path_params['did'])
    doc['composition'] = await body(request)
    drafts.save(request.path_params['did'], doc)
    return ok()


async def draft_apply(request):
    work = work_of(request)
    if Drafts(work).get(request.path_params['did'])['kind'] == 'text_edit':
        return await editor_routes.apply_edit(request)
    return ok(draft_apply_module.apply(work, request.path_params['did'], await body(request)))


async def draft_discard(request):
    return ok(Drafts(work_of(request)).set_status(request.path_params['did'], 'discarded'))


def work_guideline(s, work, name):
    return guidelines.find(work, s.paths, s.presets.effective(work.doc())['linked'], name)


def item_by_id(work, item_id, kind=None):
    item = next(
        (i for i in work.index() if i['meta'].get('id') == item_id and (kind is None or i['kind'] == kind)),
        None,
    )
    if item is None:
        raise AppError(Msg('server.works.item_missing', 'The file does not exist: {path}', path=item_id), 404)
    return work.get_item(item['path'])


async def relations_extract(request):
    return ok(st(request).work_jobs.relations(work_of(request), await body(request)))


async def consistency_run(request):
    return ok(st(request).work_jobs.consistency(work_of(request), await body(request)))


async def draft_issue(request):
    data = await body(request)
    work = work_of(request)
    drafts = Drafts(work)
    doc = drafts.get(request.path_params['did'])
    n = int(request.path_params['n'])
    issue = doc['candidates'][0]['issues'][n]
    if data.get('action') == 'apply':
        Snapshots(work).create('before_llm', 'LLM 제안 적용 전', force=True)
    result = review.issue_action(work, issue, data.get('action'), data.get('note', ''))
    issue['status'] = result['status']
    if data.get('note'):
        issue['note'] = data['note']
    drafts.save(doc['id'], doc)
    return ok({**result, 'issue': issue})


async def jsx_prompt_text(request):
    work = work_of(request)
    item = item_by_id(work, request.path_params['jid'], 'jsx')
    return ok(st(request).work_jobs.jsx_prompt(work, item, await body(request)))


async def jsx_usages(request):
    work = work_of(request)
    item = item_by_id(work, request.path_params['jid'], 'jsx')
    return ok(
        review.usages(work, item['name'], review.response_rule(st(request).presets.effective(work.doc())))
    )


async def jsx_elements(request):
    """Calls of one component in a text (draft review), read with the work's response rule."""
    data = await body(request)
    work = work_of(request)
    rule = review.response_rule(st(request).presets.effective(work.doc()))
    return ok(review.elements(data.get('text', ''), data.get('name', ''), rule))


def _authoring_scale(work, requested):
    scale = requested or work.doc().get('scale')
    return scale if scale in authoring.SCALES else 'single'


async def authoring_questions(request):
    work = work_of(request)
    s = st(request)
    scale = _authoring_scale(work, request.query_params.get('scale'))
    name = f'authoring/{scale}.md'
    text = work_guideline(s, work, name)
    return ok({'scale': scale, 'guideline': name, 'questions': authoring.questions(text)})


async def authoring_run(request):
    data = await body(request)
    work = work_of(request)
    return ok(st(request).work_jobs.authoring(work, data, _authoring_scale(work, data.get('scale'))))


async def compress(request):
    return ok(st(request).work_jobs.compression(work_of(request), await body(request)))


def routes():
    w = '/api/works/{wid}'
    return [
        Route(f'{w}/drafts', drafts_list),
        Route(f'{w}/drafts/{{did}}', draft_get),
        Route(f'{w}/drafts/{{did}}/composition', draft_composition, methods=['PUT']),
        Route(f'{w}/drafts/{{did}}/apply', draft_apply, methods=['POST']),
        Route(f'{w}/drafts/{{did}}/discard', draft_discard, methods=['POST']),
        Route(f'{w}/compress', compress, methods=['POST']),
        Route(f'{w}/authoring/questions', authoring_questions),
        Route(f'{w}/authoring', authoring_run, methods=['POST']),
        Route(f'{w}/relations/extract', relations_extract, methods=['POST']),
        Route(f'{w}/consistency', consistency_run, methods=['POST']),
        Route(f'{w}/drafts/{{did}}/issues/{{n}}', draft_issue, methods=['POST']),
        Route(f'{w}/jsx/{{jid}}/prompt-text', jsx_prompt_text, methods=['POST']),
        Route(f'{w}/jsx/{{jid}}/usages', jsx_usages),
        Route(f'{w}/jsx/elements', jsx_elements, methods=['POST']),
    ]
