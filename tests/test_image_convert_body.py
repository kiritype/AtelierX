"""Image prompt conversion without sections (#150): the whole text (A) and chosen ranges (E), with the text pieces
each part comes from."""

import time

BODY = """한서윤은 열일곱 살 고등학생이다.
검은 긴 머리를 하나로 묶고 다닌다. 눈은 짙은 갈색이다.
학교에서는 남색 교복 재킷에 체크 치마를 입는다.
어릴 때는 머리가 짧았다.
"""


def _wait(c, queued):
    for _ in range(200):
        job = next(j for j in c.get('/api/jobs').json() if j['id'] == queued['id'])
        if job['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert job['status'] == 'done', job
    return job['result']['draft']


def _character(c, body=BODY):
    wid = c.post('/api/works', json={'name': '섹션 없는 작품'}).json()['id']
    item = c.post(f'/api/works/{wid}/file', json={'path': '서윤'}).json()
    c.put(
        f'/api/works/{wid}/file?path=서윤.md',
        json={'meta': {'id': 'C001', 'kind': 'character'}, 'body': body, 'base_hash': item['hash']},
    )
    return wid, f'/api/works/{wid}/image/characters/C001'


def _rewrite(c, wid, body):
    item = c.get(f'/api/works/{wid}/file?path=서윤.md').json()
    assert (
        c.put(
            f'/api/works/{wid}/file?path=서윤.md',
            json={'meta': item['meta'], 'body': body, 'base_hash': item['hash']},
        ).status_code
        == 200
    )


def _convert(c, wid, url, **body):
    draft = _wait(c, c.post(f'{url}/convert', json=body).json())
    return draft, c.get(f'/api/works/{wid}/drafts/{draft}').json()


def _apply(c, wid, draft, **body):
    res = c.post(f'/api/works/{wid}/drafts/{draft}/apply', json=body)
    assert res.status_code == 200, res.json()
    return res.json()['design']


def test_whole_text_converts_without_sections_and_quotes_its_sources(unlocked):
    c = unlocked
    wid, url = _character(c)
    draft, doc = _convert(c, wid, url)
    design = doc['candidates'][0]['design']
    assert design['appearance']['prompt']
    # The mock quotes the first line; it is in the text, so it is the source.
    assert design['appearance']['source'] == {'spans': [{'text': '한서윤은 열일곱 살 고등학생이다.', 'by': 'auto'}]}
    assert len(design['outfits']) == 1
    _apply(c, wid, draft)
    status = c.get(url).json()['status']
    assert set(status.values()) == {'fresh'}
    # No section check any more.
    issues = c.get(f'/api/works/{wid}/check').json()
    assert not [i for i in (issues.get('issues', issues) if isinstance(issues, dict) else issues) if 'section' in str(i)]


def test_reconverting_pairs_outfits_by_name_and_keeps_ids(unlocked):
    c = unlocked
    wid, url = _character(c)
    draft, _ = _convert(c, wid, url)
    first = _apply(c, wid, draft)
    ids = set(first['outfits'])
    draft, doc = _convert(c, wid, url)
    # The mock answers with the outfit names it was given.
    assert set(doc['candidates'][0]['design']['outfits']) == ids
    assert set(_apply(c, wid, draft)['outfits']) == ids


def test_ranges_convert_into_appearance_an_outfit_and_a_new_outfit(unlocked):
    c = unlocked
    wid, url = _character(c)
    hair = '검은 긴 머리를 하나로 묶고 다닌다.'
    eyes = '눈은 짙은 갈색이다.'
    uniform = '학교에서는 남색 교복 재킷에 체크 치마를 입는다.'

    draft, doc = _convert(c, wid, url, range={'part': 'appearance', 'text': hair})
    assert doc['request']['focus'] == 'appearance'
    design = _apply(c, wid, draft)
    assert design['appearance']['source'] == {'spans': [{'text': hair, 'by': 'pick'}]}

    # Adding a range keeps the first piece.
    draft, _ = _convert(c, wid, url, range={'part': 'appearance', 'text': eyes, 'add': True})
    design = _apply(c, wid, draft)
    assert [s['text'] for s in design['appearance']['source']['spans']] == [hair, eyes]

    draft, doc = _convert(c, wid, url, range={'part': 'outfit', 'text': uniform, 'name': '교복'})
    design = _apply(c, wid, draft)
    (key,) = [k for k, o in design['outfits'].items() if o['name'] == '교복']
    assert design['outfits'][key]['source']['spans'][0]['by'] == 'pick'

    draft, doc = _convert(c, wid, url, range={'part': 'outfit', 'outfit': key, 'text': uniform})
    assert doc['request']['focus'] == f'outfit:{key}'
    assert set(_apply(c, wid, draft)['outfits']) == {key}

    for bad in (
        {'part': 'outfit', 'text': uniform},  # a new outfit needs a name
        {'part': 'outfit', 'outfit': 'o99', 'text': uniform},
        {'part': 'appearance', 'text': '본문에 없는 문장'},
        {'part': 'appearance', 'text': ' '},
        {'part': 'face', 'text': hair},
    ):
        assert c.post(f'{url}/convert', json={'range': bad}).status_code in (400, 404), bad


def test_only_the_part_whose_text_changed_goes_stale(unlocked):
    c = unlocked
    wid, url = _character(c)
    hair = '검은 긴 머리를 하나로 묶고 다닌다.'
    uniform = '학교에서는 남색 교복 재킷에 체크 치마를 입는다.'
    _apply(c, wid, _convert(c, wid, url, range={'part': 'appearance', 'text': hair})[0])
    _apply(c, wid, _convert(c, wid, url, range={'part': 'outfit', 'text': uniform, 'name': '교복'})[0])
    (key,) = c.get(url).json()['design']['outfits']

    # An unrelated paragraph and line breaks inside a piece change nothing.
    _rewrite(c, wid, BODY.replace('어릴 때는 머리가 짧았다.', '어릴 때는 머리가 아주 짧았다.').replace('하나로 묶고', '하나로\n묶고'))
    assert c.get(url).json()['status'] == {'appearance': 'fresh', f'outfit:{key}': 'fresh'}

    _rewrite(c, wid, BODY.replace('체크 치마', '주름 치마'))
    assert c.get(url).json()['status'] == {'appearance': 'fresh', f'outfit:{key}': 'stale'}


def test_chosen_ranges_and_hand_edits_survive_a_whole_text_conversion(unlocked):
    c = unlocked
    wid, url = _character(c)
    hair = '검은 긴 머리를 하나로 묶고 다닌다.'
    _apply(c, wid, _convert(c, wid, url, range={'part': 'appearance', 'text': hair})[0])
    _apply(c, wid, _convert(c, wid, url)[0])
    loaded = c.get(url).json()
    design = loaded['design']
    assert design['appearance']['source']['spans'] == [{'text': hair, 'by': 'pick'}]

    # A hand edit drops the source; the next whole-text conversion leaves it too.
    (key,) = design['outfits']
    design['outfits'][key]['slots'] = {'top': {'prompt': ['navy blazer']}}
    saved = c.put(url, json={'design': design, 'base_revision': loaded['revision']}).json()['design']
    assert 'source' not in saved['outfits'][key]
    after = _apply(c, wid, _convert(c, wid, url)[0])
    assert after['outfits'][key]['slots'] == {'top': {'prompt': ['navy blazer']}}
    assert after['appearance']['source']['spans'][0]['by'] == 'pick'
    assert c.get(url).json()['status'][f'outfit:{key}'] == 'manual'


def test_samples_come_with_sources_found_in_their_text(unlocked):
    c = unlocked
    for sample in ('single', 'ensemble'):
        wid = c.post(f'/api/samples/{sample}/install').json()['id']
        loaded = c.get(f'/api/works/{wid}/image/characters/C001').json()
        assert set(loaded['status'].values()) == {'fresh'}, sample


def test_designs_from_before_150_still_read(unlocked, paths):
    import json

    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    url = f'/api/works/{wid}/image/characters/C001'
    # A design converted from sections, as written before #150.
    (path,) = paths.works.glob(f'*/.atelierx/image/characters/C001/design.json')
    legacy = json.loads(path.read_text(encoding='utf-8'))
    legacy['appearance']['source'] = {'section': 'appearance', 'hash': 'sample'}
    for outfit in legacy['outfits'].values():
        outfit['source'] = {'section': 'outfit', 'heading': outfit['name'], 'hash': 'sample'}
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding='utf-8')
    loaded = c.get(url).json()
    assert loaded['design']['appearance']['source']['section'] == 'appearance'
    assert set(loaded['status'].values()) == {'stale'}
    # Converting again writes the new form; outfits keep their ids.
    before = set(loaded['design']['outfits'])
    after = _apply(c, wid, _convert(c, wid, url)[0], design=None)
    assert set(after['outfits']) == before
    assert 'spans' in after['appearance']['source']


