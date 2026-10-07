"""Bringing single files into a work (#115): heads read as they are, no guessed kinds, the export's keyword table."""


def _import(c, wid, files, choices=None, apply=False, folder=''):
    return c.post(
        f'/api/works/{wid}/import',
        json={'folder': folder, 'files': files, 'choices': choices or {}, 'apply': apply},
    )


def _rows(response):
    return {r['name']: r for r in response.json()['rows']}


def test_files_with_heads_come_in_as_they_are_and_clashing_ids_get_new_ones(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    files = [
        {
            'name': '바다.md',
            'text': '---\nschema_version: 1\nkind: lorebook\nid: L001\nkeywords: [바다]\n---\n파도.\n',
        },
        {'name': '시작 상황.md', 'text': '---\nkind: start\nid: S900\n---\n문이 열린다.\n'},
    ]
    preview = _import(c, wid, files)
    rows = _rows(preview)
    # L001 is taken in the sample: a new one is proposed. The name is taken too: it gets a number.
    assert rows['바다.md']['id'] != 'L001' and rows['바다.md']['id_changed'] is True
    assert rows['시작 상황.md']['id'] == 'S900' and rows['시작 상황.md']['path'] == '시작 상황 (2).md'
    assert preview.json()['blocked'] == []

    done = _import(c, wid, files, apply=True).json()
    assert sorted(done['created']) == ['바다.md', '시작 상황 (2).md']
    item = c.get(f'/api/works/{wid}/file', params={'path': '바다.md'}).json()
    assert (
        item['kind'] == 'lorebook'
        and item['meta']['keywords'] == ['바다']
        and item['meta']['id'] == rows['바다.md']['id']
    )
    snapshots = c.get(f'/api/works/{wid}/snapshots').json()
    assert any(s['reason'] == 'import' for s in snapshots)


def test_a_markdown_file_without_a_head_waits_for_a_kind(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    files = [
        {'name': '메모.md', 'text': '그냥 글.\n'},
        {'name': 'Panel.jsx', 'text': 'function Panel() { return <div/>; }\n'},
    ]
    rows = _rows(_import(c, wid, files))
    assert rows['메모.md']['head'] == 'none' and rows['메모.md']['kind'] is None
    assert rows['Panel.jsx']['kind'] == 'jsx' and rows['Panel.jsx']['id'].startswith('J')
    preview = _import(c, wid, files).json()
    assert preview['blocked'] == ['f0']
    assert _import(c, wid, files, apply=True).status_code == 400

    choices = {'f0': {'kind': 'note'}}
    assert _import(c, wid, files, choices).json()['blocked'] == []
    assert _import(c, wid, files, {'f0': {'kind': 'jsx'}}).json()['blocked'] == ['f0']  # a .md cannot be JSX
    _import(c, wid, files, choices, apply=True)
    note = c.get(f'/api/works/{wid}/file', params={'path': '메모.md'}).json()
    assert note['kind'] == 'note' and note['body'] == '그냥 글.\n'
    jsx = c.get(f'/api/works/{wid}/file', params={'path': 'Panel.jsx'}).json()
    assert jsx['kind'] == 'jsx' and 'function Panel' in jsx['body']


def test_the_keywords_table_of_an_export_fills_keywords_but_not_the_kind(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    table = (
        '| 경로 | ID | 이름 | 키워드 | 우선순위 | 항상 넣기 |\n|---|---|---|---|---|---|\n'
        '| 인물/한서윤.md | C050 | 한서윤 | 서윤, "반장, 학생회" | 100 | 예 |\n'
    )
    files = [{'name': '_keywords.md', 'text': table}, {'name': '한서윤.md', 'text': '반장이다.\n'}]
    rows = _rows(_import(c, wid, files))
    assert rows['_keywords.md']['role'] == 'table'
    person = rows['한서윤.md']
    assert person['table']['keywords'] == ['서윤', '반장, 학생회'] and person['kind'] is None
    choices = {'f1': {'kind': 'character'}}
    rows = _rows(_import(c, wid, files, choices))
    assert rows['한서윤.md']['id'] == 'C050'
    _import(c, wid, files, choices, apply=True)
    item = c.get(f'/api/works/{wid}/file', params={'path': '한서윤.md'}).json()
    assert item['kind'] == 'character' and item['meta']['id'] == 'C050'
    assert item['meta']['keywords'] == ['서윤', '반장, 학생회'] and item['meta']['priority'] == 100
    assert item['meta']['always'] is True


def test_a_broken_head_is_left_out_unless_brought_in_as_a_note(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    files = [{'name': '깨짐.md', 'text': '---\nkind: [lorebook\n---\n본문\n'}]
    rows = _rows(_import(c, wid, files))
    assert rows['깨짐.md']['head'] == 'broken' and rows['깨짐.md']['include'] is False
    choices = {'f0': {'include': True}}
    assert _import(c, wid, files, choices).json()['blocked'] == ['f0']
    choices = {'f0': {'include': True, 'broken': 'note'}}
    _import(c, wid, files, choices, apply=True)
    note = c.get(f'/api/works/{wid}/file', params={'path': '깨짐.md'}).json()
    assert note['kind'] == 'note' and note['body'].startswith('---\nkind: [lorebook')


def test_a_second_enabled_main_is_pointed_out_and_ids_typed_are_checked(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    files = [{'name': '메인 2.md', 'text': '두 번째 메인.\n'}]
    rows = _rows(_import(c, wid, files, {'f0': {'kind': 'main'}}))
    assert rows['메인 2.md']['main_warning'] is True
    rows = _rows(_import(c, wid, files, {'f0': {'kind': 'main', 'enabled': False}}))
    assert 'main_warning' not in rows['메인 2.md']
    assert (
        _rows(_import(c, wid, files, {'f0': {'kind': 'main', 'id': 'M001'}}))['메인 2.md']['id_error']
        == 'taken'
    )
    assert (
        _rows(_import(c, wid, files, {'f0': {'kind': 'main', 'id': 'bad id'}}))['메인 2.md']['id_error']
        == 'format'
    )


def test_upper_case_suffixes_are_saved_in_lower_case(unlocked):
    """#165: what the preview allowed is written, with the suffix in lower case."""
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    files = [{'name': 'good.md', 'text': '본문\n'}, {'name': 'UPPER.MD', 'text': '본문\n'}]
    choices = {'f0': {'include': True, 'kind': 'note'}, 'f1': {'include': True, 'kind': 'note'}}
    preview = _import(c, wid, files, choices).json()
    assert preview['blocked'] == []
    assert _rows(_import(c, wid, files, choices))['UPPER.MD']['path'] == 'UPPER.md'
    done = _import(c, wid, files, choices, apply=True)
    assert done.status_code == 200 and sorted(done.json()['created']) == ['UPPER.md', 'good.md']


def test_a_file_refused_half_way_takes_back_the_others(unlocked, monkeypatch):
    """#165: no partial result, and a retry does not leave numbered copies."""
    from atelierx.core import works

    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    files = [{'name': 'a.md', 'text': '본문\n'}, {'name': 'b.md', 'text': '본문\n'}]
    choices = {'f0': {'include': True, 'kind': 'note'}, 'f1': {'include': True, 'kind': 'note'}}
    real = works.Work.write_whole

    def refuse_b(self, rel, text, base_hash=None, new=False):
        if rel.endswith('b.md'):
            raise works.AppError(works.Msg('server.works.bad_path', 'This path is not allowed.'))
        return real(self, rel, text, base_hash, new)

    monkeypatch.setattr(works.Work, 'write_whole', refuse_b)
    assert _import(c, wid, files, choices, apply=True).status_code == 400
    assert c.get(f'/api/works/{wid}/file', params={'path': 'a.md'}).status_code == 404
    monkeypatch.setattr(works.Work, 'write_whole', real)
    done = _import(c, wid, files, choices, apply=True).json()
    assert sorted(done['created']) == ['a.md', 'b.md']

