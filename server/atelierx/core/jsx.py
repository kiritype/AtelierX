"""JSX items: preview examples and static checks (07-jsx). Rendering happens in the web preview frame.

An example is a call as a reply writes it, ``<Name c='C001' />`` (``.atelierx/jsx/<ID>/props/<example>.txt``). Its
props are read with the work's response rule, like a real reply. Older examples were props as JSON
(``<example>.json``); they are shown as a call and become ``.txt`` when saved.
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


def call_text(name, props):
    """A call that carries ``props``: text values as written, other values as JSON (old JSON examples, mock text)."""
    attrs = []
    for key, value in (props or {}).items() if isinstance(props, dict) else ():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        quote = '"' if "'" in text and '"' not in text else "'"
        attrs.append(f' {key}={quote}{text}{quote}')
    return f'<{name}{"".join(attrs)} />'


class Props:
    def __init__(self, work, jsx_id, name='Component'):
        if not jsx_id or not re.fullmatch(r'[\w\-]{1,32}', jsx_id):
            raise AppError(
                Msg('server.works.bad_id', "Use only letters, digits, '_' and '-' (1-32 characters).")
            )
        self.folder = work.app / 'jsx' / jsx_id / 'props'
        self.name = name

    def _name(self, name):
        if not PROPS_NAME.match(name or ''):
            raise AppError(
                Msg('server.jsx.bad_props_name', 'This example name cannot be used: {name}', name=name)
            )
        return name

    def text(self, name):
        """The example's call text, or None. A legacy JSON example is turned into a call."""
        name = self._name(name)
        call = self.folder / f'{name}.txt'
        if call.is_file():
            return call.read_text(encoding='utf-8')
        legacy = self.folder / f'{name}.json'
        if legacy.is_file():
            try:
                return call_text(self.name, json.loads(legacy.read_text(encoding='utf-8'))) + '\n'
            except json.JSONDecodeError:
                return legacy.read_text(encoding='utf-8')
        return None

    def props(self, name, rule=None):
        """The props of the example's first call, read with the work's response rule ({} when there is none)."""
        text = self.text(name) if name else None
        found = review.elements(text or '', self.name, rule)
        return found[0]['attrs'] if found else {}

    def list(self):
        names = set()
        if self.folder.is_dir():
            names = {
                p.stem
                for p in self.folder.iterdir()
                if p.suffix in ('.txt', '.json') and PROPS_NAME.match(p.stem)
            }
        return [
            {'name': name, 'text': self.text(name), 'legacy': not (self.folder / f'{name}.txt').is_file()}
            for name in sorted(names)
        ]

    def save(self, name, text):
        name = self._name(name)
        if not text.strip() or len(text) > EXAMPLE_LIMIT:
            raise AppError(
                Msg('server.jsx.bad_example', 'Write a call such as <Name /> (up to 20,000 characters).')
            )
        atomic_write_text(self.folder / f'{name}.txt', text if text.endswith('\n') else text + '\n')
        (self.folder / f'{name}.json').unlink(missing_ok=True)
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
