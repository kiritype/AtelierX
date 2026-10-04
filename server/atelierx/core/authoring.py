"""Skeleton writing (04-authoring: 뼈대 작성). Questions come from the guideline; the draft is mocked until 3단계."""

import re
from itertools import pairwise

from .relations import Relations
from .works import KIND_PREFIX, next_code

SCALES = ('single', 'ensemble', 'simulation')


def questions(text):
    """List items under the `## 질문` heading (any language's "Questions" heading also works)."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            inside = line[3:].strip().lower() in ('질문', 'questions')
            continue
        if inside and line.startswith('- '):
            out.append(line[2:].strip())
    return out


def _names(answer, limit):
    """Rough guess at person names: the first word of each line ("서아, 17살 …"), or of each comma part on one line."""
    lines = [line for line in (answer or '').splitlines() if line.strip()]
    parts = lines if len(lines) > 1 else re.split(r'[,，、/]+', answer or '')
    names = []
    for part in parts:
        word = re.split(r'[\s,，、:·()]+', re.sub(r'^[\s\-*\d.)]+', '', part))[0]
        if 0 < len(word) <= 12 and word not in names:
            names.append(word)
    return names[:limit]


def mock_skeleton(work, scale, answers):
    """A deterministic placeholder draft that exercises the review screen until a real LLM is connected."""
    answered = [a for a in answers if a.get('answer', '').strip()]
    summary = '\n'.join(f'- {a["question"]}\n  {a["answer"].strip()}' for a in answered) or '- (답 없음)'
    people_answer = next(
        (a['answer'] for a in answers if '인물' in a['question'] or '캐릭터' in a['question']), ''
    )
    names = _names(people_answer, 1 if scale == 'single' else 3) or (
        ['캐릭터'] if scale == 'single' else ['인물 1', '인물 2']
    )
    used = [i['meta'].get('id') for i in work.index() if i['meta'].get('id')]

    def take(kind):
        code = next_code(KIND_PREFIX[kind], used)
        used.append(code)
        return code

    files = [
        {
            'path': '메인.md',
            'kind': 'main',
            'id': take('main'),
            'keywords': [],
            'body': f'# 진행 규칙 (모의 초안)\n\n아래 답을 바탕으로 LLM이 메인 프롬프트를 씁니다.\n\n{summary}\n',
        },
        {
            'path': '시작 상황.md',
            'kind': 'start',
            'id': take('start'),
            'keywords': [],
            'body': '(모의 초안) 첫 장면. {{user}}가 이야기에 처음 들어오는 순간을 씁니다.\n',
        },
    ]
    characters = []
    for name in names:
        code = take('character')
        characters.append(code)
        files.append(
            {
                'path': f'인물/{name}.md',
                'kind': 'character',
                'id': code,
                'keywords': [name],
                'body': f'## 식별\n\n- {name}. (모의 초안)\n\n## 성격\n\n- (확인 필요)\n\n## 말투\n\n- (확인 필요)\n\n'
                '## 외모\n\n- (확인 필요)\n\n## 의상\n\n### 평상복\n\n(확인 필요)\n',
            }
        )
    if scale != 'single':
        files.append(
            {
                'path': '세계관/배경.md',
                'kind': 'lorebook',
                'id': take('lorebook'),
                'keywords': ['배경'],
                'body': '(모의 초안) 장소·집단·규칙처럼 조건이 맞을 때만 필요한 설정.\n',
            }
        )
    existing = {i['path'].lower() for i in work.index()}
    for file in files:
        file['exists'] = file['path'].lower() in existing
    relations = [{'from': c, 'to': '{{user}}', 'kind': '(확인 필요)', 'calls': ''} for c in characters]
    relations += [{'from': a, 'to': b, 'kind': '(확인 필요)', 'calls': ''} for a, b in pairwise(characters)]
    return {'files': files, 'relations': relations}


def create_files(work, files, relations):
    """Create the chosen files (never overwrite) and add relation rows that are not there yet."""
    created, skipped = [], []
    for file in files:
        try:
            path = work.resolve(file['path'])
            if path.exists():
                skipped.append({'path': file['path'], 'why': 'exists'})
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            item = work.create_file(file['path'], file['kind'])
            changes = {'id': file.get('id')} if file.get('id') else {}
            if file.get('keywords'):
                changes['keywords'] = list(file['keywords'])
            work.save_item(item['path'], changes, file.get('body', ''), item['hash'])
            created.append(item['path'])
        except Exception as exc:  # noqa: BLE001 - report the file and keep going with the rest
            skipped.append({'path': file.get('path'), 'why': str(exc)})
    added = 0
    if relations:
        store = Relations(work)
        doc = store.load()
        known = {(r.get('from'), r.get('to')) for r in doc['relations']}
        for row in relations:
            if (row.get('from'), row.get('to')) not in known:
                doc['relations'].append(row)
                added += 1
        store.save(doc)
    return {'created': created, 'skipped': skipped, 'relations_added': added}
