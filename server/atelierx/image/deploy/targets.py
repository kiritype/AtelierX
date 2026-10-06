"""Deployment targets (decision 0023, data-model: 배포 대상): where adopted images are uploaded.

Kept app-wide in data/image/deploy.json; a work picks one in .atelierx/image/deploy.json. Keys are never written here,
only ``secret:<vault entry>`` (decision 0011).
"""

import re
from urllib.parse import urlsplit

from ...core.i18n import Msg
from ..util import atomic_json, read_json
from .s3 import S3Client, r2_endpoint

KINDS = ('r2',)
TARGET_ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,39}$')
ACCOUNT_ID = re.compile(r'^[A-Za-z0-9]{1,64}$')
# S3 bucket names: 3-63 lowercase letters, digits, dots and hyphens.
BUCKET = re.compile(r'^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$')
PLACEHOLDERS = ('work', 'character', 'outfit', 'expression')
DEFAULT_FORMAT = '{work}/{character}/{outfit}/{expression}'
FIELD = re.compile(r'\{([^{}]*)\}')
MAX_TARGETS = 20


def check_format(value):
    """A path format: text with {work} {character} {outfit} {expression}, '/' between parts, no other braces."""
    text = (value or '').strip().strip('/')
    if not text:
        return DEFAULT_FORMAT
    names = FIELD.findall(text)
    rest = FIELD.sub('', text)
    if any(n not in PLACEHOLDERS for n in names) or '{' in rest or '}' in rest:
        raise ValueError(
            Msg(
                'server.deploy.format',
                'The path format may use only {work}, {character}, {outfit} and {expression}.',
            )
        )
    if '//' in text or '\\' in text or any(part in ('.', '..') for part in text.split('/')):
        raise ValueError(Msg('server.deploy.format_path', 'The path format has an empty or invalid folder.'))
    return text


def _reference(value):
    return isinstance(value, str) and value.startswith('secret:') and len(value) > len('secret:')


class DeployTargets:
    def __init__(self, paths, vault):
        self.file = paths.data / 'image' / 'deploy.json'
        self.vault = vault

    def doc(self):
        raw = read_json(self.file, {}) or {}
        targets = {}
        for ident, entry in (raw.get('targets') or {}).items():
            if TARGET_ID.match(str(ident)) and isinstance(entry, dict):
                try:
                    targets[ident] = self._clean(entry, strict=False)
                except ValueError:
                    continue
        return {'schema_version': 1, 'targets': targets}

    def _clean(self, entry, strict=True):
        def bad(msg):
            raise ValueError(msg)

        name = str(entry.get('name') or '').strip()[:80]
        kind = entry.get('kind') or 'r2'
        if kind not in KINDS:
            bad(Msg('server.deploy.kind', 'Unknown kind of deployment target: {kind}', kind=kind))
        account = str(entry.get('account_id') or '').strip()
        if strict and not ACCOUNT_ID.match(account):
            bad(Msg('server.deploy.account', 'Enter the Cloudflare account ID (letters and digits).'))
        bucket = str(entry.get('bucket') or '').strip()
        if strict and not BUCKET.match(bucket):
            bad(
                Msg(
                    'server.deploy.bucket',
                    'Enter the bucket name: 3 to 63 lowercase letters, digits, dots and hyphens.',
                )
            )
        keys = {}
        for field in ('access_key_id', 'secret_access_key'):
            value = entry.get(field) or None
            if value is not None and not _reference(value):
                bad(
                    Msg(
                        'server.llm.secret_reference',
                        'Save credentials in Settings and select the saved entry.',
                    )
                )
            keys[field] = value
        public = str(entry.get('public_url') or '').strip().rstrip('/')
        if public:
            parts = urlsplit(public)
            if parts.scheme not in ('http', 'https') or not parts.netloc or parts.query or parts.fragment:
                bad(
                    Msg(
                        'server.deploy.public_url',
                        'Enter the public URL as https://host (and a folder if any).',
                    )
                )
        return {
            'name': name or bucket,
            'kind': kind,
            'account_id': account,
            'bucket': bucket,
            **keys,
            'public_url': public,
            'path_format': check_format(entry.get('path_format')),
        }

    def save(self, doc):
        targets = (doc or {}).get('targets') if isinstance(doc, dict) else None
        if not isinstance(targets, dict) or len(targets) > MAX_TARGETS:
            raise ValueError(Msg('server.deploy.invalid', 'Deployment targets are required.'))
        out = {}
        for ident, entry in targets.items():
            if not TARGET_ID.match(str(ident)) or not isinstance(entry, dict):
                raise ValueError(
                    Msg(
                        'server.deploy.target_id',
                        'Use lowercase letters, digits, "_" and "-" for the target ID.',
                    )
                )
            out[ident] = self._clean(entry)
        result = {'schema_version': 1, 'targets': out}
        atomic_json(self.file, result)
        return self.public()

    def public(self):
        """What the settings screen shows: each target with whether both keys are in the (unlocked) vault."""
        listed = []
        for ident, entry in self.doc()['targets'].items():
            listed.append({'id': ident, **entry, 'ready': self._keys(entry) is not None})
        return {'targets': listed, 'placeholders': list(PLACEHOLDERS), 'default_format': DEFAULT_FORMAT}

    def _keys(self, entry):
        try:
            found = [
                self.vault.reveal(entry[f][len('secret:') :]) for f in ('access_key_id', 'secret_access_key')
            ]
        except Exception:  # no reference, a locked vault or a removed entry: not usable
            return None
        return tuple(found) if all(found) else None

    def get(self, ident):
        entry = self.doc()['targets'].get(ident)
        if entry is None:
            raise ValueError(Msg('server.deploy.unknown', 'Unknown deployment target: {id}', id=ident))
        return entry

    def client(self, ident, transport=None):
        entry = self.get(ident)
        keys = self._keys(entry)
        if keys is None:
            raise ValueError(
                Msg(
                    'server.deploy.no_keys',
                    'Register the access key ID and secret of "{name}" first.',
                    name=entry['name'],
                )
            )
        return S3Client(r2_endpoint(entry['account_id']), entry['bucket'], *keys, transport=transport)

    def check(self, ident, transport=None):
        self.client(ident, transport).check()
        return {'ok': True}


def work_file(work):
    return work.app / 'image' / 'deploy.json'


def work_settings(work):
    raw = read_json(work_file(work), {}) or {}
    target = raw.get('target') if isinstance(raw.get('target'), str) else None
    path_format = raw.get('path_format')
    try:
        path_format = check_format(path_format) if path_format else None
    except ValueError:
        path_format = None
    return {'schema_version': 1, 'target': target, 'path_format': path_format}


def save_work_settings(work, body):
    body = body if isinstance(body, dict) else {}
    target = body.get('target') or None
    if target is not None and not TARGET_ID.match(str(target)):
        raise ValueError(Msg('server.deploy.unknown', 'Unknown deployment target: {id}', id=target))
    path_format = body.get('path_format') or None
    out = {
        'schema_version': 1,
        'target': target,
        'path_format': check_format(path_format) if path_format else None,
    }
    atomic_json(work_file(work), out)
    return out
