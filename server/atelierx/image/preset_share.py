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
# What a package may hold once unpacked: a small list, small preset files, previews of at most 16 MB, 256 MB in all.
MAX_MANIFEST = 2 * 1024**2
MAX_PRESET_FILE = 1024**2
MAX_PREVIEW = 16 * 1024**2
MAX_UNPACKED = 256 * 1024**2
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


def _read(archive, name, limit, budget):
    """One member, refused when it unpacks to more than ``limit`` or past the package's remaining ``budget``
    (a list of one int). The size the ZIP claims is not trusted: reading stops one byte past the limit."""
    info = archive.getinfo(name)
    if info.file_size > limit or info.file_size > budget[0]:
        raise ValueError(
            Msg(
                'server.presets.share.too_big_inside', 'A file in the package is too large: {name}', name=name
            )
        )
    with archive.open(info) as member:
        data = member.read(min(limit, budget[0]) + 1)
    if len(data) > min(limit, budget[0]):
        raise ValueError(
            Msg(
                'server.presets.share.too_big_inside', 'A file in the package is too large: {name}', name=name
            )
        )
    budget[0] -= len(data)
    return data


def _key(ident):
    # Preset ids are file names, and Windows file names ignore case: "Ink" and "ink" are the same preset.
    return ident.casefold()


class PresetImports:
    """Packages read but not applied yet, kept in memory for a while under a token."""

    def __init__(self, paths):
        self.paths = paths
        self.pending = {}

    def preview(self, raw, catalog):
        if len(raw) > MAX_ZIP:
            raise ValueError(Msg('server.presets.share.too_big', 'The package is larger than 64 MB.'))
        budget = [MAX_UNPACKED]
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
            manifest = json.loads(_read(archive, MANIFEST, MAX_MANIFEST, budget))
        except (zipfile.BadZipFile, KeyError) as error:
            raise _bad() from error
        except ValueError as error:
            if error.args and getattr(error.args[0], 'key', '') == 'server.presets.share.too_big_inside':
                raise
            raise _bad() from error
        if (
            not isinstance(manifest, dict)
            or manifest.get('kind') != KIND
            or not isinstance(manifest.get('presets'), list)
        ):
            raise _bad()
        here = {_key(p['id']) for p in library.presets(self.paths)}
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
            if not library.ITEM_ID.match(ident) or any(_key(ident) == _key(seen) for seen in docs):
                continue
            try:
                doc = json.loads(_read(archive, f'presets/{ident}.json', MAX_PRESET_FILE, budget))
            except KeyError:
                continue
            except ValueError as error:
                if error.args and getattr(error.args[0], 'key', '') == 'server.presets.share.too_big_inside':
                    raise
                continue
            if not isinstance(doc, dict):
                continue
            preview = None
            try:
                preview = _read(archive, f'presets/{ident}.webp', MAX_PREVIEW, budget)
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
                    'exists': _key(ident) in here,
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
        pending = self.pending.get(token)
        if pending is None:
            raise ValueError(
                Msg(
                    'server.presets.share.expired',
                    'The package was read too long ago. Choose the file again.',
                )
            )
        # Everything is checked before anything is written; on a refusal the package stays for another try.
        stored_ids = {_key(p['id']): p['id'] for p in library.presets(self.paths)}
        plan, claimed = [], set()
        for ident, (doc, preview, preview_meta) in pending['docs'].items():
            choice = (choices or {}).get(ident, 'add')
            target = ident
            if isinstance(choice, dict):
                target = str(choice.get('as', ''))
                if not library.ITEM_ID.match(target) or _key(target) in stored_ids or _key(target) in claimed:
                    raise ValueError(
                        Msg('server.presets.share.bad_id', 'The id {id} is taken or not usable.', id=target)
                    )
            elif choice == 'skip' or (choice == 'add' and _key(ident) in stored_ids):
                continue
            elif choice == 'replace':
                # Replace the preset that is here under its own spelling of the id.
                target = stored_ids.get(_key(ident), ident)
            elif choice != 'add':
                raise ValueError(
                    Msg('server.presets.share.bad_choice', 'Choose add, replace or skip for each preset.')
                )
            if _key(target) in claimed:
                raise ValueError(
                    Msg('server.presets.share.bad_id', 'The id {id} is taken or not usable.', id=target)
                )
            claimed.add(_key(target))
            plan.append((target, doc, preview, preview_meta))
        self.pending.pop(token, None)
        written = []
        for target, doc, preview, preview_meta in plan:
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
            written.append(target)
        return {'written': written, 'presets': library.presets(self.paths)}
