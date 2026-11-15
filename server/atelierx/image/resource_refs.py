"""Portable references to the exact files used by a preset (#329). No local absolute paths."""

import re
from pathlib import PureWindowsPath
from urllib.parse import parse_qs, urlsplit

HASH = re.compile(r'[a-fA-F0-9]{64}')


def safe_name(value):
    if not isinstance(value, str) or not value or len(value) > 500:
        return False
    path = PureWindowsPath(value)
    return (
        not path.is_absolute()
        and not path.drive
        and not path.root
        and all(part not in ('.', '..') and not re.search(r'[<>:"|?*\x00-\x1f]', part) for part in path.parts)
    )


def references(preset):
    if preset.get('service', 'comfyui') != 'comfyui':
        return []
    settings = preset.get('settings') or {}
    wanted = []
    for slot, kind in (('model', 'model'), ('text_encoder', 'text_encoder'), ('vae', 'vae')):
        if settings.get(slot):
            wanted.append((slot, kind, str(settings[slot]).removeprefix('checkpoint::')))
    for i, item in enumerate(settings.get('loras') or []):
        if isinstance(item, dict) and item.get('name') and item.get('enabled') is not False:
            wanted.append((f'loras.{i}.name', 'lora', item['name']))
    upscale = settings.get('upscale') or {}
    if isinstance(upscale, dict) and upscale.get('model'):
        wanted.append(('upscale.model', 'upscale_model', upscale['model']))
    saved = preset.get('resources') or []
    out = []
    for slot, kind, name in wanted:
        if not safe_name(name):
            continue
        resource = {'slot': slot, 'kind': kind, 'name': name}
        old = next(
            (
                r
                for r in saved
                if isinstance(r, dict)
                and r.get('kind') == kind
                and r.get('name') == name
                and r.get('slot', slot) == slot
            ),
            {},
        )
        if HASH.fullmatch(str(old.get('sha256', ''))):
            resource['sha256'] = old['sha256'].lower()
        for field in ('model_id', 'version_id', 'file_id', 'size'):
            value = old.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                resource[field] = value
        # Older ZIPs stored only a Civitai page; accept only that provider, never an arbitrary download URL.
        try:
            url = urlsplit(str(old.get('civitai', '')))
            match = re.fullmatch(r'/models/(\d+)/?', url.path)
            if url.scheme == 'https' and url.netloc == 'civitai.com' and match:
                resource.setdefault('model_id', int(match[1]))
                version = parse_qs(url.query).get('modelVersionId', [''])[0]
                if version.isdigit():
                    resource.setdefault('version_id', int(version))
        except ValueError:
            pass
        if resource.get('model_id'):
            resource['civitai'] = f'https://civitai.com/models/{resource["model_id"]}'
            if resource.get('version_id'):
                resource['civitai'] += f'?modelVersionId={resource["version_id"]}'
        out.append(resource)
    return out


def bind(settings, slot, name):
    """Update precisely the field represented by a reference; callers first compare its old reference."""
    if slot.startswith('loras.'):
        settings['loras'][int(slot.split('.')[1])]['name'] = name
    elif slot == 'upscale.model':
        settings['upscale']['model'] = name
    else:
        settings[slot] = name
