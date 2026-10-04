"""Server messages carry a semantic key and an English sentence; the UI shows them in the user's language.

A ``Msg`` is also an ordinary English string (logs, exceptions, comparisons), so code that raises
``RuntimeError(Msg(...))`` keeps the key; ``message_of`` gets it back and ``wire`` turns messages
into ``{"key", "text", "values"}`` for the page.
"""

from __future__ import annotations


class Msg(str):
    key: str
    values: dict

    def __new__(cls, key: str, text: str, /, **values):
        # An exception becomes its message so the values stay JSON for the page.
        values = {name: message_of(v) if isinstance(v, BaseException) else v for name, v in values.items()}
        shown = {name: str(v) for name, v in values.items()}
        self = super().__new__(cls, text.format(**shown) if values else text)
        self.key = key
        self.values = values
        return self

    @property
    def text(self):
        return str.__str__(self)

    def __reduce__(self):  # copy / deepcopy / pickle keep the key
        return (_rebuild, (self.key, str.__str__(self), self.values))

    def as_dict(self):
        return {'key': self.key, 'text': str.__str__(self), 'values': wire(self.values)}


def _rebuild(key, text, values):
    message = str.__new__(Msg, text)
    message.key = key
    message.values = values
    return message


def wire(value):
    """``value`` with every ``Msg`` replaced by its page form (dicts and lists walked)."""
    if isinstance(value, Msg):
        return value.as_dict()
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(item) for item in value]
    return value


def message_of(error):
    """The ``Msg`` an exception was raised with, or its text (a message passes through)."""
    if not isinstance(error, BaseException):
        return error if isinstance(error, Msg) else str(error)
    first = error.args[0] if error.args else None
    return first if isinstance(first, Msg) else str(error)


class AppError(Exception):
    """An error the user should see. ``status`` is the HTTP status the API returns."""

    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.msg, self.status = msg, status
