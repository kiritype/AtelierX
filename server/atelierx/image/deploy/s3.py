"""A small S3-compatible client for the deployment upload (decision 0023): list, head and put, signed with AWS
Signature Version 4. Cloudflare R2 is reached at ``https://<account id>.r2.cloudflarestorage.com`` with region ``auto``.
Only what the upload needs; no multipart (the images are small).
"""

import hashlib
import hmac
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx

from ...core.i18n import Msg

EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()
UNSIGNED = 'UNSIGNED-PAYLOAD'
LIST_PAGE = 1000


class S3Error(RuntimeError):
    """A failed request, with a message for the user and the S3 error code when there is one."""

    def __init__(self, msg, code=''):
        super().__init__(msg)
        self.code = code


def _hmac(key, text):
    return hmac.new(key, text.encode('utf-8'), hashlib.sha256).digest()


def signing_key(secret, day, region, service='s3'):
    key = _hmac(('AWS4' + secret).encode('utf-8'), day)
    for part in (region, service, 'aws4_request'):
        key = _hmac(key, part)
    return key


def _encode(text, safe='-_.~'):
    return quote(text, safe=safe)


def sign(method, url, headers, payload_hash, access_key, secret, region, now, service='s3'):
    """Headers to send: the given ones plus host, x-amz-date, x-amz-content-sha256 and Authorization.

    ``url`` is the full URL; its path must already be percent-encoded the way it will be sent.
    """
    parts = urlsplit(url)
    stamp = now.strftime('%Y%m%dT%H%M%SZ')
    day = stamp[:8]
    out = {k.lower(): str(v).strip() for k, v in headers.items()}
    out['host'] = parts.netloc
    out['x-amz-date'] = stamp
    out['x-amz-content-sha256'] = payload_hash
    query = []
    for pair in parts.query.split('&') if parts.query else []:
        name, _, value = pair.partition('=')
        query.append((name, value))
    canonical_query = '&'.join(f'{n}={v}' for n, v in sorted(query))
    names = sorted(out)
    canonical_headers = ''.join(f'{n}:{out[n]}\n' for n in names)
    signed = ';'.join(names)
    canonical = '\n'.join(
        [method, parts.path or '/', canonical_query, canonical_headers, signed, payload_hash]
    )
    scope = f'{day}/{region}/{service}/aws4_request'
    to_sign = '\n'.join(
        ['AWS4-HMAC-SHA256', stamp, scope, hashlib.sha256(canonical.encode('utf-8')).hexdigest()]
    )
    signature = hmac.new(signing_key(secret, day, region, service), to_sign.encode('utf-8'), hashlib.sha256)
    out['authorization'] = (
        f'AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, '
        f'Signature={signature.hexdigest()}'
    )
    return out


def r2_endpoint(account_id):
    return f'https://{account_id}.r2.cloudflarestorage.com'


class S3Client:
    def __init__(self, endpoint, bucket, access_key, secret, region='auto', transport=None, timeout=60.0):
        self.endpoint = endpoint.rstrip('/')
        self.bucket = bucket
        self.access_key = access_key
        self.secret = secret
        self.region = region
        self.transport = transport  # tests answer with httpx.MockTransport
        self.timeout = timeout

    def _url(self, key='', query=''):
        path = f'/{_encode(self.bucket)}'
        if key:
            path += '/' + _encode(key, safe='-_.~/')
        return f'{self.endpoint}{path}' + (f'?{query}' if query else '')

    def _send(self, method, key='', query='', body=b'', headers=None):
        url = self._url(key, query)
        payload = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        signed = sign(
            method, url, headers or {}, payload, self.access_key, self.secret, self.region, datetime.now(UTC)
        )
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.request(method, url, content=body or None, headers=signed)
        except httpx.TimeoutException as error:
            raise S3Error(Msg('server.deploy.timeout', 'The storage did not answer in time.')) from error
        except httpx.HTTPError as error:
            raise S3Error(
                Msg('server.deploy.offline', 'Cannot reach the storage: {error}', error=str(error)[:200])
            ) from error
        if response.status_code >= 400 and not (method == 'HEAD' and response.status_code == 404):
            raise _error(response)
        return response

    def check(self):
        """List one object: proves the address, the bucket, the key and read permission."""
        self._send('GET', query='list-type=2&max-keys=1')
        return True

    def list(self, prefix=''):
        """``{key: etag}`` under a prefix (ETag without quotes; the MD5 for a single PUT)."""
        found = {}
        token = None
        while True:
            query = [('list-type', '2'), ('max-keys', str(LIST_PAGE))]
            if prefix:
                query.append(('prefix', prefix))
            if token:
                query.append(('continuation-token', token))
            response = self._send('GET', query='&'.join(f'{n}={_encode(v)}' for n, v in query))
            root = ET.fromstring(response.content)
            ns = root.tag.split('}')[0] + '}' if root.tag.startswith('{') else ''
            for item in root.iter(f'{ns}Contents'):
                key = item.findtext(f'{ns}Key') or ''
                found[key] = (item.findtext(f'{ns}ETag') or '').strip('"')
            if (root.findtext(f'{ns}IsTruncated') or '').lower() != 'true':
                return found
            token = root.findtext(f'{ns}NextContinuationToken')
            if not token:
                return found

    def head(self, key):
        """The ETag of an object, or None when there is none."""
        response = self._send('HEAD', key)
        return None if response.status_code == 404 else response.headers.get('etag', '').strip('"')

    def put(self, key, body, content_type):
        """Upload (or overwrite) one object; returns its ETag."""
        response = self._send('PUT', key, body=body, headers={'content-type': content_type})
        return response.headers.get('etag', '').strip('"')


def _error(response):
    code, text = '', ''
    try:
        root = ET.fromstring(response.content)
        code = root.findtext('Code') or ''
        text = root.findtext('Message') or ''
    except ET.ParseError:
        pass
    status = response.status_code
    if code == 'RequestTimeTooSkewed':
        msg = Msg(
            'server.deploy.clock',
            "The storage refused the request because this PC's clock is off. Set the clock and retry.",
        )
    elif code in ('SignatureDoesNotMatch', 'InvalidAccessKeyId') or status == 401:
        msg = Msg('server.deploy.bad_key', 'The storage refused the access key. Check the key ID and secret.')
    elif code == 'NoSuchBucket':
        msg = Msg(
            'server.deploy.no_bucket', 'The bucket does not exist. Check the bucket name and account ID.'
        )
    elif status == 403:
        msg = Msg(
            'server.deploy.forbidden',
            'The key has no permission for this bucket. Give it object read and write on the bucket.',
        )
    else:
        msg = Msg(
            'server.deploy.http',
            'The storage answered HTTP {status}: {text}',
            status=status,
            text=(text or code or response.text)[:200],
        )
    return S3Error(msg, code)
