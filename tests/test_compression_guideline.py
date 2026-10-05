from types import SimpleNamespace

from atelierx.core import guidelines, llm_tasks
from atelierx.core.fsutil import sha256_text


def test_compression_guideline_settings_read_save_reload_and_keep_default(unlocked, paths):
    response = unlocked.get('/api/settings/compression-guideline')
    assert response.status_code == 200
    initial = response.json()
    default_path = paths.defaults / 'guidelines' / 'compression.md'
    default_before = default_path.read_text(encoding='utf-8')
    assert initial == {
        'text': (paths.data / 'guidelines' / 'compression.md').read_text(encoding='utf-8'),
        'default_text': default_before,
        'revision': sha256_text(initial['text']),
    }

    saved = unlocked.put(
        '/api/settings/compression-guideline',
        json={'text': '사용자 압축 지침\n', 'base_revision': initial['revision']},
    )
    assert saved.status_code == 200
    assert saved.json()['text'] == '사용자 압축 지침\n'
    assert saved.json()['default_text'] == default_before
    assert saved.json()['revision'] == sha256_text('사용자 압축 지침\n')
    assert unlocked.get('/api/settings/compression-guideline').json() == saved.json()
    assert default_path.read_text(encoding='utf-8') == default_before


def test_compression_guideline_settings_reject_stale_and_invalid_body(unlocked):
    endpoint = '/api/settings/compression-guideline'
    first = unlocked.get(endpoint).json()
    assert (
        unlocked.put(endpoint, json={'text': 'first', 'base_revision': first['revision']}).status_code == 200
    )

    stale = unlocked.put(endpoint, json={'text': 'overwrite', 'base_revision': first['revision']})
    assert stale.status_code == 409
    assert unlocked.get(endpoint).json()['text'] == 'first'

    for body in ({}, {'text': 1, 'base_revision': first['revision']}, {'text': 'x'}):
        assert unlocked.put(endpoint, json=body).status_code == 400


def test_compression_guideline_resolves_saved_global_and_work_override(paths):
    saved = '전역 저장 지침'
    (paths.data / 'guidelines').mkdir(parents=True)
    (paths.data / 'guidelines' / 'compression.md').write_text(saved, encoding='utf-8')
    work_dir = paths.data / 'works' / 'sample'
    (work_dir / '.atelierx' / 'guidelines').mkdir(parents=True)
    work = SimpleNamespace(app=work_dir / '.atelierx')

    assert guidelines.find(work, paths, [], 'compression.md') == saved
    override = '작품 전용 지침'
    (work.app / 'guidelines' / 'compression.md').write_text(override, encoding='utf-8')
    assert guidelines.find(work, paths, [], 'compression.md') == override

    _, messages = llm_tasks.compression_messages('본문', saved, '', None, [])
    assert saved in messages[0]['content']


def test_a_later_tags_preset_guideline_wins_like_its_values(paths):
    for preset, text in (('first', '앞 태그 프리셋'), ('second', '뒤 태그 프리셋')):
        folder = paths.platforms / preset / 'guidelines'
        folder.mkdir(parents=True)
        (folder / 'jsx.md').write_text(text, encoding='utf-8')
    work_dir = paths.data / 'works' / 'sample'
    (work_dir / '.atelierx').mkdir(parents=True)
    work = SimpleNamespace(app=work_dir / '.atelierx')
    assert guidelines.locate(work, paths, ['first', 'second'], 'jsx.md') == (
        '뒤 태그 프리셋',
        'preset:second',
    )
    assert guidelines.locate(work, paths, ['second', 'first'], 'jsx.md') == ('앞 태그 프리셋', 'preset:first')
