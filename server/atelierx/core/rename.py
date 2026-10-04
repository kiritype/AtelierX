"""Rename a name across the work (04-authoring: 이름 일괄 변경). Particles are never rewritten, only flagged."""

import re

from .relations import Relations

# Particles whose form depends on the final consonant of the word before them.
PARTICLES = ('이랑', '으로', '은', '는', '이', '가', '을', '를', '과', '와', '아', '야', '랑', '로')


def has_batchim(char):
    code = ord(char) - 0xAC00
    return 0 <= code <= 11171 and code % 28 != 0


def _josa_risk(find, replace, after):
    """True when the following particle may read wrong because the final consonant changes."""
    if not find or not replace or not after:
        return False
    if has_batchim(find[-1]) == has_batchim(replace[-1]):
        return False
    return any(after.startswith(p) for p in PARTICLES)


def _line_of(text, index):
    start = text.rfind('\n', 0, index) + 1
    end = text.find('\n', index)
    return text[start : end if end >= 0 else len(text)], text.count('\n', 0, index) + 1


def _renamed(path, name):
    folder, _, filename = path.rpartition('/')
    return (f'{folder}/' if folder else '') + f'{name}.{filename.rsplit(".", 1)[1]}'


def preview(work, find, replace, targets=None):
    """Every place `find` occurs: bodies, keywords, relation-map calls, file names equal to it."""
    targets = set(targets or ('body', 'keyword', 'relation', 'filename'))
    hits = []
    if not find:
        return hits
    for item in work.index_with_bodies():
        if 'body' in targets:
            for match in re.finditer(re.escape(find), item['body']):
                line, number = _line_of(item['body'], match.start())
                after = item['body'][match.end() : match.end() + 2]
                hits.append(
                    {
                        'id': f'{item["path"]}|body|{match.start()}',
                        'path': item['path'],
                        'where': 'body',
                        'line': number,
                        'before': line.strip(),
                        'after': line.replace(find, replace).strip(),
                        'josa': _josa_risk(find, replace, after),
                    }
                )
        if 'keyword' in targets:
            for n, keyword in enumerate(item['meta'].get('keywords') or []):
                if find in str(keyword):
                    hits.append(
                        {
                            'id': f'{item["path"]}|keyword|{n}',
                            'path': item['path'],
                            'where': 'keyword',
                            'before': str(keyword),
                            'after': str(keyword).replace(find, replace),
                            'josa': False,
                        }
                    )
        if 'filename' in targets and item['name'] == find:
            hits.append(
                {
                    'id': f'{item["path"]}|filename|0',
                    'path': item['path'],
                    'where': 'filename',
                    'before': item['path'],
                    'after': _renamed(item['path'], replace),
                    'josa': False,
                }
            )
    if 'relation' in targets:
        doc = Relations(work).load()
        for n, row in enumerate(doc['relations']):
            if find in str(row.get('calls', '')):
                hits.append(
                    {
                        'id': f'relations|relation|{n}',
                        'path': None,
                        'where': 'relation',
                        'before': row['calls'],
                        'after': row['calls'].replace(find, replace),
                        'josa': False,
                    }
                )
        for n, person in enumerate(doc['people']):
            if find in str(person.get('name', '')):
                hits.append(
                    {
                        'id': f'relations|person|{n}',
                        'path': None,
                        'where': 'relation',
                        'before': person['name'],
                        'after': person['name'].replace(find, replace),
                        'josa': False,
                    }
                )
    return hits


def apply(work, find, replace, chosen):
    """Change only the chosen hits. Body offsets are applied from the end so earlier ones stay valid."""
    chosen = set(chosen)
    changed = set()
    renames = []
    for item in work.index_with_bodies():
        offsets = sorted(
            (int(h.split('|')[2]) for h in chosen if h.startswith(f'{item["path"]}|body|')), reverse=True
        )
        body = item['body']
        for offset in offsets:
            if body[offset : offset + len(find)] == find:
                body = body[:offset] + replace + body[offset + len(find) :]
        keywords = item['meta'].get('keywords')
        meta_changes = {}
        if keywords:
            new_keywords = [
                str(k).replace(find, replace) if f'{item["path"]}|keyword|{n}' in chosen else k
                for n, k in enumerate(keywords)
            ]
            if new_keywords != keywords:
                meta_changes['keywords'] = new_keywords
        if body != item['body'] or meta_changes:
            work.save_item(item['path'], meta_changes or None, body, item['hash'])
            changed.add(item['path'])
        if f'{item["path"]}|filename|0' in chosen:
            renames.append(item['path'])
    store = Relations(work)
    doc = store.load()
    touched = False
    for n, row in enumerate(doc['relations']):
        if f'relations|relation|{n}' in chosen:
            row['calls'] = row['calls'].replace(find, replace)
            touched = True
    for n, person in enumerate(doc['people']):
        if f'relations|person|{n}' in chosen:
            person['name'] = person['name'].replace(find, replace)
            touched = True
    if touched:
        store.save(doc)
    moved = []
    for path in renames:
        moved.append(work.move(path, _renamed(path, replace)))
    return {'changed': sorted(changed), 'moved': moved, 'relations': touched}
