"""Image services on the internet (#41): which ones are set up, the vault entry of each key, and the per-run limit.

Stored in data/image/services.json. A key is never written here, only ``secret:<vault entry>`` (decision 0011), so the
file can travel in a settings package without credentials. ComfyUI on this PC is configured elsewhere (connection).
"""

import re

from ..core.i18n import Msg
from .util import atomic_json, read_json

KNOWN = {'novelai': 'NovelAI', 'pixai': 'PixAI'}
DEFAULT_LIMIT = 50  # images one "Add to queue" may ask an internet service for; 0 = no limit
MAX_LIMIT = 100000
DEFAULT_INTERVAL = 3.0  # seconds between two requests to the same service
MAX_INTERVAL = 600
WITH_LORAS = ('pixai',)  # services whose own LoRAs can be listed here
LORA_ID = re.compile(r'^\d{6,25}$')
MAX_LORAS_LISTED = 200


class ServiceConfig:
    def __init__(self, paths, vault):
        self.file = paths.data / 'image' / 'services.json'
        self.vault = vault

    def doc(self):
        raw = read_json(self.file, {}) or {}
        services = {}
        for ident, entry in (raw.get('services') or {}).items():
            if ident in KNOWN and isinstance(entry, dict):
                services[ident] = {
                    'key': entry.get('key') if _is_reference(entry.get('key')) else None,
                    'interval': _interval(entry.get('interval')),
                }
                if ident in WITH_LORAS:
                    services[ident]['loras'] = _clean_loras(entry.get('loras'), strict=False)
        limit = raw.get('max_images_per_run', DEFAULT_LIMIT)
        return {
            'schema_version': 1,
            'max_images_per_run': limit if _whole(limit, MAX_LIMIT) else DEFAULT_LIMIT,
            'services': services,
        }

    def save(self, doc):
        if not isinstance(doc, dict):
            raise ValueError(Msg('server.image.services.invalid', 'Image service settings are required.'))
        limit = doc.get('max_images_per_run', DEFAULT_LIMIT)
        if not _whole(limit, MAX_LIMIT):
            raise ValueError(
                Msg(
                    'server.image.services.limit',
                    'The image limit per run must be a whole number from 0 (no limit) to {max}.',
                    max=MAX_LIMIT,
                )
            )
        services = {}
        for ident, entry in (doc.get('services') or {}).items():
            if ident not in KNOWN or not isinstance(entry, dict):
                raise ValueError(
                    Msg('server.image.services.unknown', 'Unknown image service: {id}', id=ident)
                )
            key = entry.get('key') or None
            if key is not None and not _is_reference(key):
                raise ValueError(
                    Msg(
                        'server.llm.secret_reference',
                        'Save credentials in Settings and select the saved entry.',
                    )
                )
            interval = entry.get('interval', DEFAULT_INTERVAL)
            if (
                isinstance(interval, bool)
                or not isinstance(interval, (int, float))
                or not 0 <= interval <= MAX_INTERVAL
            ):
                raise ValueError(
                    Msg(
                        'server.image.services.interval',
                        'The wait between requests must be 0 to {max} seconds.',
                        max=MAX_INTERVAL,
                    )
                )
            services[ident] = {'key': key, 'interval': float(interval)}
            if ident in WITH_LORAS:
                services[ident]['loras'] = _clean_loras(entry.get('loras'), strict=True)
        out = {'schema_version': 1, 'max_images_per_run': limit, 'services': services}
        atomic_json(self.file, out)
        return out

    def key(self, ident):
        """The service's key from the vault, or None when it is not set up (or the app is locked)."""
        entry = self.doc()['services'].get(ident) or {}
        reference = entry.get('key')
        if not reference:
            return None
        try:
            return self.vault.reveal(reference[len('secret:') :]) or None
        except Exception:  # locked vault: the same as no key
            return None

    def loras(self, ident):
        return (self.doc()['services'].get(ident) or {}).get('loras') or []

    def interval(self, ident):
        return (self.doc()['services'].get(ident) or {}).get('interval', DEFAULT_INTERVAL)

    def limit(self):
        return self.doc()['max_images_per_run']

    def public(self, available):
        """What the settings and generate screens show: each known service, whether the app can use it and why not."""
        doc = self.doc()
        listed = []
        for ident, name in KNOWN.items():
            entry = doc['services'].get(ident) or {}
            ready = ident in available
            listed.append(
                {
                    'id': ident,
                    'name': name,
                    'key': entry.get('key'),
                    'interval': entry.get('interval', DEFAULT_INTERVAL),
                    'supported': ready,
                    'connected': ready and self.key(ident) is not None,
                    **({'loras': entry.get('loras') or []} if ident in WITH_LORAS else {}),
                }
            )
        return {'max_images_per_run': doc['max_images_per_run'], 'services': listed}


def _clean_loras(value, strict):
    """PixAI LoRAs registered from their Model Market address: version id, a name, default weight and trigger words."""
    out, seen = [], set()
    for entry in value if isinstance(value, list) else []:
        ident = str((entry or {}).get('id') or '') if isinstance(entry, dict) else ''
        weight = entry.get('weight', 1.0) if isinstance(entry, dict) else None
        good_weight = isinstance(weight, (int, float)) and not isinstance(weight, bool) and 0 <= weight <= 1
        if not LORA_ID.match(ident) or not good_weight:
            if strict:
                raise ValueError(
                    Msg(
                        'server.image.services.lora',
                        'A LoRA needs the version id from its PixAI address and a weight from 0 to 1.',
                    )
                )
            continue
        if ident in seen:
            continue
        seen.add(ident)
        out.append(
            {
                'id': ident,
                'name': str(entry.get('name') or ident).strip()[:100],
                'weight': float(weight),
                'trigger_words': str(entry.get('trigger_words') or '').strip()[:500],
            }
        )
    return out[:MAX_LORAS_LISTED]


def _is_reference(value):
    return isinstance(value, str) and value.startswith('secret:') and len(value) > len('secret:')


def _whole(value, top):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= top


def _interval(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_INTERVAL:
        return DEFAULT_INTERVAL
    return float(value)
