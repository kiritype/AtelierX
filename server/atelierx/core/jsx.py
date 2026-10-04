"""JSX items: example props and static checks (07-jsx). Rendering happens in the web preview frame."""

import json
import re

from .fsutil import atomic_write_text
from .i18n import AppError, Msg

PROPS_NAME = re.compile(r'^[\w\-가-힣]{1,40}$')
HOOK_CALL = re.compile(r'(?<![\w.$])(use[A-Z]\w*)\s*\(')
TOP_FUNCTION = re.compile(r'^function\s+([\w$\u0080-\uffff]+)\s*\(', re.MULTILINE)
COMMENT = re.compile(r'/\*.*?\*/|//[^\n]*', re.DOTALL)
STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', re.DOTALL)


class Props:
    def __init__(self, work, jsx_id):
        if not jsx_id or not re.fullmatch(r'[\w\-]{1,32}', jsx_id):
            raise AppError(
                Msg('server.works.bad_id', "Use only letters, digits, '_' and '-' (1-32 characters).")
            )
        self.folder = work.app / 'jsx' / jsx_id / 'props'

    def _path(self, name):
        if not PROPS_NAME.match(name or ''):
            raise AppError(
                Msg('server.jsx.bad_props_name', 'This example name cannot be used: {name}', name=name)
            )
        return self.folder / f'{name}.json'

    def list(self):
        out = []
        if self.folder.is_dir():
            for path in sorted(self.folder.glob('*.json')):
                text = path.read_text(encoding='utf-8')
                try:
                    out.append({'name': path.stem, 'data': json.loads(text), 'text': text, 'error': None})
                except json.JSONDecodeError as exc:
                    out.append({'name': path.stem, 'data': None, 'text': text, 'error': str(exc)})
        return out

    def save(self, name, text):
        # Keep the user's text as written; only refuse what is not JSON.
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise AppError(
                Msg(
                    'server.jsx.bad_json',
                    'Not valid JSON (line {line}): {error}',
                    line=exc.lineno,
                    error=exc.msg,
                )
            ) from exc
        atomic_write_text(self._path(name), text if text.endswith('\n') else text + '\n')
        return self.list()

    def delete(self, name):
        path = self._path(name)
        if path.exists():
            path.unlink()
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
