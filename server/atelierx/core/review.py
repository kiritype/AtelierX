"""Reviewable results of the authoring-support jobs (04-authoring, 07-jsx) and applying what the user picks."""

import hashlib
import json
import re

from .fsutil import read_json, write_json
from .relations import Glossary, Relations
from .works import now_iso

USER = '{{user}}'


# --- names ↔ IDs -------------------------------------------------------------------------------------------------
def people_index(work):
    """Name → ID for characters (file name) and extra people in the relation map."""
    by_name = {}
    for item in work.index():
        if item['kind'] == 'character' and item['meta'].get('id'):
            by_name[item['name']] = item['meta']['id']
    for person in Relations(work).load()['people']:
        if person.get('name'):
            by_name.setdefault(person['name'], person['id'])
    return by_name


# --- relations from bodies ---------------------------------------------------------------------------------------
def relation_rows(work, data):
    """Model rows → reviewable rows with IDs and a status against the current map: new / same / different."""
    by_name = people_index(work)
    doc = Relations(work).load()
    known_ids = set(by_name.values()) | {p['id'] for p in doc['people']}
    new_people = {}

    def person(name):
        name = str(name or '').strip()
        if name in (USER, '{{char}}'):
            return name
        if name in by_name:
            return by_name[name]
        if not name:
            return None
        if name not in new_people:
            n = 1
            while f'N{n:02d}' in known_ids or f'N{n:02d}' in new_people.values():
                n += 1
            new_people[name] = f'N{n:02d}'
        return new_people[name]

    rows = []
    for raw in data.get('relations', []) or []:
        a, b = person(raw.get('from')), person(raw.get('to'))
        if not a or not b or a == b:
            continue
        row = {
            'type': 'relation',
            'from': a,
            'to': b,
            'kind': str(raw.get('kind', '')),
            'calls': str(raw.get('calls', '')),
        }
        old = next((r for r in doc['relations'] if r.get('from') == a and r.get('to') == b), None)
        row['status'] = (
            'new'
            if old is None
            else 'same'
            if (old.get('kind'), old.get('calls')) == (row['kind'], row['calls'])
            else 'different'
        )
        row['old'] = old
        row['quote'] = str(raw.get('quote', ''))
        rows.append(row)
    for raw in data.get('facts', []) or []:
        subject, key = person(raw.get('subject')), str(raw.get('key', '')).strip()
        if not subject or not key:
            continue
        old = next((f for f in doc['facts'] if f.get('subject') == subject and f.get('key') == key), None)
        value = str(raw.get('value', ''))
        rows.append(
            {
                'type': 'fact',
                'subject': subject,
                'key': key,
                'value': value,
                'status': 'new' if old is None else 'same' if old.get('value') == value else 'different',
                'old': old,
                'quote': str(raw.get('quote', '')),
            }
        )
    people = [{'id': pid, 'name': name} for name, pid in new_people.items()]
    return {'rows': rows, 'people': people}


def apply_relation_rows(work, rows, people):
    """Add chosen rows; a "different" row replaces the old one (the user picked it on purpose)."""
    store = Relations(work)
    doc = store.load()
    used = {r['from'] for r in rows if r.get('type') == 'relation'} | {
        r['to'] for r in rows if r.get('type') == 'relation'
    }
    used |= {r['subject'] for r in rows if r.get('type') == 'fact'}
    for person in people:
        if person['id'] in used and all(p['id'] != person['id'] for p in doc['people']):
            doc['people'].append({'id': person['id'], 'name': person['name']})
    added = 0
    for row in rows:
        if row.get('type') == 'relation':
            doc['relations'] = [
                r for r in doc['relations'] if not (r.get('from') == row['from'] and r.get('to') == row['to'])
            ]
            doc['relations'].append({k: row[k] for k in ('from', 'to', 'kind', 'calls')})
        elif row.get('type') == 'fact':
            doc['facts'] = [
                f
                for f in doc['facts']
                if not (f.get('subject') == row['subject'] and f.get('key') == row['key'])
            ]
            doc['facts'].append({k: row[k] for k in ('subject', 'key', 'value')})
        else:
            continue
        added += 1
    store.save(doc)
    return {'added': added}


