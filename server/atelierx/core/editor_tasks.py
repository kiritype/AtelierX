"""Structured prompts and validation for editor review and formatting drafts."""

import re
from collections import Counter

REVIEW_FIXED = """너는 RP 챗봇 원고의 내용 검토자다. 문체를 고치지 말고 설정의 명확성, 일관성, 빠진 핵심 정보를 점검한다.
원고를 직접 수정하지 않는다. 결과는 JSON 하나: {\"issues\":[{\"reason\":\"문제\",\"evidence\":\"본문의 짧은 근거\",\"path\":\"받은 경로\"}]}.
문제가 없으면 빈 배열이다. 근거는 받은 본문에서 그대로 인용한다. 억측이나 취향 평가는 쓰지 않는다."""

CONSISTENCY_FIXED = """너는 RP 챗봇 설정들의 상호 일관성을 검토한다. 원고를 직접 수정하지 않는다.
결과는 JSON 하나: {\"issues\":[{\"reason\":\"서로 충돌하거나 모호한 점\",\"evidence\":\"각 항목의 짧은 근거\",\"path\":\"관련 경로들\"}]}.
문제가 없으면 빈 배열이다. 비교 대상으로 받은 항목만 비교하고, 근거는 본문에서 그대로 인용한다."""

FORMAT_FIXED = """너는 RP 챗봇 Markdown 원고의 편집자다. JSON 하나로 {\"text\":\"편집한 Markdown 본문\",\"note\":\"변경 요약\"}만 답한다.
정보, 의도, 사실, {{...}} 자리표시자, JSX 컴포넌트 표기를 보존한다. 원고 밖의 설명은 넣지 않는다.
일반 정돈은 Markdown 문단과 목록을 읽기 쉽게 다듬되 내용과 순서를 유지한다. 템플릿 재구성은 제공된 템플릿을 따르되 원문 정보를 모두 적절한 곳에 옮긴다."""


def review_messages(path, body, guideline='', instruction=''):
    extra = f'\n\n사용자 요청:\n{instruction}' if instruction else ''
    return [
        {'role': 'system', 'content': '\n\n'.join(filter(None, [REVIEW_FIXED, guideline]))},
        {'role': 'user', 'content': f'경로: {path}{extra}\n\n본문:\n{body}'},
    ]


def consistency_messages(items, guideline='', instruction=''):
    parts = ['아래에서 명시한 경로들만 서로 비교한다.']
    if instruction:
        parts.append('사용자 요청:\n' + instruction)
    parts.extend(f'## 경로: {item["path"]}\n{item["body"]}' for item in items)
    return [
        {'role': 'system', 'content': '\n\n'.join(filter(None, [CONSISTENCY_FIXED, guideline]))},
        {'role': 'user', 'content': '\n\n'.join(parts)},
    ]


def format_messages(path, body, mode='tidy', template='', instruction='', guideline=''):
    directive = '정돈' if mode == 'tidy' else '템플릿 재구성'
    parts = [f'편집 방식: {directive}', f'경로: {path}']
    if template:
        parts.append('적용할 템플릿:\n' + template)
    if instruction:
        parts.append('추가 요청:\n' + instruction)
    parts.append('원고 본문:\n' + body)
    return [
        {'role': 'system', 'content': '\n\n'.join(filter(None, [FORMAT_FIXED, guideline]))},
        {'role': 'user', 'content': '\n\n'.join(parts)},
    ]


def issues_ok(data):
    return isinstance(data, dict) and isinstance(data.get('issues'), list) and all(
        isinstance(row, dict) and isinstance(row.get('reason'), str) and isinstance(row.get('evidence'), str)
        and isinstance(row.get('path'), str) for row in data['issues']
    )


def edit_ok(data):
    return isinstance(data, dict) and isinstance(data.get('text'), str) and isinstance(data.get('note', ''), str)


PLACEHOLDER = re.compile(r'\{\{[^{}]+\}\}')
JSX_TAG = re.compile(r'</?[A-Z][A-Za-z0-9_.]*(?:\s[^<>]*?)?\s*/?>', re.DOTALL)


def preserves_protected(original, edited):
    """Formatting may move protected syntax but must preserve every exact occurrence."""
    for pattern in (PLACEHOLDER, JSX_TAG):
        if Counter(pattern.findall(original)) != Counter(pattern.findall(edited)):
            return False
    return True


