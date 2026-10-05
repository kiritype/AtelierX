"""Agent panel (11-agent, decision 0021): modes from guidelines, conversations, context assembly and file proposals.

The agent never writes files. Its answer proposes whole new file contents between markers; the user sends a proposal
to review (a draft of kind ``agent_file``) and adopts the hunks they want there.
"""

import json
import re
import secrets
from datetime import datetime

from . import frontmatter, guidelines
from .count import estimate_tokens
from .fsutil import sha256_text
from .i18n import AppError, Msg
from .works import ITEM_SUFFIXES, now_iso

# The rules every mode starts with. Users cannot change them (Settings → 지침 shows them read-only).
FIXED_RULES = """너는 AtelierX의 작성 보조 에이전트다. 사용자는 RP 챗봇(작품)을 파일 여러 개로 나눠 쓰고 있다.

규칙:
- 너는 파일을 직접 고칠 수 없다. 파일을 고쳤다거나 저장했다고 말하지 마라.
- 파일을 바꾸거나 새로 만들 때는 그 파일의 새 내용 **전체**를 아래 형식으로 쓴다. 머리 메타데이터(`---` 사이)도 빠짐없이
  포함한다. 일부만 쓰거나 "(이하 동일)", "…생략"처럼 줄이면 안 된다. 사용자가 검토 화면에서 바뀐 부분만 골라 채택한다.

<<<file path="폴더/파일.md">>>
(새 내용 전체)
<<<end>>>

- 표지 두 줄은 정확히 이 모양으로 각각 한 줄을 차지한다. 코드 울타리(```)로 감싸지 마라.
- 바꿀 필요가 없는 파일은 쓰지 마라. 한 응답에 여러 파일을 쓸 수 있다. 새 파일은 작품에 없는 경로로 쓰고, 머리 메타데이터의
  `kind`(main, start, lorebook, character, jsx, note)를 정한다.
- 작품 맥락에 없는 설정을 사실처럼 지어내지 마라. 모르는 것은 사용자에게 묻는다.
- {{user}}와 {{char}}는 예약 참조다. 다른 이름으로 바꾸지 말고, 따옴표나 백틱으로 감싸지 말고 글자 그대로 써라(예: {{user}}에게 손을 흔들었다).
- 사용자가 쓴 언어로 답한다."""

FREE_MODE = {
    'id': 'free',
    'name': '자유 대화',
    'description': '정해진 방식 없이 묻고 답합니다.',
    'scope': 'file',
    'order': 1000,
    'source': None,
}

MARK = re.compile(r'^<<<file path="([^"\n]+)">>>[ \t]*$', re.MULTILINE)
END = re.compile(r'^<<<end>>>[ \t]*$', re.MULTILINE)
FENCE = re.compile(r'\A```[^\n]*\n(.*)\n```[ \t]*\n?\Z', re.DOTALL)
OMISSION = re.compile(
    r'(이하|아래|나머지|위와|기존과)\s*(동일|생략|같음|같다)|…\s*생략|\.\.\.\s*생략|\(생략\)|\[생략\]'
    r'|rest (of the file )?(is )?unchanged|unchanged\)|\(omitted\)',
    re.IGNORECASE,
)
# A reserved reference wrapped in quotes or backticks (`{{user}}`) reaches the platform with the marks around it.
WRAPPED_REF = re.compile(r'[`\'"]\{\{(?:user|char)\}\}[`\'"]')
SESSION_ID = re.compile(r'\d{8}T\d{6}-[0-9a-f]{4}')
DEFAULT_CONTEXT = 8192
CONTEXT_SHARE = 0.6  # the rest is left for the answer: whole files are long
ATTACHMENT_LIMIT = 40000


# --- modes ----------------------------------------------------------------------------------------------------------
def modes(work, paths, linked):
    """Agent modes this work can use: every ``agent/<id>.md`` from the work, its presets, global and app defaults."""
    ids = set()
    for folder in guidelines.folders(work, paths, linked, 'agent'):
        if folder.is_dir():
            ids |= {p.stem for p in folder.glob('*.md') if guidelines.AGENT_ID.fullmatch(p.stem)}
    out = []
    for mode_id in ids:
        text, source = guidelines.locate(work, paths, linked, f'agent/{mode_id}.md')
        head, _ = guidelines.mode_head(text)
        out.append({'id': mode_id, **head, 'name': head['name'] or mode_id, 'source': source})
    if 'free' not in ids:
        out.append(dict(FREE_MODE))
    return sorted(out, key=lambda m: (m['order'], m['name']))


