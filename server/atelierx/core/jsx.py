"""JSX items: preview examples and static checks (07-jsx). Rendering happens in the web preview frame.

An example is a call as a reply writes it, ``<Name c='C001' />`` (``.atelierx/jsx/<ID>/props/<example>.txt``). Its
props are read with the work's response rule, like a real reply. Older examples were props as JSON
(``<example>.json``). They are shown as a call only when that call reads back to exactly the same props under the
work's rule; otherwise the JSON is shown with a note. Saving writes ``.txt``; the old ``.json`` is kept as it was.
"""

import json
import re

from . import review
from .fsutil import atomic_write_text
from .i18n import AppError, Msg

PROPS_NAME = re.compile(r'^[\w\-가-힣]{1,40}$')
EXAMPLE_LIMIT = 20_000
HOOK_CALL = re.compile(r'(?<![\w.$])(use[A-Z]\w*)\s*\(')
TOP_FUNCTION = re.compile(r'^function\s+([\w$\u0080-\uffff]+)\s*\(', re.MULTILINE)
COMMENT = re.compile(r'/\*.*?\*/|//[^\n]*', re.DOTALL)
STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', re.DOTALL)


def call_text(name, props, rule=None):
    """A call that reads back to exactly ``props`` under ``rule``, or None when the attribute syntax cannot carry them.

    A text value is written as is when the rule reads it back unchanged (``C001``); otherwise, and for numbers, objects
    and the like, its JSON is written (``"123"`` stays a string), with single quotes as ``\\u0027`` so the attribute can
    always be quoted. Under the ``text`` rule only text values without both kinds of quote can be carried.
    """
    if not isinstance(props, dict):
        return None
    fmt = (rule or {}).get('attribute_format') or 'json_lenient'
    attrs = []
    for key, value in props.items():
        if not re.fullmatch(r'[\w-]+', str(key)):
            return None
        plain = isinstance(value, str) and review.read_attribute(value, fmt) == (value, None)
        text = value if plain else None
        if text is None or ("'" in text and '"' in text):
            if fmt == 'text':
                return None
            # Inside JSON a single quote can be written as ', so the attribute can be single-quoted.
            text = json.dumps(value, ensure_ascii=False).replace("'", '\\u0027')
        if "'" not in text:
            attrs.append(f" {key}='{text}'")
        elif '"' not in text:
            attrs.append(f' {key}="{text}"')
        else:
            return None
    call = f'<{name}{"".join(attrs)} />'
    found = review.elements(call, name, rule)
    return call if found and not found[0]['errors'] and found[0]['attrs'] == props else None


class Props:
    def __init__(self, work, jsx_id, name='Component', rule=None):
        if not jsx_id or not re.fullmatch(r'[\w\-]{1,32}', jsx_id):
            raise AppError(
                Msg('server.works.bad_id', "Use only letters, digits, '_' and '-' (1-32 characters).")
            )
        self.folder = work.app / 'jsx' / jsx_id / 'props'
        self.name = name
        self.rule = rule

    def _name(self, name):
        if not PROPS_NAME.match(name or ''):
            raise AppError(
                Msg('server.jsx.bad_props_name', 'This example name cannot be used: {name}', name=name)
            )
        return name

    def entry(self, name):
        """One example for the screen: its call text, or for an old JSON example that cannot become a call the JSON
        itself with ``convert_error`` set (the screen shows it and keeps the file)."""
        name = self._name(name)
        call = self.folder / f'{name}.txt'
        if call.is_file():
            return {'name': name, 'text': call.read_text(encoding='utf-8'), 'legacy': False}
        legacy = self.folder / f'{name}.json'
        if not legacy.is_file():
            return None
        raw = legacy.read_text(encoding='utf-8')
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        converted = call_text(self.name, data, self.rule)
        if converted is None:
            return {'name': name, 'text': raw, 'legacy': True, 'convert_error': True}
        return {'name': name, 'text': converted + '\n', 'legacy': True}

    def text(self, name):
        found = self.entry(name)
        return found['text'] if found and not found.get('convert_error') else None

    def props(self, name, rule=None):
        """The props of the example's first call, read with the work's response rule ({} when there is none).

        An old JSON example that cannot be written as a call still gives its JSON props.
        """
        found = self.entry(name) if name else None
        if found and found.get('convert_error'):
            try:
                data = json.loads(found['text'])
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        calls = review.elements(found['text'] if found else '', self.name, rule or self.rule)
        return calls[0]['attrs'] if calls else {}

    def list(self):
        names = set()
        if self.folder.is_dir():
            names = {
                p.stem
                for p in self.folder.iterdir()
                if p.suffix in ('.txt', '.json') and PROPS_NAME.match(p.stem)
            }
        return [self.entry(name) for name in sorted(names)]

    def save(self, name, text):
        name = self._name(name)
        if not text.strip() or len(text) > EXAMPLE_LIMIT:
            raise AppError(
                Msg('server.jsx.bad_example', 'Write a call such as <Name /> (up to 20,000 characters).')
            )
        # An old ``.json`` with the same name stays untouched; the ``.txt`` takes its place in the list.
        atomic_write_text(self.folder / f'{name}.txt', text if text.endswith('\n') else text + '\n')
        return self.list()

    def delete(self, name):
        name = self._name(name)
        for suffix in ('.txt', '.json'):
            (self.folder / f'{name}{suffix}').unlink(missing_ok=True)
        return self.list()


def _code_only(source):
    return STRING.sub('""', COMMENT.sub('', source))


def _issue(level, path, msg):
    return {'level': level, 'path': path, 'message': msg.as_dict()}


def issues(item, rules, bodies):
    """Static checks for one enabled JSX item. ``bodies`` are the texts of enabled main/lorebook items."""
    path, source = item['path'], item['body']
    code = _code_only(source)
    out = []
    for word in rules.get('forbid', []):
        if re.search(rf'(?<![\w.$]){re.escape(word)}\b', code):
            out.append(
                _issue('error', path, Msg('check.jsx_forbidden', '"{word}" is not allowed here.', word=word))
            )
    allowed = set(rules.get('hooks', []))
    for hook in sorted({h for h in HOOK_CALL.findall(code) if h not in allowed}):
        out.append(
            _issue('error', path, Msg('check.jsx_hook', 'Hook {hook} is not allowed here.', hook=hook))
        )
    functions = TOP_FUNCTION.findall(code)
    if len(functions) != 1 or functions[0] != item['name']:
        out.append(
            _issue(
                'warning',
                path,
                Msg('check.jsx_shape', 'Write one top-level function named {name}.', name=item['name']),
            )
        )
    if not any(re.search(rf'<{re.escape(item["name"])}[\s/>]', body) for body in bodies):
        out.append(
            _issue('info', path, Msg('check.jsx_unused', 'No prompt or lorebook uses this component yet.'))
        )
    return out