# --- consistency -------------------------------------------------------------------------------------------------
def consistency_bundles(work, scope_ids=None):
    """One bundle per character: its body, items whose body mentions its name, and the map rows about it."""
    items = [
        i
        for i in work.index_with_bodies()
        if i['kind'] != 'note' and i['meta'].get('enabled', True) and i['meta'].get('id')
    ]
    doc = Relations(work).load()
    names = {i['meta']['id']: i['name'] for i in items if i['kind'] == 'character'}
    names.update({p['id']: p.get('name', p['id']) for p in doc['people']})
    names[USER] = USER

    def label(pid):
        return f'{names.get(pid, pid)}({pid})'

    bundles = []
    for char in [i for i in items if i['kind'] == 'character']:
        cid = char['meta']['id']
        if scope_ids and cid not in scope_ids:
            continue
        others = [i for i in items if i is not char and (char['name'] in i['body'] or cid in i['body'])]
        relations = [
            f'{label(r["from"])} → {label(r["to"])}: {r.get("kind", "")} / 호칭 "{r.get("calls", "")}"'
            for r in doc['relations']
            if cid in (r.get('from'), r.get('to'))
        ]
        facts = [
            f'{label(f["subject"])} {f["key"]}: {f["value"]}' for f in doc['facts'] if f.get('subject') == cid
        ]
        bundles.append(
            {
                'person': char['name'],
                'items': [
                    {'id': i['meta']['id'], 'name': i['name'], 'body': i['body'], 'path': i['path']}
                    for i in [char, *others]
                ],
                'relations': relations,
                'facts': facts,
            }
        )
    return bundles


def glossary_lines(work):
    return [f'{t["use"]} (피할 표기: {", ".join(t["avoid"])})' for t in Glossary(work).load()['terms']]


def issue_hash(issue):
    key = '|'.join([issue.get('type', ''), ','.join(sorted(issue.get('items', []))), issue.get('quote', '')])
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def normalize_issues(work, raw_issues):
    """Check quotes and suggestions against the real text; fold issues the user ignored before."""
    bodies = {i['meta'].get('id'): i for i in work.index_with_bodies() if i['meta'].get('id')}
    ignored = {entry['hash'] for entry in (read_json(work.app / 'consistency.json') or {}).get('ignored', [])}
    out, seen = [], set()
    for raw in raw_issues or []:
        if not isinstance(raw, dict):
            continue
        issue = {
            'type': raw.get('type')
            if raw.get('type') in ('mismatch', 'missing', 'ambiguous')
            else 'ambiguous',
            'items': [str(i) for i in raw.get('items') or [] if str(i) in bodies or str(i) == '관계도'],
            'quote': str(raw.get('quote', '')).strip(),
            'quote_item': str(raw.get('quote_item', '')),
            'explain': str(raw.get('explain', '')).strip(),
            'suggest': None,
            'status': 'open',
        }
        quote_in = [
            i
            for i in [issue['quote_item'], *issue['items']]
            if i in bodies and issue['quote'] and issue['quote'] in bodies[i]['body']
        ]
        if not quote_in and issue['quote']:
            # Models often name the wrong item; the quote still counts if it is somewhere in the work.
            quote_in = [i for i, item in bodies.items() if issue['quote'] in item['body']][:1]
        issue['verified'] = bool(quote_in)
        if quote_in:
            issue['quote_item'] = quote_in[0]
            issue['path'] = bodies[quote_in[0]]['path']
        suggest = raw.get('suggest')
        if isinstance(suggest, dict):
            target = bodies.get(str(suggest.get('item', '')))
            find = str(suggest.get('find', ''))
            if target and find and find in target['body']:
                issue['suggest'] = {
                    'item': target['meta']['id'],
                    'path': target['path'],
                    'find': find,
                    'replace': str(suggest.get('replace', '')),
                }
        issue['hash'] = issue_hash(issue)
        if issue['hash'] in seen:
            continue
        seen.add(issue['hash'])
        if issue['hash'] in ignored:
            issue['status'] = 'ignored'
        out.append(issue)
    return out