def mode_text(work, paths, linked, mode_id):
    if not mode_id or not guidelines.AGENT_ID.fullmatch(str(mode_id)):
        return ''
    text, _ = guidelines.locate(work, paths, linked, f'agent/{mode_id}.md')
    return guidelines.mode_head(text)[1].strip() if text else ''


# --- conversations (.atelierx/agent/<id>.jsonl, data-model: 에이전트 대화) ------------------------------------
class Sessions:
    def __init__(self, work):
        self.work = work
        self.root = work.app / 'agent'

    def _path(self, sid):
        if not SESSION_ID.fullmatch(str(sid or '')):
            raise AppError(Msg('server.agent.no_session', 'This conversation does not exist.'), 404)
        path = self.root / f'{sid}.jsonl'
        if not path.is_file():
            raise AppError(Msg('server.agent.no_session', 'This conversation does not exist.'), 404)
        return path

    def create(self, mode, scope):
        sid = f'{datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")}-{secrets.token_hex(2)}'
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f'{sid}.jsonl').touch()
        self.append(sid, {'type': 'meta', 'mode': mode, 'title': '', 'scope': clean_scope(self.work, scope)})
        return self.read(sid)

    def append(self, sid, event):
        path = self._path(sid)
        with path.open('a', encoding='utf-8', newline='\n') as file:
            file.write(json.dumps({**event, 'at': now_iso()}, ensure_ascii=False) + '\n')

    def _events(self, path):
        events = []
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a line cut by a crash; the rest of the conversation still reads
        return events

    def read(self, sid):
        path = self._path(sid)
        doc = {'id': sid, 'mode': 'free', 'title': '', 'scope': {'kind': 'file', 'paths': []}, 'turns': []}
        for event in self._events(path):
            kind = event.get('type')
            if kind == 'meta':
                doc.update({k: v for k, v in event.items() if k in ('mode', 'title', 'scope')})
                doc.setdefault('created_at', event.get('at'))
            elif kind in ('user', 'assistant'):
                doc['turns'].append({**event, 'role': kind, 'turn': len(doc['turns']) + 1})
            elif kind == 'proposal':
                turn = next((t for t in doc['turns'] if t['turn'] == event.get('turn')), None)
                for proposal in (turn or {}).get('proposals', []):
                    if proposal.get('n') == event.get('n'):
                        proposal['draft_id'] = event.get('draft_id')
            doc['updated_at'] = event.get('at')
        return doc

    def list(self):
        out = []
        if self.root.is_dir():
            for path in self.root.glob('*.jsonl'):
                if not SESSION_ID.fullmatch(path.stem):
                    continue
                doc = self.read(path.stem)
                out.append(
                    {
                        'id': doc['id'],
                        'mode': doc['mode'],
                        'title': doc['title'],
                        'turns': len(doc['turns']),
                        'updated_at': doc.get('updated_at'),
                    }
                )
        return sorted(out, key=lambda s: s['updated_at'] or '', reverse=True)

    def update(self, sid, changes):
        meta = {'type': 'meta'}
        if 'title' in changes:
            meta['title'] = str(changes['title'] or '').strip()[:80]
        if 'scope' in changes:
            meta['scope'] = clean_scope(self.work, changes['scope'])
        if 'mode' in changes:
            meta['mode'] = str(changes['mode'] or 'free')
        self.append(sid, meta)
        return self.read(sid)

    def delete(self, sid):
        self._path(sid).unlink()


def clean_scope(work, scope):
    scope = scope if isinstance(scope, dict) else {}
    kind = scope.get('kind') if scope.get('kind') in ('file', 'paths', 'work') else 'file'
    kept = []
    for rel in scope.get('paths') or []:
        try:
            work.resolve(rel)
        except AppError:
            continue
        kept.append(str(rel).strip('/'))
    return {'kind': kind, 'paths': [] if kind == 'work' else kept[:50]}


