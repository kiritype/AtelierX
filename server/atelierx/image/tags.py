"""Offline Danbooru tag lookup for image prompts: autocomplete, aliases and unknown-tag hints.

Every CSV in data/tags/ is a dictionary (name, category, post count, aliases; defaults/tags/README.md).
The index is loaded on first use and kept in memory (a few hundred thousand rows).
"""

import csv
import difflib
import threading
from pathlib import Path

from ..core.i18n import Msg

CATEGORIES = {'0': 'general', '1': 'artist', '3': 'copyright', '4': 'character', '5': 'meta'}


def norm(tag):
    """Dictionary spelling: lower case with underscores. Saved prompts keep their own spelling."""
    return tag.strip().lower().replace(' ', '_')


class TagIndex:
    def __init__(self, files):
        self.tags, self.aliases = {}, {}
        for path in files:
            with open(path, encoding='utf-8') as stream:
                for row in csv.reader(stream):
                    if len(row) < 3:
                        continue
                    try:
                        name, category, count = row[0], row[1], int(row[2] or 0)
                    except ValueError:
                        continue
                    if name not in self.tags or self.tags[name][1] < count:
                        self.tags[name] = (category, count)
                    for alias in row[3].split(',') if len(row) > 3 and row[3] else []:
                        self.aliases.setdefault(alias.strip(), name)
        self._by_count = sorted(self.tags, key=lambda name: -self.tags[name][1])

    def entry(self, name):
        category, count = self.tags[name]
        return {'tag': name.replace('_', ' '), 'category': CATEGORIES.get(category, category), 'count': count}

    def check(self, tag):
        """ok / alias / unknown for one tag, with near matches for unknown ones."""
        key = norm(tag)
        if key in self.tags:
            return {'status': 'ok', **self.entry(key)}
        if key in self.aliases:
            return {'status': 'alias', 'tag': tag.strip(), 'alias_of': self.entry(self.aliases[key])}
        near = difflib.get_close_matches(key, self._by_count[:60000], n=5, cutoff=0.8)
        return {'status': 'unknown', 'tag': tag.strip(), 'near': [self.entry(n) for n in near]}

    def complete(self, prefix, limit=15):
        """Tags (and aliases) starting with ``prefix``, most used first."""
        key = norm(prefix)
        if not key:
            return []
        result, seen = [], set()
        for name in self._by_count:
            if name.startswith(key):
                result.append(self.entry(name))
                seen.add(name)
                if len(result) >= limit:
                    return result
        for alias, name in self.aliases.items():
            if alias.startswith(key) and name not in seen:
                result.append({**self.entry(name), 'alias': alias.replace('_', ' ')})
                seen.add(name)
                if len(result) >= limit:
                    break
        return result


class TagLookup:
    """The index for the server; empty answers (with the reason) when no dictionary is there."""

    def __init__(self, paths):
        self.paths = paths
        self._index = None
        self._error = ''
        self._lock = threading.Lock()

    def reload(self):
        with self._lock:
            self._index, self._error = None, ''

    def index(self):
        with self._lock:
            if self._index is None and not self._error:
                folder = Path(self.paths.data) / 'tags'
                files = sorted(folder.glob('*.csv')) if folder.is_dir() else []
                if not files:
                    self._error = Msg(
                        'server.tags.danbooru_tag_data_not_found', 'Danbooru tag data not found.'
                    )
                else:
                    self._index = TagIndex(files)
            return self._index

    def complete(self, prefix, limit=15):
        index = self.index()
        if index is None:
            return {'available': False, 'error': self._error, 'tags': []}
        return {'available': True, 'tags': index.complete(prefix, limit)}

    def check(self, tags):
        index = self.index()
        if index is None:
            return {'available': False, 'error': self._error, 'tags': []}
        return {'available': True, 'tags': [index.check(tag) for tag in tags if str(tag).strip()]}