def issue_action(work, issue, action, note=''):
    """apply: replace the suggested text once; resolve; ignore: remember the hash so later checks fold it."""
    if action == 'apply' and issue.get('suggest'):
        suggest = issue['suggest']
        item = work.get_item(suggest['path'])
        if suggest['find'] not in item['body']:
            return {'status': issue['status'], 'error': 'changed'}
        body = item['body'].replace(suggest['find'], suggest['replace'], 1)
        work.save_item(item['path'], None, body, item['hash'])
        return {'status': 'applied'}
    if action == 'ignore':
        path = work.app / 'consistency.json'
        doc = read_json(path) or {'schema_version': 1, 'ignored': []}
        if all(e['hash'] != issue['hash'] for e in doc['ignored']):
            doc['ignored'].append(
                {
                    'hash': issue['hash'],
                    'items': issue['items'],
                    'quote': issue['quote'],
                    'note': note,
                    'at': now_iso(),
                }
            )
            write_json(path, doc)
        return {'status': 'ignored'}
    if action == 'resolve':
        return {'status': 'resolved'}
    return {'status': issue['status']}


# --- component elements in text (07-jsx: 문구 속 예시) -------------------------------------------------------------
def read_attribute(raw):
    for candidate in (raw, re.sub(r',\s*([}\]])', r'\1', raw), raw.replace("'", '"')):
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError as exc:
            error = str(exc)
    return None, error


def elements(text, name):
    """Every <Name … /> in a text with its attributes read the json_lenient way."""
    pattern = re.compile(rf'<{re.escape(name)}((?:\s+[\w-]+=(?:\'[^\']*\'|"[^"]*"))*)\s*/>')
    out = []
    for match in pattern.finditer(text):
        attrs, errors = {}, []
        for attr in re.finditer(r'([\w-]+)=(?:\'([^\']*)\'|"([^"]*)")', match.group(1)):
            value, error = read_attribute(attr.group(2) if attr.group(2) is not None else attr.group(3))
            if error:
                errors.append(f'{attr.group(1)}: {error}')
            attrs[attr.group(1)] = value
        out.append({'raw': match.group(0), 'attrs': attrs, 'errors': errors})
    return out


def usages(work, name):
    out = []
    for item in work.index_with_bodies():
        if item['kind'] in ('main', 'start', 'lorebook', 'character') and item['meta'].get('enabled', True):
            found = elements(item['body'], name)
            if found:
                out.append({'path': item['path'], 'id': item['meta'].get('id'), 'elements': found})
    return out


def insert_text(work, text, path=None, new_path=None, position='end', heading=None):
    """Put text into an item: at the end, or at the end of a heading's section. A new path makes a lorebook item."""
    if new_path:
        item = work.create_file(new_path, 'lorebook')
        work.save_item(item['path'], {}, text.strip() + '\n', item['hash'])
        return {'path': item['path']}
    item = work.get_item(path)
    body = item['body'].rstrip('\n')
    block = text.strip()
    if position == 'heading' and heading:
        lines = body.split('\n')
        start = next(
            (
                i
                for i, line in enumerate(lines)
                if line.lstrip('#').strip() == heading and line.startswith('#')
            ),
            None,
        )
        if start is not None:
            level = len(lines[start]) - len(lines[start].lstrip('#'))
            end = next(
                (
                    i
                    for i in range(start + 1, len(lines))
                    if lines[i].startswith('#') and len(lines[i]) - len(lines[i].lstrip('#')) <= level
                ),
                len(lines),
            )
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            lines[end:end] = ['', block]
            work.save_item(item['path'], None, '\n'.join(lines) + '\n', item['hash'])
            return {'path': item['path']}
    work.save_item(item['path'], None, f'{body}\n\n{block}\n', item['hash'])
    return {'path': item['path']}
