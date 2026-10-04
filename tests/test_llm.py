from atelierx.core.llm import _split_think, parse_json, strip_thinking


def run(pieces):
    state = {'inside': False, 'buffer': '', 'thought': 0, 'reported': 0}
    text = ''.join(e['text'] for p in pieces for e in _split_think(state, p))
    if state['buffer'] and not state['inside']:
        text += state['buffer']
    return text, state['thought']


def test_think_blocks_are_hidden_across_piece_boundaries():
    text, thought = run(['안녕 <thi', 'nk>속생각', '입니다</th', 'ink>  하세요', '!'])
    assert text == '안녕 하세요!'
    assert thought > 0


def test_text_that_only_looks_like_a_tag_start_is_kept():
    assert run(['a <b', 'old> c'])[0] == 'a <bold> c'
    assert run(['끝 <'])[0] == '끝 <'


def test_strip_and_parse_json():
    assert strip_thinking('<think>x</think>\n답') == '답'
    assert strip_thinking('<think>끝나지 않음') == ''
    assert parse_json('설명\n```json\n{"a": 1}\n```') == {'a': 1}
    assert parse_json('앞말 {"b": [1, 2]} 뒷말') == {'b': [1, 2]}
    assert parse_json('없음') is None
