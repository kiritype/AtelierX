"""Requests and result parsing for the LLM jobs (03-llm: 요청 조립).

The app's fixed instructions own the output shape; guidelines (editable) own the content rules.
"""

import json

from .drafts import split_blocks
from .i18n import AppError, Msg
from .llm import parse_json
from .works import KIND_PREFIX, next_code


def _bad_answer(raw):
    return AppError(
        Msg(
            'server.llm.bad_answer',
            'The model did not answer in the expected format. Answer start: {start}',
            start=raw[:160],
        ),
        502,
    )


async def ask_json(llm, task, messages, work_id, check, override=None):
    """Ask once, retry once if the shape is wrong (03-llm: 형식이 틀린 응답)."""
    last = ''
    for _ in range(2):
        answer = await llm.complete(task, messages, work_id=work_id, override=override, json_mode=True)
        last = answer['text']
        data = parse_json(last)
        if data is not None and check(data):
            return data, answer
    raise _bad_answer(last)


# --- compression -------------------------------------------------------------------------------------------------
COMPRESSION_FIXED = """너는 RP 챗봇 원고를 줄이는 편집자다. 아래 가이드라인을 지켜 원고를 압축한다.
원고는 번호(n)가 붙은 블록 목록(JSON)으로 받는다. from·to에는 받은 n을 그대로 쓴다. 결과는 JSON 하나로만 답한다. 설명이나 다른 글은 쓰지 않는다.

형식:
{"note": "이번 압축의 요지 한 줄", "blocks": [{"from": 1, "to": 1, "text": "블록 1의 압축 결과"}, ...]}

- 원래 블록 순서대로 쓴다. 이어진 블록을 하나로 합쳤으면 from과 to에 그 범위를 쓴다.
- 지운 블록은 text를 빈 문자열로 둔다.
- 제목 블록(#로 시작)은 글자 그대로 두고, 다른 블록과 합치지 않는다.
- 잠긴 블록은 글자 그대로 둔다."""


def compression_messages(body, guideline, platform, target_size, locked):
    blocks = split_blocks(body)
    # Explicit numbers in JSON keep the model from counting the request's own lines as blocks.
    numbered = json.dumps(
        {'blocks': [{'n': b['n'], 'text': b['text']} for b in blocks]}, ensure_ascii=False, indent=1
    )
    size = len(body.encode('utf-8'))
    task = [f'현재 용량: {size} B']
    if target_size:
        task.append(f'목표 용량: {target_size} B 이하')
    if locked:
        task.append('잠긴 블록 번호: ' + ', '.join(str(n) for n in locked))
    system = '\n\n'.join(
        filter(None, [COMPRESSION_FIXED, platform and f'# 플랫폼 가이드라인\n{platform}', guideline])
    )
    return blocks, [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': '\n'.join(task) + '\n\n원고 블록:\n' + numbered},
    ]


ROUND_HINTS = (
    '이번에는 뜻을 지키며 가볍게 줄인다.',
    '이번에는 더 과감하게 줄인다. 목록·짧은 구절로 바꾸고 꾸밈말을 모두 뺀다.',
    '이번에는 핵심 사실만 남길 만큼 가장 짧게 줄인다.',
)


def compression_round(messages, n):
    """Each candidate asks for a different strength so the candidates actually differ."""
    hint = ROUND_HINTS[min(n, len(ROUND_HINTS) - 1)]
    return [*messages[:-1], {**messages[-1], 'content': messages[-1]['content'] + '\n\n' + hint}]


def compression_candidate(data, blocks, locked):
    """Turn the model's blocks into a candidate; uncovered original blocks are kept as they were."""
    count = len(blocks)
    out, covered = [], set()
    for row in data.get('blocks', []):
        try:
            start, end = int(row.get('from')), int(row.get('to', row.get('from')))
        except (TypeError, ValueError):
            continue
        if not (1 <= start <= end <= count) or covered & set(range(start, end + 1)):
            continue
        if start != end and any(blocks[n - 1]['text'].startswith('#') for n in range(start, end + 1)):
            continue  # a heading merged into other blocks: keep those blocks as they were
        if start == end and blocks[start - 1]['text'].startswith('#'):
            row = {**row, 'text': blocks[start - 1]['text']}  # headings stay word for word
        if any(n in locked for n in range(start, end + 1)):
            text = '\n\n'.join(b['text'] for b in blocks[start - 1 : end])
        else:
            text = str(row.get('text', '')).strip()
        covered |= set(range(start, end + 1))
        out.append({'from': start, 'to': end, 'text': text})
    for block in blocks:
        if block['n'] not in covered:
            out.append({'from': block['n'], 'to': block['n'], 'text': block['text']})
    out.sort(key=lambda r: r['from'])
    return {
        'round': 1,
        'note': str(data.get('note', ''))[:200],
        'size': len('\n\n'.join(r['text'] for r in out if r['text']).encode('utf-8')),
        'blocks': out,
        'checks': {},
    }


