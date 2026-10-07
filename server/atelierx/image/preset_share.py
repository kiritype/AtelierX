"""Style presets shared as one ZIP (#169): the preset files, their previews, and what each needs.

Model and LoRA files are never packed. The list names each file the preset uses with its hash and Civitai page when this
PC knows them (Stability Matrix's ``.cm-info.json``), so the other side can find what it lacks. Importing shows each
preset first (new, already here) with the files missing on that PC, then applies the person's choice per preset:
add, replace, add under another id, or skip.
"""

from __future__ import annotations

import io
import json
import secrets
import time
import zipfile
from pathlib import Path, PureWindowsPath

from .. import __version__
from ..core.i18n import Msg
from . import library
from .util import atomic_json

MANIFEST = 'atelierx-presets.json'
KIND = 'atelierx-style-presets'
MAX_ZIP = 64 * 1024**2
MAX_PRESETS = 500
PENDING_SECONDS = 1800


def _resources(preset, index):
    """The files a preset needs: ``[{kind, name, sha256?, civitai?}]``."""
    s = preset.get('settings') or {}
    wanted = []
    if s.get('model'):
        wanted.append(('model', str(s['model']).removeprefix('checkpoint::')))
    for key, kind in (('text_encoder', 'text_encoder'), ('vae', 'vae')):
        if s.get(key):
            wanted.append((kind, s[key]))
    for lora in s.get('loras') or []:
        if lora.get('enabled') is not False and lora.get('name'):
            wanted.append(('lora', lora['name']))
    if isinstance(s.get('upscale'), dict) and s['upscale'].get('model'):
        wanted.append(('upscale_model', s['upscale']['model']))
    known = {}
    for entries in (index or {}).values():
        for entry in entries:
            known.setdefault(PureWindowsPath(entry['name']).name.lower(), entry)
    out = []
    for kind, name in wanted:
        entry = {'kind': kind, 'name': name}
        info = known.get(PureWindowsPath(name).name.lower())
        if info:
            if info.get('sha256'):
                entry['sha256'] = info['sha256']
            if info.get('model_id'):
                entry['civitai'] = (
                    f'https://civitai.com/models/{info["model_id"]}?modelVersionId={info.get("version_id", "")}'
                )
        out.append(entry)
    return out


def export(paths, ids, index=None):
    """``(zip bytes, file name)`` of the chosen presets (all when ``ids`` is empty)."""
    presets = {p['id']: p for p in library.presets(paths)}
    chosen = [presets[i] for i in ids if i in presets] if ids else list(presets.values())
    if not chosen:
        raise ValueError(Msg('server.presets.share.none', 'Choose the style presets to export.'))
    out = io.BytesIO()
    listing = []
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for preset in chosen:
            ident = preset['id']
            doc = library.preset_doc(preset, ident)
            archive.writestr(f'presets/{ident}.json', json.dumps(doc, ensure_ascii=False, indent=2))
            preview = library.preview_file(paths, ident)
            has_preview = bool(doc.get('preview')) and preview.is_file()
            if has_preview:
                archive.write(preview, f'presets/{ident}.webp')
            listing.append(
                {
                    'id': ident,
                    'name': doc['name'],
                    'service': doc['service'],
                    'family': doc['family'],
                    'preview': has_preview,
                    'resources': _resources(doc, index),
                }
            )
        archive.writestr(
            MANIFEST,
            json.dumps(
                {'kind': KIND, 'schema_version': 1, 'app_version': __version__, 'presets': listing},
                ensure_ascii=False,
                indent=2,
            ),
        )
    stamp = time.strftime('%Y%m%d')
    name = f'style-presets-{chosen[0]["id"] if len(chosen) == 1 else len(chosen)}-{stamp}.zip'
    return out.getvalue(), name


def _bad():
    return ValueError(Msg('server.presets.share.bad', 'This file is not an AtelierX style preset package.'))


