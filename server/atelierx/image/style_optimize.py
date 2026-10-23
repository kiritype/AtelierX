"""Estimate weights only within identical ordered model/artist/LoRA configurations."""

import copy
import math


def group_key(config):
    return (
        config['model'],
        tuple(x['name'] for x in config['artists']),
        tuple(x['name'] for x in config['loras']),
    )


def suggestions(session, base, target='all'):
    from .style_flow import available, neighbours
    from .style_search import ranking, signature, valid_config

    scores = ranking(session)
    samples = [
        c
        for c in available(session)
        if group_key(c['config']) == group_key(base['config']) and scores[c['id']]['count'] >= 3
    ]
    desired = copy.deepcopy(base['config'])
    rules = session['rules']
    coordinates = []
    for kind, plural in [('artist', 'artists'), ('lora', 'loras')]:
        if target not in ('all', kind):
            continue
        for i, item in enumerate(desired[plural]):
            for field in ['weight', 'clip'] if kind == 'lora' and rules['split_clip'] else ['weight']:
                prefix = 'clip' if field == 'clip' else kind
                low, high, step = (rules[prefix + suffix] for suffix in ('_low', '_high', '_step'))
                if samples:
                    best = max(scores[c['id']]['score'] for c in samples)
                    weights = [
                        10 ** ((scores[c['id']]['score'] - best) / 400) * min(10, scores[c['id']]['count'])
                        for c in samples
                    ]
                    mean = sum(w * c['config'][plural][i][field] for w, c in zip(weights, samples)) / sum(
                        weights
                    )
                    # Snap to the user's grid, never create an off-grid upper bound.
                    tick = max(0, min(math.floor((high - low) / step + 1e-7), round((mean - low) / step)))
                    item[field] = round(low + tick * step, 8)
                coordinates.append((plural, i, field, step))
            if kind == 'lora' and not rules['split_clip']:
                item['clip'] = item['weight']

    def distance(config):
        return sum(abs(config[p][i][f] - desired[p][i][f]) / step for p, i, f, step in coordinates)

    options = sorted(neighbours(session, base['config'], target), key=lambda x: distance(x[0]))
    if desired != base['config'] and valid_config(desired, session):
        options.insert(0, (desired, 'elo weighted target'))
    seen = set()
    for config, description in options:
        key = signature(config)
        if key not in seen:
            seen.add(key)
            yield config, description