def compression_ok(data):
    return isinstance(data, dict) and isinstance(data.get('blocks'), list) and len(data['blocks']) > 0


# --- authoring ---------------------------------------------------------------------------------------------------
AUTHORING_FIXED = """너는 RP 챗봇 원고의 뼈대를 만드는 작가다. 사용자의 답과 가이드라인을 보고 작품의 파일 구성과 초안을 만든다.
결과는 JSON 하나로만 답한다. 설명이나 다른 글은 쓰지 않는다.

형식:
{"files": [{"path": "폴더/이름.md", "kind": "main|start|lorebook|character", "keywords": ["키워드"], "body": "본문(Markdown)"}],
 "relations": [{"from": "인물 이름 또는 {{user}}", "to": "인물 이름 또는 {{user}}", "kind": "관계", "calls": "부르는 호칭"}]}

- path는 가이드라인의 파일 구성을 따른다. 캐릭터 파일 이름은 그 인물의 이름이다(인물/이름.md).
- main은 정확히 하나. start는 하나 이상.
- character 본문은 섹션 제목을 쓴다: {sections}. 의상은 "## 의상" 아래 "### 의상 이름"으로 한 벌씩.
- lorebook과 character에는 keywords를 넣는다. main과 start는 빈 목록.
- 사용자는 {{user}}로 쓴다. {{user}} 바로 뒤에 조사를 붙이지 않는다.
- 답이 빈 질문은 무난하게 채우되 그 부분 끝에 (확인 필요)를 붙인다."""

ALLOWED_KINDS = ('main', 'start', 'lorebook', 'character')


def authoring_messages(answers, guideline, platform, sections, scale):
    system = '\n\n'.join(
        filter(
            None,
            [
                AUTHORING_FIXED.replace('{sections}', ', '.join(f'"## {t}"' for t in sections)),
                platform and f'# 플랫폼 가이드라인\n{platform}',
                guideline,
            ],
        )
    )
    qa = '\n\n'.join(f'Q. {a["question"]}\nA. {a.get("answer", "").strip() or "(빈 답)"}' for a in answers)
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': f'규모: {scale}\n\n{qa}'},
    ]


def authoring_ok(data):
    return isinstance(data, dict) and isinstance(data.get('files'), list) and len(data['files']) > 0


def authoring_skeleton(data, work):
    """Assign IDs by kind and turn relation names into character IDs; mark files that already exist."""
    used = [i['meta'].get('id') for i in work.index() if i['meta'].get('id')]
    existing = {i['path'].lower() for i in work.index()}
    files, by_name = [], {}
    for raw in data.get('files', []):
        path = str(raw.get('path', '')).strip().lstrip('/')
        kind = raw.get('kind') if raw.get('kind') in ALLOWED_KINDS else 'lorebook'
        if not path:
            continue
        if not path.endswith('.md'):
            path += '.md'
        code = next_code(KIND_PREFIX[kind], used)
        used.append(code)
        keywords = [str(k).strip() for k in raw.get('keywords') or [] if str(k).strip()]
        files.append(
            {
                'path': path,
                'kind': kind,
                'id': code,
                'keywords': keywords if kind in ('lorebook', 'character') else [],
                'body': str(raw.get('body', '')).strip() + '\n',
                'exists': path.lower() in existing,
            }
        )
        if kind == 'character':
            by_name[path.rsplit('/', 1)[-1][:-3]] = code
    for item in work.index():
        if item['kind'] == 'character' and item['meta'].get('id'):
            by_name.setdefault(item['name'], item['meta']['id'])

    def person(name):
        name = str(name or '').strip()
        return name if name == '{{user}}' else by_name.get(name)

    relations = []
    for raw in data.get('relations', []) or []:
        a, b = person(raw.get('from')), person(raw.get('to'))
        if a and b and a != b:
            relations.append(
                {'from': a, 'to': b, 'kind': str(raw.get('kind', '')), 'calls': str(raw.get('calls', ''))}
            )
    return {'files': files, 'relations': relations}


