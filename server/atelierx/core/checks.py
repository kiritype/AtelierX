"""Rule checks (02-editor 검사). A first subset; more checks plug in here."""

import re
from collections import defaultdict

from . import jsx, review
from .count import measure
from .exporter import KEYWORDS_FILE
from .i18n import Msg
from .relations import Glossary, Relations

# A component call in a prompt: <Name …/> with a capital first letter, as the platform renders it (07-jsx).
COMPONENT_CALL = re.compile(r'<([A-Z][A-Za-z0-9_]*)(?=[\s/>])')
TEXT_KINDS = ('main', 'start', 'lorebook', 'character')
JOSA_AFTER_REF = re.compile(r'\{\{(user|char)\}\}(은|는|이|가|을|를|과|와|아|야|이랑|랑|에게|의)')


def _issue(level, path, msg):
    return {'level': level, 'path': path, 'message': msg.as_dict()}


def _broken_references(doc, items, enabled):
    """References to things the export will not have (#51): a chat partner that is not a character in use, and component
    calls in the prompts with no JSX component in use by that name."""
    issues = []
    partner = str(doc.get('char') or '')
    if partner and not any(
        i['kind'] == 'character' and str(i['meta'].get('id') or '') == partner for i in enabled
    ):
        issues.append(
            _issue(
                'error',
                None,
                Msg(
                    'check.char_missing',
                    'The chat partner {id} is not a character in use.',
                    id=partner,
                ),
            )
        )
    in_use = {i['name'] for i in enabled if i['kind'] == 'jsx'}
    anywhere = {i['name'] for i in items if i['kind'] == 'jsx'}
    for item in enabled:
        if item['kind'] not in TEXT_KINDS:
            continue
        for name in sorted(set(COMPONENT_CALL.findall(item['body'])) - in_use):
            if name in anywhere:
                msg = Msg(
                    'check.jsx_call_disabled',
                    '{name} is called here, but that component is not in use, so it is not exported.',
                    name=name,
                )
            else:
                msg = Msg(
                    'check.jsx_call_missing',
                    '{name} is called here, but there is no such JSX component.',
                    name=name,
                )
            issues.append(_issue('error', item['path'], msg))
    return issues


def run(work, effective):
    """Return issues for the whole work. ``effective`` is the preset result from ``Presets.effective``."""
    doc = work.doc()
    values = effective['values']
    limits = values.get('limits', {})
    issues = []
    items = []
    for path in work.item_paths():
        items.append(work.read_item(path))

    enabled = [i for i in items if i['kind'] != 'note' and i['meta'].get('enabled', True)]

    mains = [i for i in enabled if i['kind'] == 'main']
    if len(mains) != 1:
        issues.append(
            _issue(
                'error',
                None,
                Msg('check.main_count', 'Exactly one main prompt must be in use (now {n}).', n=len(mains)),
            )
        )

    by_id = defaultdict(list)
    for item in items:
        item_id = item['meta'].get('id')
        if item['meta_error']:
            issues.append(
                _issue('error', item['path'], Msg('check.meta_error', 'The metadata head cannot be read.'))
            )
        if item['kind'] != 'note' and not item_id:
            issues.append(_issue('error', item['path'], Msg('check.no_id', 'This item has no ID.')))
        if item_id:
            by_id[item_id.lower()].append(item['path'])
    for paths in by_id.values():
        if len(paths) > 1:
            for path in paths:
                issues.append(_issue('error', path, Msg('check.dup_id', 'Another item uses the same ID.')))

    mode = values.get('count', 'utf8_bytes')
    amounts = {i['path']: measure(i['body'], mode)[0] for i in enabled}
    for item in enabled:
        if item['kind'] == 'main':
            limit_key = 'main'
        elif item['kind'] in ('lorebook', 'character'):
            limit_key = 'lorebook_entry'
        else:
            continue
        max_size = (limits.get(limit_key) or {}).get('max')
        if max_size is not None and amounts[item['path']] > max_size:
            issues.append(
                _issue(
                    'error',
                    item['path'],
                    Msg(
                        'check.too_big',
                        'Size {size} is over the limit {max}.',
                        size=amounts[item['path']],
                        max=max_size,
                    ),
                )
            )
    total_max = (limits.get('total') or {}).get('max')
    total = sum(amounts.values())
    if total_max is not None and total > total_max:
        issues.append(
            _issue(
                'error',
                None,
                Msg(
                    'check.total_too_big',
                    'Total size {size} is over the limit {max}.',
                    size=total,
                    max=total_max,
                ),
            )
        )

    keyword_owner = defaultdict(list)
    for item in enabled:
        if item['kind'] in ('lorebook', 'character'):
            keywords = item['meta'].get('keywords') or []
            if not keywords and not item['meta'].get('always'):
                issues.append(
                    _issue(
                        'warning',
                        item['path'],
                        Msg('check.no_keywords', 'No keywords and not always included.'),
                    )
                )
            for keyword in keywords:
                keyword_owner[str(keyword).lower()].append(item['path'])
                if len(str(keyword)) == 1:
                    issues.append(
                        _issue(
                            'warning',
                            item['path'],
                            Msg('check.short_keyword', 'Keyword "{k}" is very short.', k=keyword),
                        )
                    )
    for keyword, owners in keyword_owner.items():
        if len(owners) > 1:
            for path in owners:
                issues.append(
                    _issue(
                        'warning',
                        path,
                        Msg('check.shared_keyword', 'Keyword "{k}" is shared by several items.', k=keyword),
                    )
                )

    for item in enabled:
        if item['path'].lower() == KEYWORDS_FILE:
            issues.append(
                _issue(
                    'warning',
                    item['path'],
                    Msg('check.export_name_clash', 'This name is reserved for the export keywords table.'),
                )
            )

    for item in items:
        if '{{char}}' in item['body'] and doc.get('scale') != 'single':
            issues.append(
                _issue(
                    'warning',
                    item['path'],
                    Msg('check.char_ref', '{{char}} is used but this work is not 1:1.'),
                )
            )
        if JOSA_AFTER_REF.search(item['body']):
            issues.append(
                _issue(
                    'info',
                    item['path'],
                    Msg('check.josa_after_ref', 'A particle follows {{user}} or {{char}} directly.'),
                )
            )
    bodies = [i['body'] for i in enabled if i['kind'] in ('main', 'start', 'lorebook', 'character')]
    for item in enabled:
        if item['kind'] == 'jsx':
            issues.extend(jsx.issues(item, values.get('jsx', {}), bodies))
            for other in enabled:
                if other['kind'] in ('main', 'start', 'lorebook', 'character'):
                    for element in review.elements(
                        other['body'], item['name'], review.response_rule(effective)
                    ):
                        if element['errors']:
                            issues.append(
                                _issue(
                                    'warning',
                                    other['path'],
                                    Msg(
                                        'check.jsx_example_unreadable',
                                        'A {name} element here cannot be read: {error}',
                                        name=item['name'],
                                        error=element['errors'][0],
                                    ),
                                )
                            )
    issues.extend(_broken_references(doc, items, enabled))
    issues.extend(Relations(work).issues())
    issues.extend(Glossary(work).issues([i for i in items if i['kind'] != 'note']))
    return issues
