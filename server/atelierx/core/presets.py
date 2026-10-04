"""Platform presets (decision 0009): app defaults -> linked presets in tag order -> work overrides."""

import copy
import re
import shutil

from .fsutil import read_json, write_json
from .i18n import AppError, Msg

GENERIC = {
    'schema_version': 1,
    'name': '범용',
    'count': 'utf8_bytes',
    'limits': {'main': {'max': None}, 'lorebook_entry': {'max': None}, 'total': {'max': None}},
    'lorebook': {
        'keywords': True,
        'max_keywords': None,
        'match': 'substring',
        'case_sensitive': False,
        'scan': {'messages': 2, 'roles': ['user', 'assistant']},
        'budget': {'max': None},
        'max_active': None,
    },
    'jsx': {
        'globals': [],
        'forbid': ['import', 'export'],
        'hooks': ['useState', 'useEffect', 'useMemo', 'useRef', 'useCallback'],
        'response': {'syntax': 'element', 'attribute_format': 'json_lenient', 'decode': []},
    },
}


def _merge_tracked(base, sources, extra, source):
    """Merge ``extra`` into ``base``; ``sources`` mirrors leaf keys with where each value came from."""
    for key, value in (extra or {}).items():
        if key in ('schema_version', 'name'):
            continue
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            sources.setdefault(key, {})
            if not isinstance(sources[key], dict):
                sources[key] = {}
            _merge_tracked(base[key], sources[key], value, source)
        elif value is not None or key not in base:
            base[key] = copy.deepcopy(value)
            sources[key] = source


def _leaf_sources(value, source):
    if isinstance(value, dict):
        return {key: _leaf_sources(item, source) for key, item in value.items()}
    return source


def _update_preserving(target, changes):
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _update_preserving(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


class Presets:
    def __init__(self, paths):
        self.dir = paths.platforms

    def list(self):
        items = [{'id': 'generic', 'name': GENERIC['name'], 'readonly': True}]
        if self.dir.is_dir():
            for folder in sorted(self.dir.iterdir()):
                doc = read_json(folder / 'preset.json')
                if doc is not None:
                    items.append({'id': folder.name, 'name': doc.get('name', folder.name), 'readonly': False})
        return items

    def ids(self):
        return {item['id'] for item in self.list()}

    def get(self, preset_id):
        if preset_id == 'generic':
            return copy.deepcopy(GENERIC)
        doc = read_json(self.dir / preset_id / 'preset.json')
        if doc is None:
            raise AppError(
                Msg('server.presets.not_found', 'Platform preset {id} was not found.', id=preset_id), 404
            )
        return doc

    @staticmethod
    def _validate_id(preset_id):
        if not isinstance(preset_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', preset_id):
            raise AppError(
                Msg('server.presets.invalid_id', 'Preset IDs may use letters, digits, _ and -.'), 400
            )

    def _safe_folder(self, preset_id):
        self._validate_id(preset_id)
        root = self.dir.resolve()
        folder = self.dir / preset_id
        # Windows junctions can point outside the presets directory just like symlinks.
        is_junction = getattr(folder, 'is_junction', lambda: False)()
        if folder.is_symlink() or is_junction:
            raise AppError(Msg('server.presets.unsafe_path', 'This preset path is unsafe.'), 400)
        try:
            folder.resolve().relative_to(root)
        except ValueError as exc:
            raise AppError(Msg('server.presets.unsafe_path', 'This preset path is unsafe.'), 400) from exc
        return folder

    def create(self, preset_id, name, base='generic'):
        self._validate_id(preset_id)
        if preset_id in self.ids():
            raise AppError(
                Msg('server.presets.exists', 'Platform preset {id} already exists.', id=preset_id), 409
            )
        # Presets are independent settings. Generic supplies initial defaults only.
        doc = copy.deepcopy(GENERIC)
        doc['name'] = name
        write_json(self.dir / preset_id / 'preset.json', doc)
        (self.dir / preset_id / 'guidelines').mkdir(parents=True, exist_ok=True)
        return doc

    def save(self, preset_id, doc):
        if preset_id == 'generic':
            raise AppError(
                Msg('server.presets.readonly', 'The generic preset is read-only. Duplicate it to edit.')
            )
        folder = self._safe_folder(preset_id)
        current = self.get(preset_id)
        if not isinstance(doc, dict):
            raise AppError(Msg('server.presets.invalid', 'Preset must be an object.'), 400)
        if not isinstance(current.get('limits'), dict) or (
            'limits' in doc and not isinstance(doc['limits'], dict)
        ):
            raise AppError(Msg('server.presets.invalid_limit', 'Limits must be an object.'), 400)
        # Merge submitted fields so older/advanced rule fields survive GUI edits.
        _update_preserving(current, doc)
        current['name'] = str(current.get('name') or preset_id)
        for key in ('main', 'lorebook_entry'):
            if key not in current['limits']:
                current['limits'][key] = {'max': None}
        for key in ('main', 'lorebook_entry'):
            limit = current['limits'][key]
            if not isinstance(limit, dict) or (
                limit.get('max') is not None
                and (not isinstance(limit['max'], int) or isinstance(limit['max'], bool) or limit['max'] < 0)
            ):
                raise AppError(
                    Msg('server.presets.invalid_limit', 'Limits must be non-negative integers or unset.'), 400
                )
        write_json(folder / 'preset.json', current)
        return current

    def delete(self, preset_id, works, settings):
        folder = self._safe_folder(preset_id)
        if preset_id == 'generic':
            raise AppError(Msg('server.presets.readonly', 'The generic preset is read-only.'))
        used_by = [w.doc().get('id', w.folder.name) for w in works if preset_id in w.doc().get('tags', [])]
        if settings.get('default_platform_preset') == preset_id:
            used_by.append('default')
        if used_by:
            raise AppError(
                Msg('server.presets.in_use', 'Preset is in use: {uses}.', uses=', '.join(used_by)), 409
            )
        self.get(preset_id)  # give a localized 404 for an unknown preset
        shutil.rmtree(folder, ignore_errors=False)
        return self.list()

    def effective(self, work_doc):
        """Values for a work plus, for every leaf, where it came from ('default', 'preset:<id>', 'work')."""
        value = copy.deepcopy(GENERIC)
        value.pop('name', None)
        sources = _leaf_sources({k: v for k, v in value.items() if k != 'schema_version'}, 'default')
        linked = [tag for tag in work_doc.get('tags', []) if tag in self.ids() and tag != 'generic']
        for preset_id in linked:
            _merge_tracked(value, sources, self.get(preset_id), f'preset:{preset_id}')
        _merge_tracked(value, sources, work_doc.get('overrides') or {}, 'work')
        value.pop('schema_version', None)
        return {'linked': linked, 'values': value, 'sources': sources}
