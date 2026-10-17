import pytest


@pytest.mark.parametrize('keyword', ['가', '🌙', '👩‍🎨', 'shared'])
def test_short_and_shared_keywords_remain_valid(unlocked, keyword):
    c = unlocked
    wid = c.post('/api/works', json={'name': 'Keyword checks'}).json()['id']
    for index, kind in enumerate(['lorebook', 'character', 'lorebook']):
        path = f'entry{index}.md'
        item = c.post(f'/api/works/{wid}/file', json={'path': path}).json()
        keywords = [keyword, keyword] if index < 2 else []
        saved = c.put(
            f'/api/works/{wid}/file',
            params={'path': path},
            json={
                'base_hash': item['hash'],
                'meta': {'kind': kind, 'id': f'L{index:03}', 'keywords': keywords},
                'body': f'Entry {index}',
            },
        )
        assert saved.status_code == 200
        assert saved.json()['meta']['keywords'] == keywords
        loaded = c.get(f'/api/works/{wid}/file', params={'path': path}).json()
        assert loaded['meta']['keywords'] == keywords

    issues = c.get(f'/api/works/{wid}/check').json()
    keys = {i['message']['key'] for i in issues}
    assert 'check.short_keyword' not in keys
    assert 'check.shared_keyword' not in keys
    assert 'check.main_count' in keys
    assert any(i['path'] == 'entry2.md' and i['message']['key'] == 'check.no_keywords' for i in issues)

    context = c.post(f'/api/works/{wid}/chat/preview', json={'history': [], 'message': keyword}).json()
    assert {i['id'] for i in context['picked']} == {'L000', 'L001'}
