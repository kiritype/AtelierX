"""HTTP API (Starlette). Every route except /api/auth/* needs a session (architecture: 인증과 세션)."""

import asyncio
import contextlib
import csv
import io
import json
import webbrowser
from datetime import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..core import about, authoring, chat, checks, exporter, guidelines, llm_tasks, personas, rename, review
from ..core.auth import COOKIE, Sessions
from ..core.bootstrap import ensure_layout
from ..core.drafts import Drafts, mock_compress
from ..core.events import Events
from ..core.fsutil import read_json, sha256_text, write_json
from ..core.i18n import AppError, Msg, wire
from ..core.jobs import Jobs
from ..core.jsx import Props, call_text
from ..core.llm import LlmGate, Providers
from ..core.presets import Presets
from ..core.relations import Glossary, Relations
from ..core.settings import Settings
from ..core.snapshots import Snapshots
from ..core.vault import Vault
from ..core.works import KIND_PREFIX, WorkStore
from ..image import designs as image_designs
from ..image.runtime import ImageRuntime
from . import agent_routes, editor_routes, image_routes, lora_routes, tool_routes


class State:
    def __init__(self, paths, dev=False, kdf=None, desktop=False):
        self.paths = paths
        # The desktop window (pywebview) can hand the same address to the system browser.
        self.desktop = desktop
        self.cookie_name = COOKIE + '_' + sha256_text(str(paths.root.resolve()).casefold())[:12]
        self.dev = dev
        ensure_layout(paths)
        self.vault = Vault(paths.vault_file, kdf=kdf)
        self.sessions = Sessions()
        self.settings = Settings(paths.settings_file)
        self.works = WorkStore(paths)
        self.presets = Presets(paths)
        self.events = Events()
        self.jobs = Jobs(self.events)
        self.llm = Providers(paths, self.vault)
        self.image = ImageRuntime(paths, self.works, self.llm)
        self.llm.gate = LlmGate(
            self.image.gpu, lambda: (self.settings.load().get('jobs') or {}).get('api_concurrency', 2)
        )
        self.maintain()

    def maintain(self):
        """Once a day at start: prune old save snapshots in every work (09-snapshots: 정리)."""
        marker = self.paths.state / 'maintenance.json'
        today = datetime.now().astimezone().strftime('%Y-%m-%d')
        if (read_json(marker) or {}).get('pruned') == today:
            return
        rule = self.settings.load().get('history_prune') or {}
        for work in self.works.all():
            Snapshots(work).prune(rule.get('keep_recent', 200), rule.get('daily_days', 30))
        write_json(marker, {'pruned': today})


def ok(value=None, status=200):
    return JSONResponse(wire(value) if value is not None else {'ok': True}, status_code=status)


async def body(request):
    raw = await request.body()
    return json.loads(raw) if raw else {}


def st(request) -> State:
    return request.app.state.app