class PresetImports:
    """Packages read but not applied yet, kept in memory for a while under a token."""

    def __init__(self, paths):
        self.paths = paths
        self.pending = {}

    def preview(self, raw, catalog):
        if len(raw) > MAX_ZIP:
            raise ValueError(Msg('server.presets.share.too_big', 'The package is larger than 64 MB.'))
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
            manifest = json.loads(archive.read(MANIFEST))
        except (zipfile.BadZipFile, KeyError, ValueError) as error:
            raise _bad() from error
        if (
            not isinstance(manifest, dict)
            or manifest.get('kind') != KIND
            or not isinstance(manifest.get('presets'), list)
        ):
            raise _bad()
        here = {p['id'] for p in library.presets(self.paths)}
        have = {
            kind: {
                PureWindowsPath(str(n).removeprefix('checkpoint::')).name.lower()
                for n in catalog.get(key) or []
            }
            for kind, key in (
                ('model', 'models'),
                ('text_encoder', 'text_encoders'),
                ('vae', 'vaes'),
                ('lora', 'loras'),
                ('upscale_model', 'upscale_models'),
            )
        }
        items, docs = [], {}
        for entry in manifest['presets'][:MAX_PRESETS]:
            ident = str((entry or {}).get('id', ''))
            if not library.ITEM_ID.match(ident):
                continue
            try:
                doc = json.loads(archive.read(f'presets/{ident}.json'))
            except (KeyError, ValueError):
                continue
            if not isinstance(doc, dict):
                continue
            preview = None
            try:
                preview = archive.read(f'presets/{ident}.webp')
            except KeyError:
                pass
            docs[ident] = (library.preset_doc(doc, ident), preview, doc.get('preview'))
            missing = []
            if catalog.get('connected') and docs[ident][0]['service'] == 'comfyui':
                for res in entry.get('resources') or []:
                    if PureWindowsPath(str(res.get('name', ''))).name.lower() not in have.get(
                        res.get('kind'), set()
                    ):
                        missing.append(
                            {k: res[k] for k in ('kind', 'name', 'sha256', 'civitai') if res.get(k)}
                        )
            items.append(
                {
                    'id': ident,
                    'name': docs[ident][0]['name'],
                    'service': docs[ident][0]['service'],
                    'family': docs[ident][0]['family'],
                    'exists': ident in here,
                    'preview': preview is not None,
                    'missing': missing,
                }
            )
        if not items:
            raise _bad()
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if now - v['at'] < PENDING_SECONDS}
        token = secrets.token_hex(12)
        self.pending[token] = {'at': now, 'docs': docs}
        return {
            'token': token,
            'app_version': manifest.get('app_version'),
            'items': items,
            'checked': bool(catalog.get('connected')),
        }

    def apply(self, token, choices):
        """``choices``: ``{id: 'add' | 'replace' | 'skip' | {'as': new id}}``. Returns the ids written."""
        pending = self.pending.pop(token, None)
        if pending is None:
            raise ValueError(
                Msg(
                    'server.presets.share.expired',
                    'The package was read too long ago. Choose the file again.',
                )
            )
        here = {p['id'] for p in library.presets(self.paths)}
        written = []
        for ident, (doc, preview, preview_meta) in pending['docs'].items():
            choice = (choices or {}).get(ident, 'add')
            target = ident
            if isinstance(choice, dict):
                target = str(choice.get('as', ''))
                if not library.ITEM_ID.match(target) or target in here:
                    raise ValueError(
                        Msg('server.presets.share.bad_id', 'The id {id} is taken or not usable.', id=target)
                    )
            elif choice == 'skip' or (choice == 'add' and ident in here):
                continue
            elif choice not in ('add', 'replace'):
                raise ValueError(
                    Msg('server.presets.share.bad_choice', 'Choose add, replace or skip for each preset.')
                )
            folder = Path(self.paths.data) / 'image' / 'presets'
            folder.mkdir(parents=True, exist_ok=True)
            # The preview comes along with its record, so it is stale here exactly when it would be there.
            stored = dict(doc)
            if preview and isinstance(preview_meta, dict):
                stored['preview'] = preview_meta
            else:
                stored.pop('preview', None)
            atomic_json(folder / f'{target}.json', library.preset_doc(stored, target))
            preview_path = library.preview_file(self.paths, target)
            if preview:
                preview_path.write_bytes(preview)
            else:
                preview_path.unlink(missing_ok=True)
            here.add(target)
            written.append(target)
        return {'written': written, 'presets': library.presets(self.paths)}
