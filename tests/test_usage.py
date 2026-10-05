"""LLM usage: months, groupings, the request log with paging and filters, and the CSV export."""

import json


def write_month(paths, month, entries):
    folder = paths.data / 'usage'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{month}.jsonl').write_text(
        ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8'
    )


def entry(n, task='compression', work='W001', tokens=True):
    return {
        'at': f'2026-09-01T10:{n:02d}:00+09:00',
        'provider': 'local',
        'model': 'm',
        'task': task,
        'work': work,
        'input_tokens': 10 if tokens else None,
        'output_tokens': 5 if tokens else None,
    }


def test_usage_groups_months_log_and_csv(unlocked, paths):
    write_month(paths, '2026-08', [entry(1)])
    write_month(
        paths,
        '2026-09',
        [
            entry(n, task='chat_test' if n % 2 else 'compression', work='W002' if n > 55 else 'W001')
            for n in range(60)
        ]
        + [entry(59, tokens=False)],
    )
    c = unlocked

    data = c.get('/api/usage', params={'month': '2026-09'}).json()
    assert data['months'][:2] == ['2026-09', '2026-08']
    assert sum(r['requests'] for r in data['rows']) == 61
    assert (
        sum(r['unknown'] for r in data['rows']) == 1 and sum(r['input_tokens'] for r in data['rows']) == 600
    )

    by_work = {
        r['work']: r['requests']
        for r in c.get('/api/usage', params={'month': '2026-09', 'by': 'work'}).json()['rows']
    }
    assert by_work == {'W001': 57, 'W002': 4}
    by_task = {
        r['task'] for r in c.get('/api/usage', params={'month': '2026-09', 'by': 'task'}).json()['rows']
    }
    assert by_task == {'chat_test', 'compression'}

    first = c.get('/api/usage/log', params={'month': '2026-09'}).json()
    assert first['total'] == 61 and len(first['rows']) == 50
    assert first['rows'][0]['input_tokens'] is None  # newest first
    rest = c.get('/api/usage/log', params={'month': '2026-09', 'offset': 50}).json()
    assert len(rest['rows']) == 11
    only = c.get('/api/usage/log', params={'month': '2026-09', 'work': 'W002', 'task': 'chat_test'}).json()
    assert only['total'] == 2 and all(r['work'] == 'W002' and r['task'] == 'chat_test' for r in only['rows'])

    csv = c.get('/api/usage.csv', params={'month': '2026-09'})
    assert csv.headers['content-type'].startswith('text/csv')
    lines = csv.content.decode('utf-8-sig').splitlines()
    assert lines[0] == 'at,provider,model,task,work,input_tokens,output_tokens' and len(lines) == 62

    assert c.get('/api/usage', params={'month': '../x'}).json()['rows'] == []


def test_the_task_filter_does_not_depend_on_the_grouping(unlocked, paths):
    write_month(paths, '2026-07', [entry(1, task='chat_test'), entry(2, task='compression', work='W002')])
    for by in ('model', 'task', 'work'):
        data = unlocked.get('/api/usage', params={'month': '2026-07', 'by': by}).json()
        assert data['tasks'] == ['chat_test', 'compression']
