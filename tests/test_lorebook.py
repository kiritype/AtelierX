from atelierx.core.lorebook import ACTIVATION_DEFAULTS, activation_of


def test_defaults_when_missing():
    assert activation_of({}) == ACTIVATION_DEFAULTS
    assert activation_of({'activation': 'x'}) == ACTIVATION_DEFAULTS


def test_valid_values_kept_and_invalid_dropped():
    meta = {
        'activation': {
            'in_start': False,
            'scan_depth': 0,
            'mode': 'off_match',
            'group': ' 날씨 ',
            'requires': ['L002'],
            'later': 1,
        }
    }
    assert activation_of(meta) == {
        'in_start': False,
        'scan_depth': 0,
        'mode': 'off_match',
        'group': '날씨',
        'requires': ['L002'],
    }
    assert (
        activation_of({'activation': {'scan_depth': 9, 'mode': 'x', 'in_start': 'no'}}) == ACTIVATION_DEFAULTS
    )
    assert activation_of({'activation': {'scan_depth': 'all'}})['scan_depth'] == 'all'