# --- image prompt ------------------------------------------------------------------------------------------------
IMAGE_FIXED = """너는 캐릭터 설정을 이미지 생성용 태그로 바꾸는 도우미다. 아래 가이드라인을 지킨다.
결과는 JSON 하나로만 답한다. 설명이나 다른 글은 쓰지 않는다.

형식:
{"appearance": {"prompt": ["태그"], "negative": ["태그"], "evidence": ["근거 문장"]},
 "outfits": [{"name": "의상 이름", "slots": {"부위 ID": ["태그"]}, "negative": ["태그"], "evidence": ["근거 문장"]}]}

- 인물 본문 전체를 받는다. 이 인물의 현재 외모·의상만 쓴다. 다른 인물, 과거, 가정(만약 ~라면), 꿈·상상은 뺀다.
- evidence에는 태그의 근거가 된 본문 문장을 고치지 않고 그대로 옮긴다. 줄이거나 바꿔 쓰지 않는다.
- 기존 의상 목록에 있는 옷이면 그 이름을 그대로 쓴다. 목록에 없는 옷만 짧은 이름을 새로 짓는다.
- 본문에 의상이 없으면 outfits는 빈 목록으로 둔다.
- slots의 키는 다음 부위 ID만 쓴다: {slots}. 본문에 없는 부위는 넣지 않는다."""

IMAGE_RANGE_FIXED = """너는 캐릭터 설정의 일부를 이미지 생성용 태그로 바꾸는 도우미다. 아래 가이드라인을 지킨다.
결과는 JSON 하나로만 답한다. 설명이나 다른 글은 쓰지 않는다.

받은 글은 사람이 고른 {what} 묘사다. 이 글에 적힌 것만 태그로 바꾼다. 다른 인물, 과거, 가정은 뺀다.

형식:
{format}"""


def _slot_list(slots):
    return ', '.join(f'{s["id"]}({s["name"]})' for s in slots)


def image_messages(body, existing, slots, guideline):
    """Whole-text conversion (#150): the character's text and the names of the outfits it has."""
    system = '\n\n'.join(filter(None, [IMAGE_FIXED.replace('{slots}', _slot_list(slots)), guideline]))
    names = '\n'.join(f'- {name}' for name in existing) or '(없음)'
    user = f'# 기존 의상\n{names}\n\n# 인물 본문\n{body.strip() or "(없음)"}'
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def image_range_messages(text, part, slots, guideline):
    """Range conversion (#150): only the chosen text, into one part."""
    if part == 'appearance':
        what, form = '외모', '{"prompt": ["태그"], "negative": ["태그"]}'
    else:
        what = '의상'
        form = (
            '{"slots": {"부위 ID": ["태그"]}, "negative": ["태그"]}\n\n'
            f'- slots의 키는 다음 부위 ID만 쓴다: {_slot_list(slots)}. 글에 없는 부위는 넣지 않는다.'
        )
    fixed = IMAGE_RANGE_FIXED.replace('{what}', what).replace('{format}', form)
    system = '\n\n'.join(filter(None, [fixed, guideline]))
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': text.strip()}]


def image_ok(data):
    return (
        isinstance(data, dict)
        and isinstance(data.get('appearance'), dict)
        and isinstance(data.get('outfits'), list)
    )


def image_range_ok(data):
    return isinstance(data, dict) and (isinstance(data.get('prompt'), list) or isinstance(data.get('slots'), dict))


def tags(values):
    out = []
    for value in values or []:
        tag = str(value).strip()
        if tag and tag not in out:
            out.append(tag)
    return out


# --- relations from bodies ---------------------------------------------------------------------------------------
RELATIONS_FIXED = """너는 RP 챗봇 원고에서 인물 관계를 정리하는 편집자다. 캐릭터 본문들을 읽고 관계·호칭·기준 사실 후보를 뽑는다.
결과는 JSON 하나로만 답한다. 설명이나 다른 글은 쓰지 않는다.

형식:
{"relations": [{"from": "인물 이름", "to": "인물 이름 또는 {{user}}", "kind": "관계", "calls": "from이 to를 부르는 호칭", "quote": "근거 인용"}],
 "facts": [{"subject": "인물 이름", "key": "항목(나이, 학년, 소속 등)", "value": "값", "quote": "근거 인용"}]}

- 본문에 실제로 적힌 것만 뽑는다. 근거 인용은 본문의 글을 그대로 짧게 옮긴다. 인용할 수 없으면 넣지 않는다.
- 관계는 방향이 있다. 서로 다르면 두 줄로 쓴다. 호칭이 없으면 calls는 빈 문자열.
- 인물 이름은 받은 이름 그대로 쓴다. 사용자는 {{user}}."""


