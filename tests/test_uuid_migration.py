"""Synthetic pre-migration contract for image-library UUID migration (#265)."""

import json
import uuid

import pytest

from atelierx.core.paths import AppPaths
from atelierx.core.works import WorkStore
from atelierx.image import library, library_share, preset_share
from atelierx.image.compose import Composer
from atelierx.image.settings import get as image_settings
from atelierx.image.uuid_migration import mapping, migrate


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def fixture(paths):
    """Two works with a global override and two independent same-named entries."""
    (paths.data / 'image').mkdir(parents=True)
    paths.works.mkdir(parents=True)
    works = WorkStore(paths)
    first = works.create('작품 A', 'W901')
    second = works.create('작품 B', 'W902')
    global_image = paths.data / 'image'
    _write(
        global_image / 'common.json',
        {
            'schema_version': 1,
            'items': {'quality': {'name': '품질', 'prompt': ['detailed'], 'default': True}},
        },
    )
    _write(
        global_image / 'compositions.json',
        {
            'schema_version': 1,
            'items': {'portrait': {'name': '초상', 'prompt': ['portrait'], 'suggest_slots': ['top']}},
        },
    )
    _write(
        global_image / 'expressions.json',
        {
            'schema_version': 1,
            'items': {
                'smile': {
                    'name': '미소',
                    'prompt': ['happy'],
                    'composition': 'portrait',
                    'rating': 'general',
                    'code': '001',
                }
            },
        },
    )
    _write(
        global_image / 'outfits.json',
        {'schema_version': 1, 'items': {'shirt': {'name': '상의', 'prompt': ['blue shirt'], 'slot': 'top'}}},
    )
    _write(
        global_image / 'presets' / 'soft.json',
        library.preset_doc(
            {'name': '부드러움', 'common': ['quality'], 'artist': {'positive': 'soft light'}}, 'soft'
        ),
    )
    (global_image / 'presets' / 'soft.webp').write_bytes(b'RIFF synthetic preview')
    for work, prompt in ((first, 'warm smile'), (second, 'quiet smile')):
        own = work.app / 'image'
        _write(
            own / 'expressions.json',
            {
                'schema_version': 1,
                'items': {
                    'smile': {
                        'name': '미소',
                        'prompt': [prompt],
                        'composition': 'portrait',
                        'rating': 'general',
                    },
                    'custom': {'name': '같은 이름', 'prompt': [prompt + ' custom'], 'rating': 'general'},
                },
            },
        )
        _write(
            own / 'characters' / 'C001' / 'design.json',
            {
                'schema_version': 1,
                'appearance': {'prompt': ['brown hair']},
                'default_outfit': 'o01',
                'outfits': {'o01': {'name': '평상복', 'slots': {'top': {'ref': 'global:shirt'}}}},
            },
        )
    return first, second


