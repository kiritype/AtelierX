"""Training captions built from an image's generation record.

Order follows the trainer guide: rating, count, character trigger, outfit trigger, then general tags (framing,
plain background, expression). Appearance and outfit tags are left out on purpose: the triggers are meant to
carry them.
"""

import re

BACKGROUND_TAGS = ('white background', 'simple background')
SENTENCE = re.compile(r'^[A-Z].* .* ')
# The image library's rating ids → the rating word Anima was trained with.
RATING_WORDS = {
    'general': 'safe',
    'safe': 'safe',
    'sensitive': 'sensitive',
    'questionable': 'nsfw',
    'explicit': 'explicit',
}


def tags_of(text, stop_at_sentence=True):
    """Comma tags without weights; stops at the first natural-language sentence."""
    out = []
    for token in (t.strip() for t in str(text or '').split(',')):
        token = re.sub(r'^\((.*):[\d.]+\)$', r'\1', token).strip().rstrip('.')
        if not token:
            continue
        if stop_at_sentence and SENTENCE.match(token):
            break
        out.append(token)
    return out


def caption(meta, triggers):
    """Caption for one image. ``meta`` is the image's generation record."""
    parts = meta.get('parts') or {}
    appearance = tags_of(parts.get('appearance'))
    count = next((t for t in appearance if re.fullmatch(r'\d(girl|boy)s?', t)), '1girl')
    general = (['solo'] if 'solo' in appearance else []) + tags_of(parts.get('composition'))
    general += [t for t in tags_of(parts.get('common'), stop_at_sentence=False) if t in BACKGROUND_TAGS]
    general += [t for t in tags_of(parts.get('expression')) if t != 'pov']
    rating = RATING_WORDS.get(str(meta.get('rating') or 'general'), 'nsfw')
    ordered, seen = [], set()
    for tag in [rating, count, triggers.get('character', ''), triggers.get('outfit', ''), *general]:
        if tag and tag not in seen:
            seen.add(tag)
            ordered.append(tag)
    return ', '.join(ordered)


def default_triggers(work_id, character_id, design, outfit_ids):
    """The design's trigger (or w001_c001), and an outfit trigger when the dataset is one outfit."""
    character = design.get('trigger') or f'{work_id}_{character_id}'.lower()
    outfit = f'{character}_{outfit_ids[0]}'.lower() if len(outfit_ids) == 1 else ''
    return {'character': character, 'outfit': outfit}
