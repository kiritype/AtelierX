"""Two-character Anima inputs, preserved separately from the composed prompt."""

from ..core.i18n import Msg


def clean_multi(value, service, family):
    if value is None:
        return None
    if service != 'comfyui' or family != 'anima':
        raise ValueError(
            Msg('server.multi.service', 'Two-character generation currently supports ComfyUI Anima only.')
        )
    if not isinstance(value, dict) or set(value) - {'characters', 'left_id'}:
        raise ValueError(Msg('server.multi.invalid', 'Choose two characters and their left/right placement.'))
    people = value.get('characters')
    if not isinstance(people, list) or len(people) != 2:
        raise ValueError(Msg('server.multi.invalid', 'Choose two characters and their left/right placement.'))
    cleaned = []
    for person in people:
        if not isinstance(person, dict) or set(person) - {'id', 'name', 'prompt'}:
            raise ValueError(
                Msg('server.multi.invalid', 'Choose two characters and their left/right placement.')
            )
        for key in ('id', 'name', 'prompt'):
            if not isinstance(person.get(key), str) or len(person[key]) > (10000 if key == 'prompt' else 100):
                raise ValueError(
                    Msg('server.multi.invalid', 'Choose two characters and their left/right placement.')
                )
        if not person['id'].strip() or not person['prompt'].strip():
            raise ValueError(
                Msg('server.multi.empty', 'Enter the appearance and clothing for both characters.')
            )
        cleaned.append({key: person[key].strip() for key in ('id', 'name', 'prompt')})
    ids = {person['id'] for person in cleaned}
    if len(ids) != 2 or value.get('left_id') not in ids:
        raise ValueError(Msg('server.multi.invalid', 'Choose two characters and their left/right placement.'))
    return {'characters': cleaned, 'left_id': value['left_id']}


def compose_multi(scene, multi):
    left = next(p for p in multi['characters'] if p['id'] == multi['left_id'])
    right = next(p for p in multi['characters'] if p['id'] != multi['left_id'])
    return f'Two people. {scene}. On the left: {left["prompt"]}. On the right: {right["prompt"]}.'