def scope_items(work, scope):
    """Items whose bodies the scope brings in, in the order given (a folder brings its items)."""
    items = work.index()
    if scope['kind'] == 'work':
        return items
    out = []
    for rel in scope['paths']:
        for item in items:
            if (item['path'] == rel or item['path'].startswith(rel + '/')) and item not in out:
                out.append(item)
    return out


# --- context ---------------------------------------------------------------------------------------------------
def context_budget(provider, model):
    context = ((provider.get('models') or {}).get(model) or {}).get('context') or DEFAULT_CONTEXT
    return int(int(context) * CONTEXT_SHARE)


def platform_summary(effective):
    values = effective.get('values', {})
    lines = [f'- 용량 세는 방식: {values.get("count") or "utf8_bytes"}']
    for key, limit in (values.get('limits') or {}).items():
        if isinstance(limit, dict) and limit.get('max'):
            lines.append(f'- {key} 최대: {limit["max"]}')
    response = (values.get('jsx') or {}).get('response') or {}
    if response:
        lines.append(f'- 응답 속 컴포넌트 표기: {json.dumps(response, ensure_ascii=False)}')
    return '\n'.join(lines)


def file_block(path, text):
    return f'<<<file path="{path}">>>\n{text.rstrip(chr(10))}\n<<<end>>>'


def attachment_text(work, attachment):
    path = str(attachment.get('path') or '')
    text = attachment.get('text')
    if not isinstance(text, str):
        text = work.resolve(path).read_text(encoding='utf-8')
    span = ''
    if attachment.get('from'):
        span = f':{attachment["from"]}-{attachment.get("to") or attachment["from"]}'
    return f'[첨부 {path}{span}]\n{text[:ATTACHMENT_LIMIT]}'


def build(work, paths, effective, linked, session, message, attachments, budget):
    """Chat messages for the model and a summary of what went in (11-agent: 맥락 조립)."""
    mode = mode_text(work, paths, linked, session['mode'])
    platform = guidelines.find(work, paths, linked, 'platform.md').strip()
    system = [FIXED_RULES]
    if mode:
        system.append(f'## 모드 지침\n\n{mode}')
    system.append(f'## 플랫폼 규칙\n\n{platform}\n\n{platform_summary(effective)}'.strip())

    attached = [attachment_text(work, a) for a in attachments or []]
    asked = '\n\n'.join([*attached, message]) if attached else message
    used = estimate_tokens('\n\n'.join(system)) + estimate_tokens(asked)

    wanted = scope_items(work, session['scope'])
    bodies, omitted = [], []
    for item in wanted:
        text = work.resolve(item['path']).read_text(encoding='utf-8')
        cost = estimate_tokens(text) + 20
        if used + cost > budget:
            omitted.append(item['path'])
            continue
        used += cost
        bodies.append((item['path'], text))
    included = {p for p, _ in bodies}
    listing = '\n'.join(
        f'- {i["path"]} ({i["kind"]}{", " + i["meta"]["id"] if i["meta"].get("id") else ""}, {i["size"]} B)'
        f'{" ← 본문 아래" if i["path"] in included else " (본문 빠짐)"}'
        for i in wanted
    )
    work_context = f'## 범위의 파일 목록\n\n{listing or "(파일 없음)"}'
    if bodies:
        work_context += '\n\n## 범위의 본문\n\n' + '\n\n'.join(file_block(p, t) for p, t in bodies)
    if omitted:
        work_context += '\n\n(예산을 넘어 본문을 뺀 파일: ' + ', '.join(omitted) + ')'
    used += estimate_tokens(listing)
    system.append(work_context)

    history = []
    for turn in reversed(session['turns']):
        content = turn.get('text') or ''
        if turn['role'] == 'user' and turn.get('attachments'):
            content = '\n\n'.join([*(attachment_text(work, a) for a in turn['attachments']), content])
        cost = estimate_tokens(content)
        if not content or used + cost > budget:
            break
        used += cost
        history.insert(0, {'role': turn['role'], 'content': content})

    messages = [
        {'role': 'system', 'content': '\n\n'.join(system)},
        *history,
        {'role': 'user', 'content': asked},
    ]
    summary = {
        'files': len(bodies),
        'tokens': used,
        'budget': budget,
        'omitted': omitted,
        'history': len(history),
        'history_dropped': len(session['turns']) - len(history),
    }
    return messages, summary


