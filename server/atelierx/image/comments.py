"""Notes inside image prompts (#157): they stay in what is saved and never reach an image service.

A ``#`` that starts a tag (at the start of a line, after a comma or after a space) begins a note that runs to the end
of the line. A ``#`` inside a tag is part of it (``memories_off#5``, ``ririka_(#compass)``); a tag that really starts
with ``#`` is written ``\\#compass``.
"""

import re

_NOTE = re.compile(r'(?:^|(?<=[\s,]))#')


def _cut(line):
    found = _NOTE.search(line)
    if not found:
        return line.replace('\\#', '#'), False
    return line[: found.start()].replace('\\#', '#'), True


def strip_tag(tag):
    """One tag without its note; '' when the whole tag is a note."""
    text, _ = _cut(str(tag))
    return text.strip()


def strip_text(text):
    """Prompt text without notes: a note ends its line, and a line left empty is dropped."""
    lines = []
    for line in str(text).splitlines():
        kept, cut = _cut(line)
        kept = kept.rstrip(' \t,') if cut else kept.rstrip()
        if kept.strip():
            lines.append(kept)
    return '\n'.join(lines).strip()
