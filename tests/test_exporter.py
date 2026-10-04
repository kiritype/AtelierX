from atelierx.core import exporter


def item(path, kind='lorebook', **meta):
    return {'path': path, 'name': path.rsplit('/', 1)[-1].rsplit('.', 1)[0], 'kind': kind, 'meta': meta}


def test_keywords_table_follows_language_and_has_id():
    items = [
        item('인물/하람.md', 'character', id='C001', keywords=['하람', 'a, b'], priority=100, always=True),
        item('메인.md', 'main', id='M001'),
    ]
    ko = exporter.keywords_table(items, 'ko').splitlines()
    assert ko[0] == '| 경로 | ID | 이름 | 키워드 | 우선순위 | 항상 넣기 |'
    assert ko[2] == '| 인물/하람.md | C001 | 하람 | 하람, "a, b" | 100 | 예 |'
    assert len(ko) == 3
    en = exporter.keywords_table(items, 'en').splitlines()
    assert en[0] == '| Path | ID | Name | Keywords | Priority | Always |'
    assert en[2].endswith('| 100 | yes |')


def test_name_clash_only_at_root():
    assert exporter.name_clash([item('_Keywords.md')]) == '_Keywords.md'
    assert exporter.name_clash([item('세계관/_keywords.md'), item('keywords.md')]) is None