# --- proposals -------------------------------------------------------------------------------------------------
def _normalize(raw):
    path = str(raw).strip().replace('\\', '/')
    while path.startswith('./'):
        path = path[2:]
    return path.strip('/')


def _head(text, suffix):
    try:
        meta, _, _ = frontmatter.split(text, suffix)
        return frontmatter.to_plain(meta) or {}, None
    except frontmatter.MetaError as error:
        return {}, str(error)


def proposals(work, text):
    """Read the file proposals of an answer. Each has the new text, whether it is cut off, and warnings."""
    found = {}
    for match in MARK.finditer(text):
        start = match.end() + 1 if text[match.end() : match.end() + 1] == '\n' else match.end()
        end = END.search(text, start)
        nxt = MARK.search(text, start)
        truncated = end is None or (nxt is not None and nxt.start() < end.start())
        stop = (nxt.start() if nxt else len(text)) if truncated else end.start()
        content = text[start:stop]
        fenced = FENCE.match(content)
        if fenced:
            content = fenced.group(1) + '\n'
        if content and not content.endswith('\n'):
            content += '\n'
        path = _normalize(match.group(1))
        found[path] = {
            'path': path,
            'text': content,
            'truncated': truncated,
        }  # the same path twice: the later wins
    out = []
    for n, entry in enumerate(found.values(), start=1):
        out.append({'n': n, **_check(work, entry)})
    return out


def _check(work, entry):
    path, content = entry['path'], entry['text']
    result = {
        'path': path,
        'text': content,
        'truncated': entry['truncated'],
        'warnings': [],
        'rejected': None,
    }
    suffix = '.' + path.rsplit('.', 1)[-1] if '.' in path.rsplit('/', 1)[-1] else ''
    try:
        target = work.resolve(path)
    except AppError:
        target = None
    if target is None:
        result['rejected'] = 'bad_path'
    elif suffix not in ITEM_SUFFIXES:
        result['rejected'] = 'not_item'
    result['new'] = not (target is not None and target.is_file())
    result['base_hash'] = None
    old = ''
    if target is not None and target.is_file():
        old = target.read_text(encoding='utf-8')
        result['base_hash'] = sha256_text(old)
    result['lines_before'] = len(old.splitlines()) if old else 0
    result['lines_after'] = len(content.splitlines())
    if result['rejected']:
        return result
    new_head, error = _head(content, suffix)
    if error:
        result['warnings'].append('bad_head')
    if WRAPPED_REF.search(content) and not WRAPPED_REF.search(old):
        result['warnings'].append('wrapped_ref')
    if OMISSION.search(content) and not OMISSION.search(old):
        result['warnings'].append('omission')
    if old:
        if len(old) > 300 and len(content) < 0.6 * len(old):
            result['warnings'].append('shrunk')
        old_head, _ = _head(old, suffix)
        if not error and str(old_head.get('id') or '') != str(new_head.get('id') or ''):
            result['warnings'].append('id_changed')
        if not error and str(old_head.get('kind') or '') != str(new_head.get('kind') or ''):
            result['warnings'].append('kind_changed')
    return result


def public(proposal):
    """A proposal as stored in the conversation and sent to the screen: everything but the text."""
    return {k: v for k, v in proposal.items() if k != 'text'}


def mock_reply(messages):
    """Stand-in answer for the mock connection: proposes the first file in scope with one added line."""
    system = messages[0]['content'] if messages else ''
    bodies = system.split('## 범위의 본문', 1)[1] if '## 범위의 본문' in system else ''
    match = MARK.search(bodies)
    if not match:
        return '(모의 응답) 범위에 본문이 들어간 파일이 없습니다. 범위를 파일로 정하면 그 파일을 고친 제안을 보여 드립니다.'
    path = match.group(1)
    body_start = match.end() + 1
    end = END.search(bodies, body_start)
    text = bodies[body_start : end.start() if end else len(bodies)].rstrip('\n')
    return (
        f'(모의 응답) {path}의 끝에 한 줄을 덧붙인 제안입니다. 설정 → LLM에서 실제 연결을 고르면 진짜 제안이 나옵니다.\n\n'
        f'{file_block(path, text + chr(10) + chr(10) + "(모의 에이전트가 덧붙인 줄)")}\n\n검토 탭에서 바뀐 부분을 확인하세요.'
    )
