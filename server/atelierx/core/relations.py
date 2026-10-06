"""Relation map and glossary (data-model: 관계도, 용어집). Reference data only; never exported or sent to the chat."""

from . import revisions
from .fsutil import read_json, write_json
from .i18n import Msg

RESERVED = ('{{user}}', '{{char}}')


def _issue(level, path, msg):
    return {'level': level, 'path': path, 'message': msg.as_dict()}


class Relations:
    def __init__(self, work):
        self.work = work
        self.path = work.app / 'relations.json'

    def load(self):
        doc = read_json(self.path) if self.path.is_file() else {}
        return {
            'schema_version': 1,
            'people': doc.get('people', []),
            'relations': doc.get('relations', []),
            'facts': doc.get('facts', []),
            'layout': doc.get('layout', {}),
        }

    def save(self, doc):
        clean = {
            'schema_version': 1,
            'people': [p for p in doc.get('people', []) if str(p.get('id', '')).strip()],
            'relations': [r for r in doc.get('relations', []) if r.get('from') and r.get('to')],
            'facts': [f for f in doc.get('facts', []) if f.get('subject') and str(f.get('key', '')).strip()],
            'layout': doc.get('layout', {}),
        }
        write_json(self.path, clean)
        return self.view()

    def update(self, data):
        """Save from the relation map tab: refused when the map changed since the tab loaded it (``base_revision``)."""
        revisions.check(data.get('base_revision', data.get('revision')), revisions.of(self.load()))
        return self.save(data)

    def view(self):
        """Stored data plus the people the editor shows: {{user}}, every character item, then extra people."""
        doc = self.load()
        characters = [i for i in self.work.index() if i['kind'] == 'character' and i['meta'].get('id')]
        known = {c['meta']['id'] for c in characters}
        people = [{'id': '{{user}}', 'name': '{{user}}', 'source': 'reserved'}]
        char_id = self.work.doc().get('char')
        for item in characters:
            person = {
                'id': item['meta']['id'],
                'name': item['name'],
                'path': item['path'],
                'source': 'character',
            }
            if item['meta']['id'] == char_id:
                person['char'] = True
            people.append(person)
        for extra in doc['people']:
            if extra.get('id') not in known:
                people.append({**extra, 'name': extra.get('name') or extra['id'], 'source': 'extra'})
        return {**doc, 'view': people, 'revision': revisions.of(doc)}

    def issues(self):
        doc = self.load()
        ids = {p['id'] for p in self.view()['view']} | set(RESERVED)
        issues = []
        refs = [(r.get('from'), r.get('to')) for r in doc['relations']] + [
            (f.get('subject'),) for f in doc['facts']
        ]
        for missing in sorted({i for ref in refs for i in ref if i and i not in ids}):
            issues.append(
                _issue(
                    'error',
                    None,
                    Msg(
                        'check.relation_missing_person',
                        'The relation map refers to {id}, which does not exist.',
                        id=missing,
                    ),
                )
            )
        return issues


class Glossary:
    def __init__(self, work):
        self.path = work.app / 'glossary.json'

    def load(self):
        doc = read_json(self.path) if self.path.is_file() else {}
        return {'schema_version': 1, 'terms': doc.get('terms', [])}

    def view(self):
        doc = self.load()
        return {**doc, 'revision': revisions.of(doc)}

    def update(self, data):
        """Save from the glossary tab: refused when the glossary changed since the tab loaded it."""
        revisions.check(data.get('base_revision', data.get('revision')), revisions.of(self.load()))
        self.save(data)
        return self.view()

    def save(self, doc):
        terms = []
        for term in doc.get('terms', []):
            use = str(term.get('use', '')).strip()
            if not use:
                continue
            avoid = [str(a).strip() for a in term.get('avoid', []) if str(a).strip()]
            terms.append({'use': use, 'avoid': avoid, 'note': str(term.get('note', ''))})
        write_json(self.path, {'schema_version': 1, 'terms': terms})
        return self.load()

    def issues(self, items):
        issues = []
        for term in self.load()['terms']:
            for avoid in term.get('avoid', []):
                for item in items:
                    if avoid and avoid in item['body']:
                        issues.append(
                            _issue(
                                'warning',
                                item['path'],
                                Msg(
                                    'check.glossary_avoid',
                                    '"{avoid}" is listed to avoid; use "{use}".',
                                    avoid=avoid,
                                    use=term['use'],
                                ),
                            )
                        )
        return issues
