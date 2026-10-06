"""Prompt composition (06-image-prompts: 조합): a character's design + the image library -> positive / negative.

A target names one character, one outfit and one expression. The composition comes from the request or the
expression's suggestion; it also suggests which outfit slots are visible. Common prompts and styles come from
the request (or a generation preset). Parts are joined in the order of compose.json.
"""

from ..core.i18n import Msg
from . import library
from .util import read_json

OVERRIDABLE = ('common', 'style', 'composition', 'trigger', 'appearance', 'expression', 'outfit', 'negative')
MAX_OVERRIDE = 30000


def _join(*groups):
    out = []
    for group in groups:
        for tag in group or []:
            tag = str(tag).strip()
            if tag and tag not in out:
                out.append(tag)
    return out


def design_of(work, character_id):
    design = read_json(work.app / 'image' / 'characters' / character_id / 'design.json')
    if not design:
        raise ValueError(
            Msg(
                'server.image.compose.no_design',
                'Character {id} has no image design yet. Convert its appearance and outfits first.',
                id=character_id,
            )
        )
    return design


class Composer:
    """Loads the library once per request so composing many targets stays cheap."""

    def __init__(self, paths, work):
        self.paths, self.work = paths, work
        self.rules = library.compose_rules(paths)
        self.lib = {kind: library.items(paths, work, kind) for kind in library.KINDS}
        self.designs = {}

    def design(self, character_id):
        if character_id not in self.designs:
            self.designs[character_id] = design_of(self.work, character_id)
        return self.designs[character_id]

    def has_lora(self, character_id):
        models = (
            read_json(self.work.app / 'image' / 'characters' / character_id / 'lora' / 'models.json') or {}
        )
        return any(m.get('enabled', True) for m in models.get('models', []))

    def _pick(self, kind, ident, label):
        item = self.lib[kind].get(ident)
        if item is None:
            raise ValueError(
                Msg('server.image.compose.not_found', '{label} not found: {id}', label=label, id=ident)
            )
        return item

    def _slot(self, outfit, slot):
        entry = (outfit.get('slots') or {}).get(slot) or {}
        if entry.get('ref'):
            ident = str(entry['ref']).split(':', 1)[-1]
            part = self.lib['outfits'].get(ident)
            if part is None:
                raise ValueError(
                    Msg(
                        'server.image.compose.outfit_ref',
                        'Shared outfit part not found: {id}',
                        id=entry['ref'],
                    )
                )
            return part.get('prompt', []), part.get('negative', [])
        return entry.get('prompt', []), entry.get('negative', [])

    def compose(self, target, options=None):
        options = options or {}
        character_id = str(target.get('character_id') or '')
        design = self.design(character_id)
        outfit_id = target.get('outfit_id') or design.get('default_outfit')
        outfit = (design.get('outfits') or {}).get(outfit_id)
        if outfit is None:
            raise ValueError(
                Msg('server.image.compose.no_outfit', 'Outfit {id} is not in this design.', id=outfit_id)
            )
        expression = self._pick('expressions', target.get('expression_id'), 'Expression')
        composition_id = (
            target.get('composition_id') or options.get('composition_id') or expression.get('composition')
        )
        composition = self._pick('compositions', composition_id, 'Composition') if composition_id else None

        order = [s['id'] for s in self.rules['slots']]
        defined = [s for s in order if s in (outfit.get('slots') or {})]
        wanted = target.get('outfit_slots') or options.get('outfit_slots')
        if not wanted and composition and composition.get('suggest_slots'):
            # 'full' (one-piece outfits) always shows; otherwise only what the framing reveals.
            wanted = [*composition['suggest_slots'], 'full']
        slots = [s for s in defined if not wanted or s in wanted]
        outfit_prompt, outfit_negative = [], list(outfit.get('negative') or [])
        for slot in slots:
            prompt, negative = self._slot(outfit, slot)
            outfit_prompt += prompt
            outfit_negative += negative

        common_ids = options.get('common_ids')
        if common_ids is None:
            common_ids = [i for i, c in self.lib['common'].items() if c.get('default', True)]
        commons = [self._pick('common', i, 'Common prompt') for i in common_ids]
        styles = [self._pick('styles', i, 'Style') for i in options.get('style_ids') or []]

        # Items written for other targets (#80) stay out of the prompt and are named in the warnings. The expression
        # is what the image is of, so it stays and is only named.
        family = options.get('family') or 'anima'
        names = {t['id']: t['name'] for t in self.rules['targets']}
        warnings = []

        def unfit(label, record, left_out=True):
            targets = ', '.join(names.get(t, t) for t in record.get('targets') or [])
            if left_out:
                msg = Msg(
                    'server.image.compose.left_out',
                    '{label} {id} is for {targets}, so it was left out.',
                    label=label,
                    id=record['id'],
                    targets=targets,
                )
            else:
                msg = Msg(
                    'server.image.compose.other_target',
                    '{label} {id} is for {targets}.',
                    label=label,
                    id=record['id'],
                    targets=targets,
                )
            warnings.append(msg)

        if not library.fits(expression, family):
            unfit('expression', expression, left_out=False)
        if composition and not library.fits(composition, family):
            unfit('composition', composition)
            composition = None
        for label, records in (('common', commons), ('style', styles)):
            for record in [r for r in records if not library.fits(r, family)]:
                unfit(label, record)
                records.remove(record)

        parts = {
            'common': _join(*(c.get('prompt') for c in commons if c.get('target') != 'negative')),
            'style': _join(*(s.get('prompt') for s in styles)),
            'composition': _join(composition.get('prompt') if composition else []),
            # The trigger word only means something to a LoRA trained on it: by default it is added when the
            # character has a registered LoRA; options['trigger'] True/False forces it on or off.
            'trigger': _join(
                [design.get('trigger')]
                if design.get('trigger')
                and (
                    options.get('trigger')
                    if options.get('trigger') is not None
                    else self.has_lora(character_id)
                )
                else []
            ),
            'appearance': _join((design.get('appearance') or {}).get('prompt')),
            'expression': _join(expression.get('prompt')),
            'outfit': _join(outfit_prompt),
        }
        negative = _join(
            *(c.get('prompt') for c in commons if c.get('target') == 'negative'),
            *(s.get('negative') for s in styles),
            (design.get('appearance') or {}).get('negative'),
            outfit_negative,
            expression.get('negative'),
            composition.get('negative') if composition else [],
        )
        texts = {key: ', '.join(value) for key, value in parts.items()}
        texts['negative'] = ', '.join(negative)
        overrides = options.get('overrides') or {}
        for key in OVERRIDABLE:
            if key in overrides:
                value = overrides[key]
                if not isinstance(value, str) or len(value) > MAX_OVERRIDE:
                    raise ValueError(
                        Msg(
                            'server.image.compose.override',
                            'A prompt edit must be text of at most 30,000 characters.',
                        )
                    )
                texts[key] = value.strip()

        order_keys = [k for k in self.rules['order'] if k in parts]
        return {
            'character_id': character_id,
            'outfit_id': outfit_id,
            'outfit_name': outfit.get('name', outfit_id),
            'expression_id': expression['id'],
            'expression_name': expression.get('name', expression['id']),
            'rating': expression.get('rating'),
            'composition_id': composition['id'] if composition else None,
            'outfit_slots': slots,
            'common_ids': common_ids,
            'style_ids': options.get('style_ids') or [],
            'trigger': design.get('trigger'),
            'model_family': family,
            'parts': texts,
            'positive': ', '.join(texts[k] for k in order_keys if texts[k]),
            'negative': texts['negative'],
            'warnings': warnings,
        }
