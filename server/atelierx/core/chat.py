"""Chat test context assembly (08-chat-test: 맥락 조립). The reply itself is mocked until 3단계."""

import re

from . import review
from .count import measure
from .i18n import AppError
from .jsx import Props


def _matches(keyword, text, lore):
    keyword = str(keyword)
    if not keyword:
        return False
    if not lore.get('case_sensitive'):
        keyword, text = keyword.lower(), text.lower()
    if lore.get('match') == 'word':
        return re.search(rf'(?<!\w){re.escape(keyword)}(?!\w)', text) is not None
    return keyword in text


def substitute(text, user_name, char_name):
    if user_name:
        text = text.replace('{{user}}', user_name)
    if char_name:
        text = text.replace('{{char}}', char_name)
    return text


def assemble(work, effective, history, message, persona=None):
    """Pick lorebook items for the next turn and build the system context.

    ``history`` is a list of ``{'role': 'user'|'assistant', 'text': …}``; ``message`` is the new user text.
    """
    lore = effective['values']['lorebook']
    doc = work.doc()
    items = [work.read_item(p) for p in work.item_paths()]
    enabled = [i for i in items if i['meta'].get('enabled', True) and i['kind'] != 'note']
    mains = [i for i in enabled if i['kind'] == 'main']
    scan_roles = lore.get('scan', {}).get('roles', ['user', 'assistant'])
    turns = [*history, {'role': 'user', 'text': message}]
    window = [t['text'] for t in turns if t['role'] in scan_roles][
        -int(lore.get('scan', {}).get('messages', 2)) :
    ]
    scan_text = '\n'.join(window)

    picked, skipped = [], []
    for item in enabled:
        if item['kind'] not in ('lorebook', 'character'):
            continue
        meta = item['meta']
        if meta.get('always'):
            picked.append({'item': item, 'reason': 'always', 'keyword': None})
            continue
        hit = next((k for k in meta.get('keywords') or [] if _matches(k, scan_text, lore)), None)
        if hit is not None:
            picked.append({'item': item, 'reason': 'keyword', 'keyword': hit})

    picked.sort(key=lambda p: (p['reason'] != 'always', -int(p['item']['meta'].get('priority') or 0)))
    budget = (lore.get('budget') or {}).get('max')
    max_active = lore.get('max_active')
    used, kept = 0, []
    for entry in picked:
        size = measure(entry['item']['body'], effective['values'].get('count'))[0]
        if (budget and used + size > budget) or (max_active and len(kept) >= max_active):
            skipped.append(
                {**_brief(entry), 'why': 'budget' if budget and used + size > budget else 'max_active'}
            )
            continue
        used += size
        kept.append(entry)

    char_name = None
    if doc.get('char'):
        char_item = next((i for i in items if i['meta'].get('id') == doc['char']), None)
        char_name = char_item['name'] if char_item else None
    user_name = (persona or {}).get('name') or '사용자'

    parts = [m['body'].strip() for m in mains[:1]] + [e['item']['body'].strip() for e in kept]
    if persona and persona.get('description'):
        parts.append(f'사용자: {persona["description"]}')
    system = substitute('\n\n'.join(parts), user_name, char_name)
    return {
        'main': mains[0]['path'] if mains else None,
        'picked': [_brief(e) for e in kept],
        'skipped': skipped,
        'lorebook_size': used,
        'system': system,
        'system_size': len(system.encode('utf-8')),
        'char_name': char_name,
        'user_name': user_name,
        'lorebook': [
            {'path': i['path'], 'id': i['meta'].get('id'), 'name': i['name'], 'kind': i['kind']}
            for i in enabled
            if i['kind'] in ('lorebook', 'character')
        ],
        'components': [
            _component(work, i, review.response_rule(effective)) for i in enabled if i['kind'] == 'jsx'
        ],
    }


def _component(work, item, rule=None):
    """A JSX item as the chat sees it: the element name is the file name (07-jsx: 응답 속 컴포넌트 표기).

    ``props`` are those of the default example's call, read with the work's response rule.
    """
    props = {}
    item_id, default = item['meta'].get('id'), item['meta'].get('default_props')
    if item_id and default:
        try:
            props = Props(work, item_id, item['name']).props(default, rule)
        except AppError:
            props = {}
    return {'path': item['path'], 'id': item_id, 'name': item['name'], 'props': props}


def _brief(entry):
    item = entry['item']
    return {
        'path': item['path'],
        'id': item['meta'].get('id'),
        'name': item['name'],
        'reason': entry['reason'],
        'keyword': entry['keyword'],
        'size': item['size'],
    }


def messages(context, history, message):
    """Chat messages for the model: the assembled system context, then the conversation with reserved refs replaced."""
    user, char = context['user_name'], context['char_name']
    out = [{'role': 'system', 'content': context['system']}]
    for turn in history:
        if turn.get('role') in ('user', 'assistant') and turn.get('text'):
            out.append({'role': turn['role'], 'content': substitute(turn['text'], user, char)})
    out.append({'role': 'user', 'content': substitute(message, user, char)})
    return out
