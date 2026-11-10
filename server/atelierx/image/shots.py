"""Visual shot choices map to prompt hints, not camera parameters."""

from ..core.i18n import Msg

SHOT_FRAMING = {
    'face': {'prompt': 'close-up portrait, face focus, head and shoulders only', 'slots': []},
    'upper': {
        'prompt': 'upper body, chest-up portrait, medium close-up',
        'slots': ['full', 'hands', 'top'],
    },
    'cowboy': {'prompt': 'cowboy shot', 'slots': ['full', 'hands', 'top', 'bottom']},
    'full': {'prompt': 'full body', 'slots': None},
}
SHOT_DIRECTION = {
    'front': 'straight-on',
    'three_quarter': 'three-quarter view',
    'side': 'profile, from side, facing sideways',
    'back': 'back view, facing away, back of head',
}
SHOT_HEIGHT = {'eye': 'eye level', 'high': 'from above', 'low': 'from below'}

SHOT_CHOICES = {'framing': SHOT_FRAMING, 'direction': SHOT_DIRECTION, 'height': SHOT_HEIGHT}


def clean_shot(value):
    if value is None:
        return None
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str) or value[key] not in choices
        for key, choices in SHOT_CHOICES.items()
    ):
        raise ValueError(
            Msg('server.image.compose.invalid_shot', 'Choose a valid framing, direction and camera height.')
        )
    return {key: value[key] for key in SHOT_CHOICES}


def shot_tags(shot):
    return [
        SHOT_FRAMING[shot['framing']]['prompt'],
        SHOT_DIRECTION[shot['direction']],
        SHOT_HEIGHT[shot['height']],
    ]
