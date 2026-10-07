"""First start: create the app folder layout and copy the defaults (architecture: 앱 시작)."""

import shutil

from .fsutil import read_json, write_json

LAYOUT_VERSION = 1

DEFAULT_PROVIDERS = {
    'schema_version': 1,
    'providers': {
        'local': {
            'name': '로컬 LLM',
            'type': 'openai_compatible',
            'base_url': 'http://127.0.0.1:1234/v1',
            'key': None,
            'trusted': False,
            'models': {},
        }
    },
    'tasks': {},
}


def ensure_layout(paths):
    for folder in (paths.config, paths.state, paths.data, paths.output, paths.works, paths.platforms):
        folder.mkdir(parents=True, exist_ok=True)
    marker = paths.data / 'atelierx.json'
    first = not marker.is_file()
    if first:
        write_json(marker, {'schema_version': 1, 'layout_version': LAYOUT_VERSION})
    for name, target in (('guidelines', paths.data / 'guidelines'), ('image', paths.data / 'image')):
        source = paths.defaults / name
        if source.is_dir() and not target.exists():
            shutil.copytree(source, target)
    # Fields the bundled library gained after this app folder was made (deployment codes, decision 0023).
    from ..image.library import fill_default_codes, migrate_styles

    fill_default_codes(paths)
    # Style fragments became the style presets' artist tags (#169).
    migrate_styles(paths)
    tags = paths.data / 'tags'
    if not tags.exists() and (paths.defaults / 'tags').is_dir():
        tags.mkdir(parents=True)
        for csv in (paths.defaults / 'tags').glob('*.csv'):
            shutil.copy2(csv, tags / csv.name)
    if read_json(paths.data / 'providers.json') is None:
        write_json(paths.data / 'providers.json', DEFAULT_PROVIDERS)
    return first