def _prompt(paths, work, expression='smile'):
    return Composer(paths, work).compose(
        {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': expression},
        {'common_ids': ['quality'], 'artist': {'positive': 'soft light'}},
    )


def test_synthetic_legacy_fixture_has_distinct_overrides_and_prompts(paths):
    first, second = fixture(paths)
    assert library.items(paths, first, 'expressions')['smile']['overrides']
    assert library.items(paths, second, 'expressions')['custom']['prompt'] == ['quiet smile custom']
    assert library.items(paths, first, 'expressions')['custom']['prompt'] == ['warm smile custom']
    assert _prompt(paths, first)['positive'] != _prompt(paths, second)['positive']
    assert (paths.data / 'image' / 'presets' / 'soft.webp').read_bytes() == b'RIFF synthetic preview'


def test_migration_preserves_composed_prompts_scope_and_preview(paths):
    first, second = fixture(paths)
    before = [_prompt(paths, work)['positive'] for work in (first, second)]
    old_counts = [len(library.items(paths, work, 'expressions')) for work in (first, second)]
    result = migrate(paths)
    global_smile = result['library']['expressions/global/smile']
    assert result['library']['expressions/work/W901/smile'] == global_smile
    assert result['library']['expressions/work/W902/smile'] == global_smile
    assert (
        result['library']['expressions/work/W901/custom'] != result['library']['expressions/work/W902/custom']
    )
    assert all(str(uuid.UUID(value)) == value for value in result['library'].values())
    assert all(str(uuid.UUID(value)) == value for value in result['presets'].values())
    assert [_prompt(paths, work)['positive'] for work in (first, second)] == before
    assert [len(library.items(paths, work, 'expressions')) for work in (first, second)] == old_counts
    assert result['presets']['soft'] in {preset['id'] for preset in library.presets(paths)}
    assert (
        paths.data / 'image' / 'presets' / (result['presets']['soft'] + '.webp')
    ).read_bytes() == b'RIFF synthetic preview'
    assert not (paths.data / 'image' / 'presets' / 'soft.json').exists()
    assert migrate(paths) == result == mapping(paths)


@pytest.mark.parametrize('phase', ['backup', 'journal', 'replace', 'cleanup'])
def test_migration_recovers_each_interruption(paths, phase):
    first, _ = fixture(paths)
    original_prompt = _prompt(paths, first)['positive']
    active = [paths.data / 'image' / 'expressions.json', paths.data / 'image' / 'presets' / 'soft.json']
    original = [path.read_bytes() for path in active]
    with pytest.raises(RuntimeError, match='Injected UUID migration'):
        migrate(paths, fail_at=phase)
    # Recovering an interrupted journal restores exact source bytes before retry.
    from atelierx.image.uuid_migration import recover

    recover(paths)
    assert [path.read_bytes() for path in active] == original
    result = migrate(paths)
    assert _prompt(paths, first)['positive'] == original_prompt
    assert mapping(paths) == result


def test_invalid_library_is_preserved_without_committing(paths):
    fixture(paths)
    broken = paths.data / 'image' / 'expressions.json'
    broken.write_text('{', encoding='utf-8')
    with pytest.raises(ValueError, match='malformed image data'):
        migrate(paths)
    assert broken.read_text(encoding='utf-8') == '{'
    assert not (paths.data / 'image' / 'uuid-map.json').exists()


def test_design_scope_refs_keep_global_and_work_outfits_distinct(paths):
    first, _ = fixture(paths)
    _write(
        first.app / 'image' / 'outfits.json',
        {
            'schema_version': 1,
            'items': {
                'shirt': {'name': 'Local shirt', 'prompt': ['red shirt'], 'slot': 'top'},
            },
        },
    )
    design = first.app / 'image' / 'characters' / 'C001' / 'design.json'
    doc = json.loads(design.read_text(encoding='utf-8'))
    doc['outfits']['o01']['slots']['bottom'] = {'ref': 'work:shirt'}
    _write(design, doc)
    migrated = migrate(paths)
    refs = json.loads(design.read_text(encoding='utf-8'))['outfits']['o01']['slots']
    assert refs['top']['ref'] == 'global:' + migrated['library']['outfits/global/shirt']
    assert refs['bottom']['ref'] == 'work:' + migrated['library']['outfits/work/W901/shirt']
    assert refs['top']['ref'] != refs['bottom']['ref']


def test_preset_preview_freshness_is_preserved(paths):
    fixture(paths)
    folder = paths.data / 'image' / 'presets'
    doc = json.loads((folder / 'soft.json').read_text(encoding='utf-8'))
    seed = image_settings(paths, 'presets')['preview_seed']
    doc['preview'] = {'seed': seed, 'hash': library.preview_hash(doc, seed)}
    _write(folder / 'soft.json', doc)
    stale = {**doc, 'preview': {'seed': seed, 'hash': 'already-stale'}}
    _write(folder / 'stale.json', stale)
    migrated = migrate(paths)
    fresh = json.loads((folder / f'{migrated["presets"]["soft"]}.json').read_text(encoding='utf-8'))
    old = json.loads((folder / f'{migrated["presets"]["stale"]}.json').read_text(encoding='utf-8'))
    assert fresh['preview']['hash'] == library.preview_hash(fresh, seed)
    assert old['preview']['hash'] == 'already-stale'


def test_cross_root_share_carries_preset_common_and_expression_composition(paths, tmp_path):
    first, _ = fixture(paths)
    source = migrate(paths)
    # A second installation has its own migration history and no custom items.
    other = AppPaths(
        root=tmp_path / 'other', defaults=paths.defaults, samples=paths.samples, web=tmp_path / 'web2'
    )
    other.root.mkdir()
    other_work = WorkStore(other).create('Other work', 'W903')
    migrate(other)
    preset_zip, _ = preset_share.export(paths, [source['presets']['soft']])
    importer = preset_share.PresetImports(other)
    preview = importer.preview(preset_zip, {'connected': False})
    importer.apply(preview['token'], {})
    imported = library.presets(other)[0]
    assert imported['common']
    assert imported['common'][0] in library.items(other, None, 'common')
    assert library.preview_prompts(other, imported)[0].startswith('detailed')

    expression_id = source['library']['expressions/global/smile']
    shared, _ = library_share.export(paths, first, 'expressions', [expression_id])
    assert shared['dependencies']['compositions']
    library_share.apply(other, other_work, 'expressions', shared, 'work', {expression_id: 'add'})
    expression = library.items(other, other_work, 'expressions')[expression_id]
    assert expression['composition'] in library.items(other, other_work, 'compositions')
    assert library.items(other, other_work, 'compositions')[expression['composition']]['prompt'] == [
        'portrait'
    ]


def test_missing_historical_references_remain_verbatim(paths):
    first, _ = fixture(paths)
    expressions = first.app / 'image' / 'expressions.json'
    doc = json.loads(expressions.read_text(encoding='utf-8'))
    doc['items']['custom']['composition'] = 'deleted_composition'
    _write(expressions, doc)
    preset = paths.data / 'image' / 'presets' / 'soft.json'
    doc = json.loads(preset.read_text(encoding='utf-8'))
    doc['common'].append('deleted_common')
    _write(preset, doc)
    design = first.app / 'image' / 'characters' / 'C001' / 'design.json'
    doc = json.loads(design.read_text(encoding='utf-8'))
    doc['outfits']['o01']['slots']['bottom'] = {'ref': 'global:deleted_outfit'}
    _write(design, doc)
    migrated = migrate(paths)
    custom = library.items(paths, first, 'expressions')[migrated['library']['expressions/work/W901/custom']]
    assert custom['composition'] == 'deleted_composition'
    assert library.presets(paths)[0]['common'][-1] == 'deleted_common'
    assert (
        json.loads(design.read_text(encoding='utf-8'))['outfits']['o01']['slots']['bottom']['ref']
        == 'global:deleted_outfit'
    )
