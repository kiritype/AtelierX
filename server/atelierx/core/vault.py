"""Master-password vault (decision 0011): scrypt -> KEK wraps a random DEK; the DEK encrypts the secrets."""

import base64
import hashlib
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .fsutil import read_json, write_json
from .i18n import AppError, Msg

KDF = {'name': 'scrypt', 'n': 2**17, 'r': 8, 'p': 1}
# New master passwords (#82); an older shorter one still unlocks, and the app suggests changing it.
MIN_PASSWORD = 8


def _b64(data):
    return base64.b64encode(data).decode('ascii')


def _unb64(text):
    return base64.b64decode(text)


def _kek(password, kdf, salt):
    return hashlib.scrypt(
        password.encode('utf-8'),
        salt=salt,
        n=kdf['n'],
        r=kdf['r'],
        p=kdf['p'],
        maxmem=256 * 1024 * 1024,
        dklen=32,
    )


def _seal(key, data):
    nonce = os.urandom(12)
    return {
        'cipher': 'AES-256-GCM',
        'nonce': _b64(nonce),
        'data': _b64(AESGCM(key).encrypt(nonce, data, None)),
    }


def _open(key, box):
    return AESGCM(key).decrypt(_unb64(box['nonce']), _unb64(box['data']), None)


def _check_password(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AppError(
            Msg(
                'server.vault.password_too_short',
                'Use at least {n} characters for the password.',
                n=MIN_PASSWORD,
            )
        )


def _mask(value):
    if len(value) <= 8:
        return '…' if value else ''
    return f'{value[:3]}…{value[-4:]}'


class Vault:
    """Holds the decrypted secrets in memory only while unlocked."""

    def __init__(self, path, kdf=None):
        self.path = path
        self.kdf = kdf or KDF
        self._dek = None
        self._secrets = None

    @property
    def initialized(self):
        return self.path.is_file()

    @property
    def unlocked(self):
        return self._dek is not None

    def setup(self, password):
        if self.initialized:
            raise AppError(Msg('server.vault.already_set_up', 'The vault is already set up.'), 409)
        _check_password(password)
        self._dek, self._secrets = os.urandom(32), {}
        self._write(password)

    def unlock(self, password):
        doc = read_json(self.path)
        kdf = doc['kdf']
        try:
            dek = _open(_kek(password, kdf, _unb64(kdf['salt'])), doc['wrapped_key'])
            secrets = json.loads(_open(dek, doc['secrets']))
        except InvalidTag:
            raise AppError(Msg('server.vault.wrong_password', 'The password is not correct.'), 401) from None
        self._dek, self._secrets = dek, secrets

    def lock(self):
        self._dek = self._secrets = None

    def change_password(self, old, new):
        self.unlock(old)
        _check_password(new)
        self._write(new)

    def reset(self, password):
        _check_password(password)
        self.path.unlink(missing_ok=True)
        self.lock()
        self.setup(password)

    def list(self):
        self._require()
        return [
            {
                'name': name,
                'kind': item.get('kind', 'other'),
                'note': item.get('note', ''),
                'masked': _mask(item.get('value', '')),
            }
            for name, item in sorted(self._secrets.items())
        ]

    def put(self, name, kind, value, note=''):
        self._require()
        self._secrets[name] = {'kind': kind, 'value': value, 'note': note}
        self._save()

    def delete(self, name):
        self._require()
        self._secrets.pop(name, None)
        self._save()

    def reveal(self, name):
        self._require()
        return self._secrets.get(name, {}).get('value')

    def _require(self):
        if not self.unlocked:
            raise AppError(Msg('server.vault.locked', 'The app is locked.'), 401)

    def _write(self, password):
        salt = os.urandom(16)
        kdf = {**self.kdf, 'salt': _b64(salt)}
        doc = {
            'schema_version': 1,
            'kdf': kdf,
            'wrapped_key': _seal(_kek(password, kdf, salt), self._dek),
            'secrets': _seal(self._dek, b'{}'),
        }
        write_json(self.path, doc)
        self._save()

    def _save(self):
        doc = read_json(self.path)
        doc['secrets'] = _seal(self._dek, json.dumps(self._secrets, ensure_ascii=False).encode('utf-8'))
        write_json(self.path, doc)
