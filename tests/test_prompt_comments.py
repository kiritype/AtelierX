"""Notes in image prompts (#157): kept where they are written, left out of what is sent."""

import json

from atelierx.image.comments import strip_tag, strip_text


def test_a_note_starts_a_tag_and_runs_to_the_end_of_the_line():
    assert strip_tag('# why this tag') == ''
    assert strip_tag('smile # keeps the mood light') == 'smile'
    # A # inside a tag is part of it; a tag that starts with # is escaped.
    assert strip_tag('memories_off#5') == 'memories_off#5'
    assert strip_tag('ririka_(#compass)') == 'ririka_(#compass)'
    assert strip_tag('\\#compass') == '#compass'
    text = 'masterpiece, smile, # tried: grin, laughing\n# whole line\nblue sky,#gone\n\\#compass, (a, b:1.2)'
    assert strip_text(text) == 'masterpiece, smile\nblue sky\n#compass, (a, b:1.2)'
    assert strip_text('# only a note') == ''


def test_notes_stay_out_of_the_composed_prompt(unlocked):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    c.put(
        '/api/image/library/common/noted',
        json={
            'scope': 'work',
            'work': wid,
            'item': {
                'name': 'noted',
                'prompt': ['soft light', '# from the reference sheet', 'film grain # maybe'],
            },
        },
    )
    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    body = {'targets': [target], 'common_ids': ['noted'], 'settings': {'family': 'anima'}}
    composed = c.post(f'/api/works/{wid}/image/compose', json=body).json()[0]
    assert 'soft light' in composed['positive'] and 'film grain' in composed['positive']
    assert '#' not in composed['positive'] and 'maybe' not in composed['positive']
    edited = c.post(
        f'/api/works/{wid}/image/compose',
        json={**body, 'overrides': {'artist': 'soft light, # off for now\nrim light'}},
    ).json()[0]
    assert edited['parts']['artist'] == 'soft light\nrim light'
    # The note stays in the library item.
    saved = c.get('/api/image/library/common', params={'work': wid}).json()
    assert '# from the reference sheet' in json.dumps(saved, ensure_ascii=False)