# --- middleware ------------------------------------------------------------------------------------------------
class Guard(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith('/api/'):
            if _unsafe_api_path(request.scope['path']):
                return JSONResponse(
                    {'error': Msg('server.works.bad_path', 'This path is not allowed.').as_dict()},
                    status_code=400,
                )
            origin = request.headers.get('origin')
            if origin and not _origin_ok(origin, request, st(request).dev):
                return JSONResponse(
                    {'error': Msg('server.auth.bad_origin', 'Request from another site.').as_dict()},
                    status_code=403,
                )
            if not path.startswith('/api/auth/') and not st(request).sessions.valid(
                request.cookies.get(st(request).cookie_name)
            ):
                return JSONResponse(
                    {'error': Msg('server.auth.required', 'Unlock the app first.').as_dict()}, status_code=401
                )
        try:
            response = await call_next(request)
            if path.startswith('/api/') and 'cache-control' not in response.headers:
                # API answers change with every edit; a cached one would show stale data.
                response.headers['Cache-Control'] = 'no-store'
            if path.startswith('/assets/'):
                # Bundled files only. The preview frame has an opaque origin and loads them as CORS module scripts.
                response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        except AppError as error:
            return JSONResponse({'error': error.msg.as_dict()}, status_code=error.status)


def _unsafe_api_path(path):
    """IDs and names in API URLs become file names (trash bundles, drafts, examples …). None of them needs a backslash,
    a colon or a dot segment, and on Windows each of those can step out of the folder the ID belongs to."""
    # A part made only of dots and spaces ('..', '...', '. ') is the current or parent folder to Windows.
    return any(c in path for c in '\\:\x00') or any(part and not part.strip('. ') for part in path.split('/'))


def _origin_ok(origin, request, dev):
    host = request.headers.get('host', '')
    allowed = {f'http://{host}'}
    if dev:
        allowed |= {'http://localhost:5173', 'http://127.0.0.1:5173'}
    return origin in allowed


async def handle_app_error(request, error):
    return JSONResponse({'error': error.msg.as_dict()}, status_code=error.status)


# --- auth ------------------------------------------------------------------------------------------------------
def _session_response(request, value):
    response = ok(value)
    response.set_cookie(
        st(request).cookie_name, st(request).sessions.issue(), httponly=True, samesite='strict'
    )
    return response


async def auth_status(request):
    s = st(request)
    return ok(
        {
            'initialized': s.vault.initialized,
            'unlocked': s.sessions.valid(request.cookies.get(st(request).cookie_name)),
            'language': s.settings.load()['language'],
            'wait': round(s.sessions.wait_seconds()),
        }
    )


async def auth_setup(request):
    data = await body(request)
    s = st(request)
    s.vault.setup(data.get('password', ''))
    s.settings.update({'language': data.get('language', 'ko')})
    return _session_response(request, {'ok': True})


async def auth_unlock(request):
    s = st(request)
    if s.sessions.wait_seconds() > 0:
        raise AppError(
            Msg('server.auth.wait', 'Try again in {n} seconds.', n=round(s.sessions.wait_seconds())), 429
        )
    data = await body(request)
    try:
        await asyncio.to_thread(s.vault.unlock, data.get('password', ''))
    except AppError:
        s.sessions.failed()
        raise
    return _session_response(request, {'ok': True})


async def auth_lock(request):
    s = st(request)
    s.vault.lock()
    s.sessions.clear()
    s.events.publish('lock')
    response = ok()
    response.delete_cookie(st(request).cookie_name)
    return response


async def auth_reset(request):
    data = await body(request)
    if data.get('confirm') != 'RESET':
        raise AppError(Msg('server.auth.reset_confirm', 'Type RESET to confirm.'))
    s = st(request)
    s.vault.reset(data.get('password', ''))
    s.sessions.clear()
    return _session_response(request, {'ok': True})


# --- about, update check (Help menu) ------------------------------------------------------------------------
async def about_get(request):
    return ok({**about.info(st(request).paths), 'desktop': st(request).desktop})


async def open_in_browser(request):
    if not st(request).desktop:
        raise AppError(
            Msg('server.about.not_desktop', 'Only the desktop window can open the app in a browser.'), 400
        )
    webbrowser.open(str(request.base_url))
    return ok({'url': str(request.base_url)})


async def about_notices(request):
    return Response(about.notices(st(request).paths), media_type='text/plain; charset=utf-8')


async def update_check(request):
    return ok(await about.check_update())


# --- settings, ui state, vault, providers, presets ---------------------------------------------------------------
async def settings_get(request):
    return ok(st(request).settings.load())


async def settings_patch(request):
    return ok(st(request).settings.update(await body(request)))


async def compression_guideline_get(request):
    return ok(guidelines.compression_settings(st(request).paths))


async def compression_guideline_put(request):
    return ok(guidelines.save_compression_settings(st(request).paths, await body(request)))


async def personas_get(request):
    return ok(personas.load(st(request).paths))


async def personas_put(request):
    return ok(personas.save(st(request).paths, await body(request)))


async def ui_state_get(request):
    return ok(read_json(st(request).paths.state / 'ui.json', {}))


async def ui_state_put(request):
    write_json(st(request).paths.state / 'ui.json', await body(request))
    return ok()


async def vault_list(request):
    return ok(st(request).vault.list())


async def vault_put(request):
    data = await body(request)
    st(request).vault.put(data['name'], data.get('kind', 'other'), data['value'], data.get('note', ''))
    return ok()


async def vault_delete(request):
    st(request).vault.delete(request.path_params['name'])
    return ok()


async def vault_password(request):
    data = await body(request)
    await asyncio.to_thread(st(request).vault.change_password, data.get('old', ''), data.get('new', ''))
    return ok()


async def providers_get(request):
    return ok(st(request).llm.doc())


async def providers_put(request):
    return ok(st(request).llm.save(await body(request)))


def _usage_month(request):
    return request.query_params.get('month') or datetime.now().astimezone().strftime('%Y-%m')


async def usage(request):
    month = _usage_month(request)
    llm = st(request).llm
    return ok(
        {
            'month': month,
            'months': llm.usage_months(),
            'tasks': llm.usage_tasks(month),
            'rows': llm.usage(month, request.query_params.get('by', 'model')),
        }
    )


async def usage_log(request):
    q = request.query_params
    return ok(
        st(request).llm.usage_log(
            _usage_month(request),
            q.get('offset', 0),
            q.get('limit', 50),
            q.get('work') or None,
            q.get('task') or None,
        )
    )


async def usage_csv(request):
    """The month's requests as CSV (UTF-8 with BOM so spreadsheet programs read Korean names)."""
    month = _usage_month(request)
    out = io.StringIO()
    fields = ['at', 'provider', 'model', 'task', 'work', 'input_tokens', 'output_tokens']
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for entry in st(request).llm.usage_entries(month):
        writer.writerow(entry)
    return Response(
        '\ufeff' + out.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="atelierx-usage-{month}.csv"'},
    )


async def providers_models(request):
    return ok({'models': await st(request).llm.models(request.path_params['pid'])})


async def providers_probe(request):
    return ok(await st(request).llm.probe(request.path_params['pid']))


def mocked(s, task, override=None):
    """Whether this task's connection is the built-in mock (tests, offline checks)."""
    provider, _, _ = s.llm.resolve(task, override)
    return provider.get('type') == 'mock'


def work_guideline(s, work, name):
    return guidelines.find(work, s.paths, s.presets.effective(work.doc())['linked'], name)


async def presets_list(request):
    return ok(st(request).presets.list())


async def presets_create(request):
    data = await body(request)
    return ok(
        st(request).presets.create(data['id'], data.get('name', data['id']), data.get('base', 'generic'))
    )


async def presets_get(request):
    return ok(st(request).presets.get(request.path_params['pid']))


async def presets_put(request):
    return ok(st(request).presets.save(request.path_params['pid'], await body(request)))


async def presets_delete(request):
    s = st(request)
    return ok(s.presets.delete(request.path_params['pid'], s.works.all(), s.settings.load()))


# --- works -----------------------------------------------------------------------------------------------------
def work_of(request):
    return st(request).works.get(request.path_params['wid'])


async def works_list(request):
    s = st(request)
    return ok({'works': [s.works.card(w) for w in s.works.all()], 'suggest_id': s.works.suggest_id()})


async def works_create(request):
    data = await body(request)
    s = st(request)
    tags = data.get('tags')
    if tags is None:
        default = s.settings.load().get('default_platform_preset')
        tags = [default] if default else []
    work = s.works.create(
        data['name'], data.get('id') or None, tags, data.get('scale', 'single'), data.get('language', 'ko')
    )
    return ok(s.works.card(work), 201)


async def works_patch(request):
    data = await body(request)
    s = st(request)
    work = work_of(request)
    if 'name' in data and data['name'] != work.name:
        work = s.works.rename(work.id, data['name'])
    fields = {
        k: v
        for k, v in data.items()
        if k
        in ('tags', 'scale', 'language', 'overrides', 'character_sections', 'char', 'order', 'llm_consent')
    }
    if fields:
        work.update_doc(fields)
    return ok(s.works.card(work))


async def works_delete(request):
    return ok(st(request).works.delete(request.path_params['wid']))


async def works_duplicate(request):
    data = await body(request)
    s = st(request)
    return ok(
        s.works.card(s.works.duplicate(request.path_params['wid'], data['name'], data.get('id') or None))
    )


async def samples_list(request):
    return ok(st(request).works.samples())


async def samples_install(request):
    s = st(request)
    work = s.works.install_sample(request.path_params['name'])
    Snapshots(work).create('import', '샘플 설치')
    return ok(s.works.card(work), 201)


async def data_trash_list(request):
    return ok(st(request).works.trash())


async def data_trash_restore(request):
    return ok(st(request).works.restore(request.path_params['bid']))


async def data_trash_purge(request):
    st(request).works.purge(request.path_params.get('bid'))
    return ok()


async def work_get(request):
    s = st(request)
    work = work_of(request)
    doc = work.doc()
    return ok(
        {
            'name': work.name,
            'doc': doc,
            'effective': s.presets.effective(doc),
            'sections': work.section_titles(),
            'presets': s.presets.list(),
        }
    )


async def work_tree(request):
    return ok(work_of(request).tree())


def _with_links(work, item):
    # The editor locks the ID field while other data refers to the ID.
    return {**item, 'id_links': work.id_links(item['meta'].get('id'))}


async def item_get(request):
    work = work_of(request)
    return ok(_with_links(work, work.get_item(request.query_params['path'])))


async def item_put(request):
    data = await body(request)
    work = work_of(request)
    saved = work.save_item(
        request.query_params['path'], data.get('meta'), data.get('body'), data.get('base_hash')
    )
    Snapshots(work).save_point(st(request).settings.load().get('snapshot_interval_minutes'))
    return ok(_with_links(work, saved))


async def item_create(request):
    data = await body(request)
    return ok(work_of(request).create_file(data['path'], data.get('kind')), 201)


async def folder_create(request):
    data = await body(request)
    return ok(work_of(request).create_folder(data['path']), 201)


async def item_move(request):
    data = await body(request)
    return ok(work_of(request).move(data['from'], data['to']))


async def item_kind(request):
    data = await body(request)
    return ok(work_of(request).change_kind(data['path'], data['kind']))


async def item_delete(request):
    work = work_of(request)
    return ok(work.delete(request.query_params['path'], request.query_params.get('extras') == '1'))


async def suggest_item_id(request):
    kind = request.query_params.get('kind', 'lorebook')
    return ok({'id': work_of(request).suggest_id(kind) if kind in KIND_PREFIX else ''})


async def work_check(request):
    s = st(request)
    work = work_of(request)
    return ok(checks.run(work, s.presets.effective(work.doc())))


async def work_search(request):
    query = request.query_params.get('q', '').lower()
    work = work_of(request)
    hits = []
    if query:
        for path in work.item_paths():
            item = work.read_item(path)
            lines = [
                (n + 1, line) for n, line in enumerate(item['body'].splitlines()) if query in line.lower()
            ]
            names = query in item['name'].lower() or query in str(item['meta'].get('id', '')).lower()
            if lines or names:
                hits.append({'path': item['path'], 'name': item['name'], 'lines': lines[:20]})
    return ok(hits)


async def work_trash(request):
    return ok(work_of(request).trash())


async def work_trash_restore(request):
    work = work_of(request)
    Snapshots(work).create('before_bulk', '휴지통에서 되살리기 전')
    return ok(work.restore_trash(request.path_params['bid']))


async def work_trash_purge(request):
    work_of(request).purge_trash(request.path_params.get('bid'))
    return ok()


# --- snapshots -------------------------------------------------------------------------------------------------
async def snap_list(request):
    return ok(Snapshots(work_of(request)).list())


async def snap_create(request):
    data = await body(request)
    created = Snapshots(work_of(request)).create(data.get('reason', 'manual'), data.get('label'), force=True)
    return ok(created, 201)


async def snap_save_point(request):
    """Called when a work is closed: keep a save point if anything changed since the last snapshot."""
    created = Snapshots(work_of(request)).save_point(0, force=True)
    return ok(created)


async def snap_diff(request):
    snaps = Snapshots(work_of(request))
    return ok(snaps.diff(request.path_params['sid'], request.query_params.get('against', 'parent')))


async def snap_file(request):
    snaps = Snapshots(work_of(request))
    path = request.query_params['path']
    sid = request.path_params['sid']
    current = snaps.path_in_work(path)
    return ok(
        {
            'snapshot': snaps.file_text(sid, path),
            'current': current.read_text(encoding='utf-8') if current.is_file() else None,
        }
    )


async def snap_restore(request):
    data = await body(request)
    return ok(Snapshots(work_of(request)).restore(request.path_params['sid'], data.get('paths')))


async def snap_patch(request):
    data = await body(request)
    return ok(Snapshots(work_of(request)).mark_release(request.path_params['sid'], data.get('release')))


# --- export ----------------------------------------------------------------------------------------------------
async def export_preview(request):
    work = work_of(request)
    include, skip = exporter.plan(work)
    target = request.query_params.get('target')
    blocked = exporter.blocked_target(target, st(request).paths.root, work.folder) if target else None
    return ok(
        {
            'include': [i['path'] for i in include],
            'skip': skip,
            'keywords_file': exporter.KEYWORDS_FILE,
            'clash': exporter.name_clash(include),
            'target': exporter.target_state(target, include),
            'blocked': blocked.as_dict() if blocked else None,
        }
    )


async def export_run(request):
    data = await body(request)
    work = work_of(request)
    s = st(request)
    blocked = exporter.blocked_target(data.get('target'), s.paths.root, work.folder)
    if blocked:
        raise AppError(blocked, 400)
    clash = exporter.name_clash(exporter.plan(work)[0])
    if clash:
        raise AppError(
            Msg(
                'server.export.name_clash',
                '{path} has the reserved export name. Rename it first.',
                path=clash,
            ),
            409,
        )
    if data.get('snapshot'):
        Snapshots(work).create('export', data.get('release') or '내보내기', force=True)

    async def runner(progress):
        await progress(30)
        return await asyncio.to_thread(
            exporter.export, work, data['target'], data.get('overwrite', False), s.paths.root
        )

    return ok(s.jobs.submit('export', f'{work.name} 내보내기', runner, work_id=work.id))


# --- drafts, compression, image prompts (mock until 2·5단계) -----------------------------------------------------
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
    data = await body(request)
    work = work_of(request)
    drafts = Drafts(work)
    doc = drafts.get(request.path_params['did'])
    if doc['kind'] == 'text_edit':
        return await editor_routes.apply_edit(request)
    if doc['kind'] == 'content_review':
        raise AppError(Msg('server.editor.review_read_only', 'Review drafts are read-only.'))
    if doc['kind'] == 'image_prompt':
        if doc.get('status') != 'pending':
            raise AppError(Msg('server.drafts.not_pending', 'This draft has already been handled.'), 409)
        cid = doc['target']['id']
        design_path = image_designs.character_design_path(work, cid)
        current = read_json(design_path)
        expected = doc['target'].get('base_design_revision')
        if image_designs.revision(current) != expected:
            raise AppError(
                Msg(
                    'server.image.design.stale',
                    'The character design changed after this conversion draft was created.',
                ),
                409,
            )
        submitted = data.get('design', doc['candidates'][0]['design'])
        image_designs.validate(submitted)
        merged = image_designs.reconcile_conversion(current, submitted)
        Snapshots(work).create('before_llm', 'LLM 결과 채택 전', force=True)
        write_json(design_path, merged)
        doc['applied_design'] = merged
        drafts.save(request.path_params['did'], doc)
        drafts.set_status(request.path_params['did'], 'applied')
        return ok({'path': design_path.relative_to(work.folder).as_posix(), 'design': merged})
    Snapshots(work).create('before_llm', 'LLM 결과 채택 전', force=True)
    if doc['kind'] == 'relations':
        result = review.apply_relation_rows(
            work, data.get('rows', []), doc['candidates'][0].get('people', [])
        )
        drafts.set_status(request.path_params['did'], 'applied')
        return ok(result)
    if doc['kind'] == 'jsx_prompt':
        result = review.insert_text(
            work,
            data.get('text') or doc['candidates'][0]['text'],
            path=data.get('path'),
            new_path=data.get('new_path'),
            position=data.get('position', 'end'),
            heading=data.get('heading'),
        )
        drafts.set_status(request.path_params['did'], 'applied')
        return ok(result)
    if doc['kind'] == 'authoring':
        result = authoring.create_files(work, data.get('files', []), data.get('relations', []))
        drafts.set_status(request.path_params['did'], 'applied')
        return ok(result)
    return ok(
        drafts.apply_text(
            request.path_params['did'],
            data['text'],
            data.get('mode', 'overwrite'),
            data.get('new_name'),
            data.get('enable', 'new'),
        )
    )


async def draft_discard(request):
    return ok(Drafts(work_of(request)).set_status(request.path_params['did'], 'discarded'))


# --- rename across the work ------------------------------------------------------------------------------------
async def rename_preview(request):
    data = await body(request)
    work = work_of(request)
    return ok(rename.preview(work, data.get('find', ''), data.get('replace', ''), data.get('targets')))


async def rename_apply(request):
    data = await body(request)
    work = work_of(request)
    Snapshots(work).create('before_bulk', f'이름 바꾸기 전: {data.get("find", "")}', force=True)
    return ok(rename.apply(work, data['find'], data['replace'], data.get('hits', [])))


# --- relation extraction, consistency check, JSX prompt text ---------------------------------------------------
def item_by_id(work, item_id, kind=None):
    item = next(
        (i for i in work.index() if i['meta'].get('id') == item_id and (kind is None or i['kind'] == kind)),
        None,
    )
    if item is None:
        raise AppError(Msg('server.works.item_missing', 'The file does not exist: {path}', path=item_id), 404)
    return work.get_item(item['path'])


async def relations_extract(request):
    data = await body(request)
    work = work_of(request)
    st(request).llm.require_consent(work, 'consistency', data.get('llm'))
    s = st(request)

    async def runner(progress):
        items = [
            i for i in work.index_with_bodies() if i['meta'].get('enabled', True) and i['kind'] != 'note'
        ]
        characters = [i for i in items if i['kind'] == 'character']
        model = None
        if mocked(s, 'consistency', data.get('llm')):
            await asyncio.sleep(0.4)
            first = characters[0]['name'] if characters else '인물'
            result = {
                'relations': [{'from': first, 'to': '{{user}}', 'kind': '(모의) 관계', 'calls': ''}],
                'facts': [],
            }
        else:
            await progress(10)
            doc = Relations(work).load()
            existing = [f'{r["from"]} → {r["to"]}: {r.get("kind", "")}' for r in doc['relations']]
            others = [i for i in items if i['kind'] in ('main', 'lorebook')]
            messages = llm_tasks.relations_messages(characters, others, existing)
            result, answer = await llm_tasks.ask_json(
                s.llm, 'consistency', messages, work.id, llm_tasks.relations_ok, override=data.get('llm')
            )
            model = {'provider': answer['provider'], 'name': answer['model']}
        draft = Drafts(work).create(
            'relations', {'scope': 'work'}, {}, [review.relation_rows(work, result)], model=model
        )
        s.events.publish('draft', {'work': work.id, 'id': draft['id']})
        return {'draft': draft['id']}

    return ok(s.jobs.submit('relations', f'관계 찾기 · {work.name}', runner, work_id=work.id))


async def consistency_run(request):
    data = await body(request)
    work = work_of(request)
    st(request).llm.require_consent(work, 'consistency', data.get('llm'))
    s = st(request)
    bundles = review.consistency_bundles(work, data.get('scope') or None)

    async def runner(progress):
        issues, model = [], None
        if mocked(s, 'consistency', data.get('llm')):
            await asyncio.sleep(0.4)
            for bundle in bundles[:1]:
                head = bundle['items'][0]
                quote = next(
                    (line for line in head['body'].splitlines() if line.strip() and not line.startswith('#')),
                    '',
                )
                issues.append(
                    {
                        'type': 'ambiguous',
                        'items': [head['id']],
                        'quote': quote.strip(),
                        'quote_item': head['id'],
                        'explain': '(모의) 검사 흐름을 보여 주는 예시 문제입니다.',
                        'suggest': None,
                    }
                )
        else:
            guideline = work_guideline(s, work, 'consistency.md')
            glossary = review.glossary_lines(work)
            for n, bundle in enumerate(bundles):
                await progress(int(100 * n / max(1, len(bundles))) + 2)
                messages = llm_tasks.consistency_messages(
                    bundle['person'],
                    bundle['items'],
                    bundle['relations'],
                    bundle['facts'],
                    glossary,
                    guideline,
                )
                result, answer = await llm_tasks.ask_json(
                    s.llm,
                    'consistency',
                    messages,
                    work.id,
                    llm_tasks.consistency_ok,
                    override=data.get('llm'),
                )
                issues.extend(result['issues'])
                model = {'provider': answer['provider'], 'name': answer['model']}
        draft = Drafts(work).create(
            'consistency',
            {'scope': data.get('scope') or 'work'},
            {'people': [b['person'] for b in bundles]},
            [{'issues': review.normalize_issues(work, issues)}],
            model=model,
            guidelines=['consistency.md'],
        )
        s.events.publish('draft', {'work': work.id, 'id': draft['id']})
        return {'draft': draft['id']}

    return ok(s.jobs.submit('consistency', f'모순 검사 · {work.name}', runner, work_id=work.id))


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
    data = await body(request)
    work = work_of(request)
    st(request).llm.require_consent(work, 'jsx_prompt', data.get('llm'))
    s = st(request)
    item = item_by_id(work, request.path_params['jid'], 'jsx')
    props = data.get('props') or {}
    rule = review.response_rule(s.presets.effective(work.doc()))

    async def runner(progress):
        model = None
        if mocked(s, 'jsx_prompt', data.get('llm')):
            await asyncio.sleep(0.4)
            text = (
                f'## {item["name"]}\n응답 맨 끝에 아래 형식으로 {item["name"]}을(를) 한 번 출력한다.\n'
                f'{call_text(item["name"], props, rule) or "<" + item["name"] + " />"}\n(모의 문구)'
            )
        else:
            await progress(10)
            messages = llm_tasks.jsx_prompt_messages(
                item['name'],
                item['body'],
                props,
                work_guideline(s, work, 'jsx.md'),
                work_guideline(s, work, 'platform.md'),
                data.get('feedback', ''),
            )
            result, answer = await llm_tasks.ask_json(
                s.llm, 'jsx_prompt', messages, work.id, llm_tasks.jsx_prompt_ok, override=data.get('llm')
            )
            text = result['text'].strip()
            model = {'provider': answer['provider'], 'name': answer['model']}
        draft = Drafts(work).create(
            'jsx_prompt',
            {'id': item['meta'].get('id'), 'path': item['path'], 'name': item['name']},
            {'props': props, 'feedback': data.get('feedback', '')},
            [{'round': 1, 'text': text, 'elements': review.elements(text, item['name'], rule)}],
            model=model,
            guidelines=['platform.md', 'jsx.md'],
        )
        s.events.publish('draft', {'work': work.id, 'id': draft['id']})
        return {'draft': draft['id']}

    return ok(s.jobs.submit('jsx_prompt', f'JSX 문구 · {item["name"]}', runner, work_id=work.id))


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


# --- authoring (mock skeleton until 3단계) -------------------------------------------------------------------
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
    st(request).llm.require_consent(work, 'authoring', data.get('llm'))
    s = st(request)
    scale = _authoring_scale(work, data.get('scale'))
    answers = data.get('answers', [])

    async def runner(progress):
        model = None
        if mocked(s, 'authoring', data.get('llm')):
            for value in (25, 60, 90):
                await asyncio.sleep(0.4)
                await progress(value)
            skeleton = authoring.mock_skeleton(work, scale, answers)
        else:
            await progress(10)
            messages = llm_tasks.authoring_messages(
                answers,
                work_guideline(s, work, f'authoring/{scale}.md'),
                work_guideline(s, work, 'platform.md'),
                list(work.section_titles().values()),
                scale,
            )
            result, answer = await llm_tasks.ask_json(
                s.llm, 'authoring', messages, work.id, llm_tasks.authoring_ok, override=data.get('llm')
            )
            skeleton = llm_tasks.authoring_skeleton(result, work)
            model = {'provider': answer['provider'], 'name': answer['model']}
        draft = Drafts(work).create(
            'authoring',
            {'scope': 'work', 'scale': scale},
            {'answers': answers},
            [skeleton],
            model=model,
            guidelines=[f'authoring/{scale}.md', 'platform.md'],
        )
        s.events.publish('draft', {'work': work.id, 'id': draft['id']})
        return {'draft': draft['id']}

    return ok(s.jobs.submit('authoring', f'뼈대 작성 · {work.name}', runner, work_id=work.id))


async def compress(request):
    data = await body(request)
    work = work_of(request)
    st(request).llm.require_consent(work, 'compression', data.get('llm'))
    s = st(request)
    item = work.get_item(data['path'])

    rounds = max(1, min(4, int(data.get('candidates', 2))))
    locked = [int(n) for n in data.get('locked', [])]
    target = data.get('target_size')
    if target is not None and (isinstance(target, bool) or not isinstance(target, int) or target <= 0):
        raise AppError(
            Msg('server.editor.bad_target', 'Target size must be a positive number of bytes.'), 400
        )
    instruction = str(data.get('instructions') or '').strip()

    async def runner(progress):
        model = None
        if mocked(s, 'compression', data.get('llm')):
            for value in (20, 50, 80):
                await asyncio.sleep(0.4)
                await progress(value)
            blocks, candidates = mock_compress(item['body'], rounds)
        else:
            blocks, messages = llm_tasks.compression_messages(
                item['body'],
                '\n\n'.join(filter(None, [work_guideline(s, work, 'compression.md'), instruction])),
                work_guideline(s, work, 'platform.md'),
                data.get('target_size'),
                locked,
            )
            candidates = []
            for n in range(rounds):
                await progress(int(100 * n / rounds) + 5)
                result, answer = await llm_tasks.ask_json(
                    s.llm,
                    'compression',
                    llm_tasks.compression_round(messages, n),
                    work.id,
                    llm_tasks.compression_ok,
                    override=data.get('llm'),
                )
                candidates.append(llm_tasks.compression_candidate(result, blocks, locked))
                model = {'provider': answer['provider'], 'name': answer['model']}
        draft = Drafts(work).create(
            'compression',
            {'id': item['meta'].get('id'), 'path': item['path'], 'base_hash': item['hash']},
            {'target_size': data.get('target_size'), 'keep': locked, 'feedback': []},
            candidates,
            model=model,
            guidelines=['platform.md', 'compression.md'],
            blocks=blocks,
        )
        s.events.publish('draft', {'work': work.id, 'id': draft['id']})
        return {'draft': draft['id']}

    return ok(s.jobs.submit('compression', f'압축 · {item["name"]}', runner, gpu=True, work_id=work.id))


async def image_design(request):
    work = work_of(request)
    cid = request.path_params['cid']
    item = next((i for i in work.index() if i['kind'] == 'character' and i['meta'].get('id') == cid), None)
    if item is None:
        raise AppError(Msg('server.image.no_character', 'Character {id} was not found.', id=cid), 404)
    design = read_json(image_designs.character_design_path(work, cid))
    status = {}
    if design and item:
        body_text = work.get_item(item['path'])['body']
        parts = {'appearance': design.get('appearance', {})}
        parts.update({f'outfit:{k}': v for k, v in (design.get('outfits') or {}).items()})
        for key, part in parts.items():
            source = part.get('source') or {}
            text = work.section_text(body_text, source.get('section'), source.get('heading'))
            if not source:
                status[key] = 'manual'
            elif text is None:
                status[key] = 'broken'
            else:
                status[key] = 'fresh' if sha256_text(text) == source.get('hash') else 'stale'
    return ok({'design': design, 'status': status, 'revision': image_designs.revision(design)})


async def image_design_update(request):
    work = work_of(request)
    cid = request.path_params['cid']
    item = next((i for i in work.index() if i['kind'] == 'character' and i['meta'].get('id') == cid), None)
    if item is None:
        raise AppError(Msg('server.image.no_character', 'Character {id} was not found.', id=cid), 404)
    data = await body(request)
    design_path = image_designs.character_design_path(work, cid)
    previous = read_json(design_path)
    if data.get('base_revision') != image_designs.revision(previous):
        raise AppError(
            Msg('server.image.design.stale', 'The character design changed after it was loaded.'), 409
        )
    merged = image_designs.prepare_update(previous, data.get('design'))
    Snapshots(work).create('before_edit', '이미지 디자인 수정 전', force=True)
    write_json(design_path, merged)
    return ok({'design': merged, 'revision': image_designs.revision(merged)})


async def image_convert(request):
    work = work_of(request)
    s = st(request)
    cid = request.path_params['cid']
    item = next((i for i in work.index() if i['kind'] == 'character' and i['meta'].get('id') == cid), None)
    if item is None:
        raise AppError(Msg('server.image.no_character', 'Character {id} was not found.', id=cid), 404)
    body_text = work.get_item(item['path'])['body']
    design_path = image_designs.character_design_path(work, cid)
    old = read_json(design_path)
    base_design_revision = image_designs.revision(old)
    old = old or {}
    data = await body(request)
    s.llm.require_consent(work, 'image_prompt', data.get('llm'))

    async def runner(progress):
        appearance = work.section_text(body_text, 'appearance') or ''
        outfit_all = work.section_text(body_text, 'outfit') or ''
        headings = [line[4:].strip() for line in outfit_all.splitlines() if line.startswith('### ')] or [
            '기본'
        ]
        texts = [work.section_text(body_text, 'outfit', h if h != '기본' else None) or '' for h in headings]
        model = None
        if mocked(s, 'image_prompt', data.get('llm')):
            await asyncio.sleep(0.6)
            await progress(60)
            result = {
                'appearance': {'prompt': ['1girl', 'solo', '(모의 태그)'], 'negative': []},
                'outfits': [{'name': h, 'slots': {'top': ['(모의 태그)']}, 'negative': []} for h in headings],
            }
        else:
            await progress(10)
            compose = (
                read_json(work.app / 'image' / 'compose.json')
                or read_json(s.paths.data / 'image' / 'compose.json')
                or {}
            )
            slots = compose.get('slots') or [{'id': 'full', 'name': '전체'}, {'id': 'top', 'name': '상의'}]
            messages = llm_tasks.image_messages(
                appearance,
                list(zip(headings, texts, strict=True)),
                slots,
                work_guideline(s, work, 'image-prompt.md'),
            )
            result, answer = await llm_tasks.ask_json(
                s.llm, 'image_prompt', messages, work.id, llm_tasks.image_ok, override=data.get('llm')
            )
            model = {'provider': answer['provider'], 'name': answer['model']}
            allowed = {slot['id'] for slot in slots}
            for outfit in result['outfits']:
                outfit['slots'] = {k: v for k, v in (outfit.get('slots') or {}).items() if k in allowed}
        outfits_by_name = {
            str(o.get('name', '')).strip(): o for o in result['outfits'] if isinstance(o, dict)
        }
        design = {
            'schema_version': 1,
            'trigger': old.get('trigger') or f'{work.id.lower()}_{cid.lower()}',
            'appearance': {
                'prompt': llm_tasks.tags(result['appearance'].get('prompt')),
                'negative': llm_tasks.tags(result['appearance'].get('negative')),
                'source': {'section': 'appearance', 'hash': sha256_text(appearance)},
            },
            'outfits': {},
            'default_outfit': None,
        }
        for n, (heading, text) in enumerate(zip(headings, texts, strict=True), 1):
            key = f'o{n:02d}'
            got = outfits_by_name.get(heading) or (
                result['outfits'][n - 1] if n <= len(result['outfits']) else {}
            )
            design['outfits'][key] = {
                'name': heading,
                'slots': {
                    k: {'prompt': llm_tasks.tags(v)}
                    for k, v in (got.get('slots') or {}).items()
                    if llm_tasks.tags(v)
                },
                'negative': llm_tasks.tags(got.get('negative')),
                'source': {
                    'section': 'outfit',
                    'heading': heading if heading != '기본' else None,
                    'hash': sha256_text(text),
                },
            }
        design['default_outfit'] = next(iter(design['outfits']), None)
        design = image_designs.reconcile_conversion(old, design)
        draft = Drafts(work).create(
            'image_prompt',
            {
                'id': cid,
                'path': item['path'],
                'base_hash': item['hash'],
                'base_design_revision': base_design_revision,
            },
            {'parts': 'all', 'previous_design': old},
            [{'round': 1, 'design': design}],
            model=model,
            guidelines=['image-prompt.md'],
        )
        s.events.publish('draft', {'work': work.id, 'id': draft['id']})
        return {'draft': draft['id']}

    return ok(
        s.jobs.submit('image_prompt', f'이미지 프롬프트 · {item["name"]}', runner, gpu=True, work_id=work.id)
    )


# --- JSX example props -----------------------------------------------------------------------------------------
def _props(request):
    # The component name turns old JSON examples into calls; an item without that ID still lists its examples.
    work, jsx_id = work_of(request), request.path_params['jid']
    try:
        name = item_by_id(work, jsx_id, 'jsx')['name']
    except AppError:
        name = 'Component'
    return Props(work, jsx_id, name, review.response_rule(st(request).presets.effective(work.doc())))


async def props_list(request):
    return ok(_props(request).list())


async def props_put(request):
    text = (await request.body()).decode('utf-8')
    # Examples are written only for a JSX item that exists, never under a stray ID (e.g. before the item has one).
    work, jsx_id = work_of(request), request.path_params['jid']
    if not any(i['meta'].get('id') == jsx_id and i['kind'] == 'jsx' for i in work.index()):
        raise AppError(Msg('server.jsx.no_item', 'There is no JSX item with the ID {id}.', id=jsx_id), 404)
    return ok(_props(request).save(request.path_params['name'], text))


async def props_delete(request):
    return ok(_props(request).delete(request.path_params['name']))


# --- relation map, glossary -----------------------------------------------------------------------------------
async def relations_get(request):
    return ok(Relations(work_of(request)).view())


async def relations_put(request):
    return ok(Relations(work_of(request)).save(await body(request)))


async def glossary_get(request):
    return ok(Glossary(work_of(request)).load())


async def glossary_put(request):
    return ok(Glossary(work_of(request)).save(await body(request)))


# --- chat test (mock reply until 3단계) ----------------------------------------------------------------------------
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


# --- jobs, events --------------------------------------------------------------------------------------------------
async def jobs_list(request):
    s = st(request)
    return ok([s.jobs.public(j) for j in s.jobs.list()])


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


# --- static web --------------------------------------------------------------------------------------------------
def spa(web_dir: Path):
    async def index(request):
        if request.path_params.get('rest', '').startswith('api/'):
            return JSONResponse(
                {'error': Msg('server.api.not_found', 'Unknown API address.').as_dict()}, status_code=404
            )
        # The sandboxed JSX preview is its own page; everything else is the app.
        page = 'preview.html' if request.path_params.get('rest') == 'preview.html' else 'index.html'
        target = web_dir / page
        if target.is_file():
            return FileResponse(target)
        return Response(
            'Web UI is not built. Run the dev server (npm run dev) or build it (npm run build).',
            media_type='text/plain',
            status_code=503,
        )

    return index


def build_app(paths, dev=False, kdf=None, desktop=False):
    w = '/api/works/{wid}'
    routes = [
        Route('/api/auth/status', auth_status),
        Route('/api/auth/setup', auth_setup, methods=['POST']),
        Route('/api/auth/unlock', auth_unlock, methods=['POST']),
        Route('/api/auth/lock', auth_lock, methods=['POST']),
        Route('/api/auth/reset', auth_reset, methods=['POST']),
        Route('/api/about', about_get),
        Route('/api/about/notices', about_notices),
        Route('/api/update-check', update_check),
        Route('/api/open-in-browser', open_in_browser, methods=['POST']),
        Route('/api/settings', settings_get),
        Route('/api/settings', settings_patch, methods=['PATCH']),
        Route('/api/guidelines', agent_routes.guidelines_list),
        Route('/api/guidelines/file', agent_routes.guideline_get),
        Route('/api/guidelines/file', agent_routes.guideline_put, methods=['PUT']),
        Route('/api/guidelines/file', agent_routes.guideline_delete, methods=['DELETE']),
        Route('/api/settings/compression-guideline', compression_guideline_get),
        Route('/api/settings/compression-guideline', compression_guideline_put, methods=['PUT']),
        Route('/api/personas', personas_get),
        Route('/api/personas', personas_put, methods=['PUT']),
        Route('/api/ui-state', ui_state_get),
        Route('/api/ui-state', ui_state_put, methods=['PUT']),
        Route('/api/vault', vault_list),
        Route('/api/vault', vault_put, methods=['POST']),
        Route('/api/vault/password', vault_password, methods=['POST']),
        Route('/api/vault/{name}', vault_delete, methods=['DELETE']),
        Route('/api/providers', providers_get),
        Route('/api/providers', providers_put, methods=['PUT']),
        Route('/api/providers/{pid}/models', providers_models),
        Route('/api/providers/{pid}/probe', providers_probe, methods=['POST']),
        Route('/api/usage', usage),
        Route('/api/usage/log', usage_log),
        Route('/api/usage.csv', usage_csv),
        Route('/api/platforms', presets_list),
        Route('/api/platforms', presets_create, methods=['POST']),
        Route('/api/platforms/{pid}', presets_get),
        Route('/api/platforms/{pid}', presets_put, methods=['PUT']),
        Route('/api/platforms/{pid}', presets_delete, methods=['DELETE']),
        Route('/api/works', works_list),
        Route('/api/works', works_create, methods=['POST']),
        Route('/api/samples', samples_list),
        Route('/api/samples/{name}/install', samples_install, methods=['POST']),
        Route('/api/trash', data_trash_list),
        Route('/api/trash', data_trash_purge, methods=['DELETE']),
        Route('/api/trash/{bid}/restore', data_trash_restore, methods=['POST']),
        Route('/api/trash/{bid}', data_trash_purge, methods=['DELETE']),
        Route(w, work_get),
        Route(w, works_patch, methods=['PATCH']),
        Route(w, works_delete, methods=['DELETE']),
        Route(f'{w}/duplicate', works_duplicate, methods=['POST']),
        Route(f'{w}/tree', work_tree),
        Route(f'{w}/file', item_get),
        Route(f'{w}/file', item_put, methods=['PUT']),
        Route(f'{w}/file', item_create, methods=['POST']),
        Route(f'{w}/file', item_delete, methods=['DELETE']),
        Route(f'{w}/folder', folder_create, methods=['POST']),
        Route(f'{w}/move', item_move, methods=['POST']),
        Route(f'{w}/kind', item_kind, methods=['POST']),
        Route(f'{w}/suggest-id', suggest_item_id),
        Route(f'{w}/check', work_check),
        Route(f'{w}/search', work_search),
        Route(f'{w}/trash', work_trash),
        Route(f'{w}/trash', work_trash_purge, methods=['DELETE']),
        Route(f'{w}/trash/{{bid}}/restore', work_trash_restore, methods=['POST']),
        Route(f'{w}/trash/{{bid}}', work_trash_purge, methods=['DELETE']),
        Route(f'{w}/snapshots', snap_list),
        Route(f'{w}/snapshots', snap_create, methods=['POST']),
        Route(f'{w}/snapshots/save-point', snap_save_point, methods=['POST']),
        Route(f'{w}/snapshots/{{sid}}/diff', snap_diff),
        Route(f'{w}/snapshots/{{sid}}/file', snap_file),
        Route(f'{w}/snapshots/{{sid}}/restore', snap_restore, methods=['POST']),
        Route(f'{w}/snapshots/{{sid}}', snap_patch, methods=['PATCH']),
        Route(f'{w}/export/preview', export_preview),
        Route(f'{w}/export', export_run, methods=['POST']),
        Route(f'{w}/drafts', drafts_list),
        Route(f'{w}/drafts/{{did}}', draft_get),
        Route(f'{w}/drafts/{{did}}/composition', draft_composition, methods=['PUT']),
        Route(f'{w}/drafts/{{did}}/apply', draft_apply, methods=['POST']),
        Route(f'{w}/drafts/{{did}}/discard', draft_discard, methods=['POST']),
        Route(f'{w}/compress', compress, methods=['POST']),
        Route(f'{w}/editor/{{action}}', editor_routes.run_action, methods=['POST']),
        Route(f'{w}/agent/modes', agent_routes.modes),
        Route(f'{w}/agent/sessions', agent_routes.sessions_list),
        Route(f'{w}/agent/sessions', agent_routes.sessions_create, methods=['POST']),
        Route(f'{w}/agent/sessions/{{sid}}', agent_routes.session_get),
        Route(f'{w}/agent/sessions/{{sid}}', agent_routes.session_patch, methods=['PATCH']),
        Route(f'{w}/agent/sessions/{{sid}}', agent_routes.session_delete, methods=['DELETE']),
        Route(f'{w}/agent/sessions/{{sid}}/preview', agent_routes.preview, methods=['POST']),
        Route(f'{w}/agent/sessions/{{sid}}/send', agent_routes.send, methods=['POST']),
        Route(
            f'{w}/agent/sessions/{{sid}}/proposals/{{turn:int}}/{{n:int}}/review',
            agent_routes.proposal_review,
            methods=['POST'],
        ),
        Route(f'{w}/agent-drafts/{{did}}/apply', agent_routes.draft_apply, methods=['POST']),
        Route(f'{w}/editor-drafts/{{did}}/apply', editor_routes.apply_edit, methods=['POST']),
        Route(f'{w}/image/characters/{{cid}}', image_design),
        Route(f'{w}/image/characters/{{cid}}', image_design_update, methods=['PUT']),
        Route(f'{w}/image/characters/{{cid}}/convert', image_convert, methods=['POST']),
        Route(f'{w}/jsx/{{jid}}/props', props_list),
        Route(f'{w}/jsx/{{jid}}/props/{{name}}', props_put, methods=['PUT']),
        Route(f'{w}/jsx/{{jid}}/props/{{name}}', props_delete, methods=['DELETE']),
        Route(f'{w}/authoring/questions', authoring_questions),
        Route(f'{w}/authoring', authoring_run, methods=['POST']),
        Route(f'{w}/rename-text/preview', rename_preview, methods=['POST']),
        Route(f'{w}/rename-text', rename_apply, methods=['POST']),
        Route(f'{w}/relations/extract', relations_extract, methods=['POST']),
        Route(f'{w}/consistency', consistency_run, methods=['POST']),
        Route(f'{w}/drafts/{{did}}/issues/{{n}}', draft_issue, methods=['POST']),
        Route(f'{w}/jsx/{{jid}}/prompt-text', jsx_prompt_text, methods=['POST']),
        Route(f'{w}/jsx/{{jid}}/usages', jsx_usages),
        Route(f'{w}/jsx/elements', jsx_elements, methods=['POST']),
        Route(f'{w}/relations', relations_get),
        Route(f'{w}/relations', relations_put, methods=['PUT']),
        Route(f'{w}/glossary', glossary_get),
        Route(f'{w}/glossary', glossary_put, methods=['PUT']),
        Route(f'{w}/chat/preview', chat_preview, methods=['POST']),
        Route(f'{w}/chat/send', chat_send, methods=['POST']),
        Route('/api/jobs', jobs_list),
        Route('/api/jobs/{jid}/cancel', jobs_cancel, methods=['POST']),
        Route('/api/events', events),
        *image_routes.routes(),
        *tool_routes.routes(),
        *lora_routes.routes(),
    ]
    if paths.web.is_dir() and (paths.web / 'assets').is_dir():
        routes.append(Mount('/assets', StaticFiles(directory=paths.web / 'assets')))
    # The packaged app carries the offline manual beside the executable; Help opens it from here.
    if (paths.root / 'manual' / 'index.html').is_file():
        routes.append(Mount('/manual', StaticFiles(directory=paths.root / 'manual', html=True)))
    routes.append(Route('/{rest:path}', spa(paths.web)))
    state = State(paths, dev=dev, kdf=kdf, desktop=desktop)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        # The image worker thread lives as long as the server.
        state.image.start()
        try:
            yield
        finally:
            state.image.shutdown()

    app = Starlette(
        routes=routes,
        middleware=[Middleware(Guard)],
        exception_handlers={AppError: handle_app_error},
        lifespan=lifespan,
    )
    app.state.app = state
    return app
