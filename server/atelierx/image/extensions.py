"""Custom nodes in the generation graph (#178, decision 0026).

Two kinds are supported:

- **Model patches**: any ComfyUI node that takes a model and returns a model and whose other inputs are plain settings
  (numbers, switches, choices, text). They go after shift, before the sampler, in the listed order. The settings
  store only the node name and its input values; the screen builds the fields from ``/object_info``.
- **Sampler and scheduler names** from node packs (``res_3m``, ``beta57`` …). Used as they are when ComfyUI lists them.
  Some have a built-in equivalent (``ALIASES``) and work without the pack.

When something is missing the request either stops with the list (``missing: ask``, the default) or goes on without it
(``missing: skip``): patches are left out, the sampler and scheduler fall back to ``fallback`` (or the defaults).
"""

from __future__ import annotations

from typing import Any

from ..core.i18n import Msg

MAX_PATCHES = 8

# Schedulers that the built-in BetaSamplingScheduler reproduces (alpha, beta).
ALIASES = {'beta57': {'kind': 'beta', 'alpha': 0.5, 'beta': 0.7}}

_PLAIN = ('INT', 'FLOAT', 'BOOLEAN', 'STRING')


class MissingNodes(ValueError):
    """Raised for ``missing: ask`` when the settings need what ComfyUI does not have. ``missing``: what is absent."""

    def __init__(self, missing):
        self.missing = missing
        names = ', '.join(item['name'] for item in missing)
        super().__init__(
            Msg(
                'server.workflow.missing_nodes',
                'ComfyUI does not have what these settings need: {names}. Install it, or generate without it.',
                names=names,
            )
        )