def relations_messages(characters, others, existing):
    people = ', '.join(c['name'] for c in characters)
    parts = [f'인물 목록: {people}, {{{{user}}}}']
    if existing:
        parts.append('이미 정리된 관계(참고):\n' + '\n'.join(existing))
    for item in characters:
        parts.append(f'# 캐릭터: {item["name"]}\n{item["body"].strip()}')
    for item in others:
        parts.append(f'# 설정: {item["name"]}\n{item["body"].strip()}')
    return [{'role': 'system', 'content': RELATIONS_FIXED}, {'role': 'user', 'content': '\n\n'.join(parts)}]


def relations_ok(data):
    return (
        isinstance(data, dict)
        and isinstance(data.get('relations', []), list)
        and isinstance(data.get('facts', []), list)
    )


# --- consistency -------------------------------------------------------------------------------------------------
CONSISTENCY_FIXED = """너는 RP 챗봇 원고의 모순을 찾는 검토자다. 아래 가이드라인을 따른다.
결과는 JSON 하나로만 답한다. 설명이나 다른 글은 쓰지 않는다. 문제가 없으면 {"issues": []}.

형식:
{"issues": [{"type": "mismatch|missing|ambiguous", "items": ["관련 항목 ID"], "quote": "근거 인용(본문 그대로)",
  "quote_item": "인용이 있는 항목 ID", "explain": "무엇이 어긋나는지 한 줄",
  "suggest": {"item": "고칠 항목 ID", "find": "바꿀 본문 글(그대로)", "replace": "새 글"} 또는 null}]}

- 항목 ID는 받은 [ID] 그대로 쓴다. 관계도는 ID "관계도"로 가리킨다.
- 인용과 find는 본문에 있는 글을 한 글자도 바꾸지 않고 옮긴다."""


def consistency_messages(person, bundle, relations, facts, glossary, guideline):
    system = '\n\n'.join(filter(None, [CONSISTENCY_FIXED, guideline]))
    parts = [f'검사 대상 인물: {person}']
    if relations or facts:
        parts.append('# [관계도]\n' + '\n'.join(relations + facts))
    if glossary:
        parts.append('# 용어집\n' + '\n'.join(glossary))
    for item in bundle:
        parts.append(f'# [{item["id"]}] {item["name"]}\n{item["body"].strip()}')
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': '\n\n'.join(parts)}]


def consistency_ok(data):
    return isinstance(data, dict) and isinstance(data.get('issues'), list)


# --- JSX prompt text ---------------------------------------------------------------------------------------------
JSX_PROMPT_FIXED = """너는 RP 챗봇 프롬프트 작가다. 챗봇이 응답에 컴포넌트를 넣도록 프롬프트에 넣을 문구를 쓴다.
결과는 JSON 하나로만 답한다: {"text": "문구(Markdown)"}

문구에 넣을 것: 출력 양식(요소 한 줄), 각 필드의 뜻, 언제 어떻게 갱신하는지, 실제 값을 넣은 예시 하나 이상.
- 요소 표기: <{name} 속성='JSON 값' /> 형식. 속성 값은 작은따옴표로 감싼 JSON이다.
- 예시에는 실제 값을 넣어 그대로 읽히게 쓴다(자리표시 값은 양식 줄에만)."""


def jsx_prompt_messages(name, source, props, guideline, platform, feedback):
    system = '\n\n'.join(
        filter(
            None,
            [
                JSX_PROMPT_FIXED.replace('{name}', name),
                platform and f'# 플랫폼 가이드라인\n{platform}',
                guideline,
            ],
        )
    )
    parts = [
        f'컴포넌트 이름: {name}',
        f'# 소스\n{source.strip()}',
        f'# 기준 예시 props\n{json.dumps(props, ensure_ascii=False)}',
    ]
    if feedback:
        parts.append(f'# 추가 요청\n{feedback}')
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': '\n\n'.join(parts)}]


def jsx_prompt_ok(data):
    return isinstance(data, dict) and isinstance(data.get('text'), str) and data['text'].strip() != ''