def test_section_titles_are_no_longer_a_work_setting(unlocked):
    c = unlocked
    wid, _ = _character(c)
    c.patch(f'/api/works/{wid}', json={'character_sections': {'appearance': '생김새'}})
    info = c.get(f'/api/works/{wid}').json()
    assert 'character_sections' not in info['doc'] and 'sections' not in info


def test_reconcile_adds_new_outfits_and_keeps_the_ones_not_named():
    from atelierx.image.designs import reconcile_conversion

    prior = {
        'appearance': {'prompt': [], 'negative': []},
        'outfits': {
            'o01': {'name': '교복', 'slots': {}, 'negative': [], 'source': {'spans': []}},
            'o02': {'name': '잠옷', 'slots': {}, 'negative': [], 'source': {'spans': []}},
        },
        'retired_outfit_ids': ['o03'],
        'default_outfit': 'o01',
    }
    generated = {
        'appearance': {'prompt': ['x'], 'negative': []},
        'outfits': {
            'o01': {'name': '교복', 'slots': {'top': {'prompt': ['blazer']}}, 'negative': []},
            'o04': {'name': '수영복', 'slots': {}, 'negative': []},
        },
    }
    merged = reconcile_conversion(prior, generated)
    assert merged['outfits']['o01']['slots'] == {'top': {'prompt': ['blazer']}}
    assert merged['outfits']['o02']['name'] == '잠옷'
    assert merged['outfits']['o04']['name'] == '수영복'
    assert merged['retired_outfit_ids'] == ['o03']
