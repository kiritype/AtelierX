"""Save conflicts (#90): a tab saving what it loaded earlier does not overwrite a change made elsewhere since."""

from atelierx.core import review, revisions
from atelierx.core.relations import Relations


def test_revisions_ignore_key_order():
    assert revisions.of({'a': 1, 'b': [1, 2]}) == revisions.of({'b': [1, 2], 'a': 1})
    assert revisions.of({'a': 1}) != revisions.of({'a': 2})


def test_the_relation_map_refuses_a_save_over_an_adopted_change(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    work = c.app.state.app.works.get(wid)
    opened = c.get(f'/api/works/{wid}/relations').json()

    # An LLM draft is adopted while the tab is open.
    review.apply_relation_rows(
        work,
        [{'type': 'relation', 'from': 'C001', 'to': '{{user}}', 'kind': '오랜 단골', 'calls': '손님'}],
        [],
    )
    adopted = Relations(work).load()['relations']

    stale = c.put(f'/api/works/{wid}/relations', json={**opened, 'facts': []})
    assert stale.status_code == 409 and stale.json()['error']['key'] == 'server.save.stale'
    assert Relations(work).load()['relations'] == adopted

    fresh = c.get(f'/api/works/{wid}/relations').json()
    saved = c.put(f'/api/works/{wid}/relations', json={**fresh, 'layout': {'C001': {'x': 1, 'y': 2}}}).json()
    assert saved['layout'] == {'C001': {'x': 1, 'y': 2}} and saved['revision'] != fresh['revision']
    # The next save goes on from the revision the last one returned.
    again = c.put(f'/api/works/{wid}/relations', json={**saved, 'layout': {}})
    assert again.status_code == 200


def test_the_glossary_refuses_a_save_from_an_older_load(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    first = c.get(f'/api/works/{wid}/glossary').json()
    saved = c.put(
        f'/api/works/{wid}/glossary',
        json={'terms': [{'use': '노을', 'avoid': ['석양']}], 'base_revision': first['revision']},
    ).json()
    assert saved['terms'][0]['use'] == '노을'
    stale = c.put(f'/api/works/{wid}/glossary', json={'terms': [], 'base_revision': first['revision']})
    assert stale.status_code == 409
    assert c.get(f'/api/works/{wid}/glossary').json()['terms'][0]['use'] == '노을'
