"""Component calls are read with the platform preset's response rule; JSX examples are calls."""

import json

import pytest

from atelierx.core import review
from atelierx.core.jsx import Props, call_text
from atelierx.core.works import Work

CALL = "<Asset c='C001' o='001' e='010' bg='002' n='2' data='{\"hp\": 3,}' />"


def attrs(rule):
    return review.elements(CALL, 'Asset', rule)[0]


def test_text_keeps_every_value_as_written():
    found = attrs({'attribute_format': 'text'})
    assert found['attrs'] == {
        'c': 'C001',
        'o': '001',
        'e': '010',
        'bg': '002',
        'n': '2',
        'data': '{"hp": 3,}',
    }
    assert found['errors'] == []


def test_lenient_json_reads_json_and_keeps_plain_words():
    found = attrs({'attribute_format': 'json_lenient'})
    assert found['attrs'] == {'c': 'C001', 'o': '001', 'e': '010', 'bg': '002', 'n': 2, 'data': {'hp': 3}}
    assert found['errors'] == []
    assert review.elements("<Asset data='{broken' />", 'Asset')[0]['errors']  # looks like JSON but is not


def test_strict_json_refuses_plain_words():
    found = attrs({'attribute_format': 'json'})
    assert {e.split(':')[0] for e in found['errors']} >= {'c', 'o', 'data'}


def test_decode_table_runs_before_reading():
    rule = {'attribute_format': 'text', 'decode': [['&apos;', "'"], {'from': '[[', 'to': '<'}]}
    assert review.elements('[[Asset c=&apos;C001&apos; />', 'Asset', rule)[0]['attrs'] == {'c': 'C001'}


@pytest.fixture
def simulation(unlocked, tmp_path):
    wid = unlocked.post('/api/samples/simulation/install').json()['id']
    folder = next(p for p in (tmp_path / 'data' / 'works').iterdir() if p.is_dir())
    jid = next(i['meta']['id'] for i in Work(folder).index() if i['kind'] == 'jsx')
    return wid, folder, jid


def test_examples_are_calls_and_old_json_examples_become_calls(unlocked, simulation):
    wid, folder, jid = simulation
    url = f'/api/works/{wid}/jsx/{jid}/props'
    listed = {e['name']: e for e in unlocked.get(url).json()}
    assert listed['basic']['text'].startswith('<StatusPanel data=') and not listed['basic']['legacy']

    props = folder / '.atelierx' / 'jsx' / jid / 'props'
    (props / 'old.json').write_text(json.dumps({'data': {'day': 3}, 'label': "it's"}), encoding='utf-8')
    old = next(e for e in unlocked.get(url).json() if e['name'] == 'old')
    assert old['legacy'] and old['text'].strip() == call_text(
        'StatusPanel', {'data': {'day': 3}, 'label': "it's"}
    )
    assert review.elements(old['text'], 'StatusPanel')[0]['attrs'] == {'data': {'day': 3}, 'label': "it's"}

    saved = unlocked.put(f'{url}/old', content=old['text'].encode('utf-8'))
    assert (
        saved.status_code == 200 and (props / 'old.txt').is_file() and (props / 'old.json').is_file()
    )  # kept
    assert unlocked.put(f'{url}/empty', content=b'  ').status_code == 400


def test_the_chat_reads_the_default_example_with_the_work_rule(simulation):
    _, folder, jid = simulation
    examples = Props(Work(folder), jid, 'StatusPanel')
    assert examples.props('basic', {'attribute_format': 'json_lenient'})['data']['gold'] == 120
    assert isinstance(examples.props('basic', {'attribute_format': 'text'})['data'], str)


def test_a_platform_preset_sets_how_attribute_values_are_read(unlocked):
    unlocked.post('/api/platforms', json={'id': 'rp', 'name': 'RP'})
    preset = unlocked.get('/api/platforms/rp').json()
    bad = {**preset, 'jsx': {'response': {'attribute_format': 'yaml'}}}
    assert unlocked.put('/api/platforms/rp', json=bad).status_code == 400
    good = {**preset, 'jsx': {'response': {'syntax': 'element', 'attribute_format': 'text'}}}
    saved = unlocked.put('/api/platforms/rp', json=good).json()
    assert saved['jsx']['response']['attribute_format'] == 'text'


@pytest.mark.parametrize(
    ('props', 'rule'),
    [
        ({'data': {'label': "it's", 'quote': 'say "hi"'}}, None),
        ({'label': '123', 'flag': 'true', 'none': None, 'n': 2}, None),
        ({'label': 'C001'}, {'attribute_format': 'json'}),
        ({'label': 'C001', 'mixed': 'a"b\'c'}, None),
        ({'c': 'C001', 'o': '001'}, {'attribute_format': 'text'}),
    ],
)
def test_old_json_examples_convert_to_calls_with_the_same_values(props, rule):
    call = call_text('Panel', props, rule)
    assert call and review.elements(call, 'Panel', rule)[0]['attrs'] == props


def test_values_a_text_rule_cannot_carry_stay_as_json_and_the_file_is_kept(unlocked, simulation):
    _, folder, jid = simulation
    assert call_text('Panel', {'n': 2}, {'attribute_format': 'text'}) is None
    props = folder / '.atelierx' / 'jsx' / jid / 'props'
    (props / 'counts.json').write_text(json.dumps({'data': {'day': 3}}), encoding='utf-8')
    examples = Props(Work(folder), jid, 'StatusPanel', {'attribute_format': 'text'})
    entry = examples.entry('counts')
    assert entry['convert_error'] and json.loads(entry['text']) == {'data': {'day': 3}}
    assert examples.props('counts') == {'data': {'day': 3}}  # the chat still gets the JSON props

    examples.save('counts', '<StatusPanel data=\'{"day": 4}\' />')
    assert (props / 'counts.json').is_file()  # the old JSON is never deleted by a save
    assert examples.entry('counts')['text'].startswith('<StatusPanel')