def _field(spec):
    """One input of ``/object_info`` as a plain setting, or None when it is a connection (MODEL, CLIP …)."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    kind, options = spec[0], spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if isinstance(kind, list):
        return {
            'type': 'COMBO',
            'options': list(kind),
            'default': options.get('default', kind[0] if kind else None),
        }
    if kind == 'COMBO':
        choices = list(options.get('options') or [])
        return {
            'type': 'COMBO',
            'options': choices,
            'default': options.get('default', choices[0] if choices else None),
        }
    if kind not in _PLAIN:
        return None
    field = {'type': kind, 'default': options.get('default')}
    for key in ('min', 'max', 'step', 'multiline'):
        if key in options:
            field[key] = options[key]
    return field


def patch_nodes(info: dict[str, Any]) -> dict[str, Any]:
    """Nodes in ``/object_info`` usable as model patches: ``{name: {label, module, inputs: {key: field}}}``."""
    found = {}
    for name, node in (info or {}).items():
        if not isinstance(node, dict) or list(node.get('output') or []) != ['MODEL']:
            continue
        spec = node.get('input') or {}
        required, optional = spec.get('required') or {}, spec.get('optional') or {}
        model = required.get('model')
        if not model or model[0] != 'MODEL':
            continue
        inputs, usable = {}, True
        for key, value in required.items():
            if key == 'model':
                continue
            field = _field(value)
            if field is None:
                usable = False
                break
            inputs[key] = field
        if not usable:
            continue
        for key, value in optional.items():
            field = _field(value)
            if field is not None:
                inputs[key] = {**field, 'optional': True}
        found[name] = {
            'label': node.get('display_name') or name,
            'module': node.get('python_module') or '',
            'inputs': inputs,
        }
    return found


def _value(field, raw, label):
    kind = field['type']
    if kind == 'BOOLEAN':
        if not isinstance(raw, bool):
            raise ValueError(f'{label} must be true or false')
        return raw
    if kind == 'COMBO':
        if raw not in field['options']:
            raise ValueError(f'{label} must be one of its choices')
        return raw
    if kind == 'STRING':
        if not isinstance(raw, str) or len(raw) > 4000:
            raise ValueError(f'{label} must be text')
        return raw
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f'{label} must be a number')
    if kind == 'INT':
        if raw != int(raw):
            raise ValueError(f'{label} must be an integer')
        raw = int(raw)
    low, high = field.get('min'), field.get('max')
    if (low is not None and raw < low) or (high is not None and raw > high):
        raise ValueError(f'{label} must be between {low} and {high}')
    return raw


def validate_patches(value, catalog):
    """Normalize ``patches``; returns (patches, missing names). Missing nodes keep their stored values unchecked."""
    if value in (None, ''):
        return [], []
    if not isinstance(value, list):
        raise ValueError('patches must be a list')
    if len(value) > MAX_PATCHES:
        raise ValueError(f'patches cannot contain more than {MAX_PATCHES} entries')
    known = catalog.get('patch_nodes')
    out, missing = [], []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not isinstance(item.get('node'), str) or not item['node']:
            raise ValueError(f'patches[{index}].node must be a node name')
        raw = item.get('inputs') or {}
        if not isinstance(raw, dict):
            raise ValueError(f'patches[{index}].inputs must be an object')
        entry = {'node': item['node'], 'inputs': dict(raw)}
        if item.get('enabled') is False:
            entry['enabled'] = False
        spec = known.get(item['node']) if isinstance(known, dict) else None
        if spec is None:
            # A catalog that does not list patch nodes (tests, older callers) takes the values as they are.
            if isinstance(known, dict) and entry.get('enabled') is not False:
                missing.append(item['node'])
            out.append(entry)
            continue
        inputs = {}
        for key, field in spec['inputs'].items():
            if key in raw:
                inputs[key] = _value(field, raw[key], f'patches[{index}].inputs.{key}')
            elif not field.get('optional'):
                inputs[key] = field.get('default')
        unknown = set(raw) - set(spec['inputs'])
        if unknown:
            raise ValueError(f'patches[{index}].inputs has unknown keys: {", ".join(sorted(unknown))}')
        entry['inputs'] = inputs
        out.append(entry)
    return out, missing


def resolve_names(result, catalog, choices_of):
    """Check ``sampler`` and ``scheduler``; returns the names ComfyUI does not have (aliases count as present).

    Sets ``result['sigmas']`` for a scheduler served by a built-in alias.
    """
    result.pop('sigmas', None)
    missing = []
    samplers, schedulers = choices_of('samplers'), choices_of('schedulers')
    if samplers and result.get('sampler') not in samplers:
        missing.append(('sampler', result.get('sampler')))
    scheduler = result.get('scheduler')
    if schedulers and scheduler not in schedulers:
        if scheduler in ALIASES:
            result['sigmas'] = dict(ALIASES[scheduler])
        else:
            missing.append(('scheduler', scheduler))
    return missing


def validate_fallback(value, choices_of):
    if value in (None, ''):
        return None
    if not isinstance(value, dict):
        raise ValueError('fallback must be an object')
    out = {}
    for key, catalog_key in (('sampler', 'samplers'), ('scheduler', 'schedulers')):
        name = value.get(key)
        if name in (None, ''):
            continue
        if name not in choices_of(catalog_key):
            raise ValueError(f'fallback.{key} must be one of the available {catalog_key}')
        out[key] = name
    return out or None


def apply(result, catalog, choices_of, defaults):
    """Validate the custom-node parts of ``result`` in place and apply the missing policy."""
    policy = result.get('missing') or 'ask'
    if policy not in ('ask', 'skip'):
        raise ValueError("missing must be 'ask' or 'skip'")
    result['fallback'] = validate_fallback(result.get('fallback'), choices_of)
    patches, missing_patches = validate_patches(result.get('patches'), catalog)
    missing_names = resolve_names(result, catalog, choices_of)
    missing = [{'kind': kind, 'name': name} for kind, name in missing_names] + [
        {'kind': 'patch', 'name': name} for name in missing_patches
    ]
    result.pop('skipped', None)
    if missing and policy == 'ask':
        raise MissingNodes(missing)
    if missing:
        fallback = result['fallback'] or {}
        for kind, _ in missing_names:
            result[kind] = fallback.get(kind) or defaults[kind]
        patches = [p for p in patches if p['node'] not in missing_patches]
        result['skipped'] = [item['name'] for item in missing]
    result['patches'] = patches
    result['missing'] = policy
    for key in ('fallback', 'patches'):
        if not result[key]:
            result.pop(key)
    if result.get('missing') == 'ask':
        result.pop('missing')
    return result


def known_packs(manifest):
    """``{name: pack}`` for the sampler, scheduler and node names the listed packs provide (installable or not)."""
    names = {}
    for pack, installable in [(n, True) for n in manifest.get('nodes', [])] + [
        (n, False) for n in manifest.get('known', [])
    ]:
        for name in pack.get('provides') or []:
            names[name] = {
                'id': pack['id'],
                'repo': pack.get('repo'),
                'license': pack.get('license'),
                'installable': installable,
                'note': pack.get('note'),
            }
    return names
