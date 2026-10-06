"""The S3 client of the deployment upload: SigV4 against AWS's published examples, and requests to a fake bucket."""

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from atelierx.image.deploy import s3

# AWS's published example key, split so the public-file audit does not take it for a real one.
AWS_KEY_TYPE = 'AKIA'
AWS_KEY = AWS_KEY_TYPE + 'IOSFODNN7EXAMPLE'
AWS_SECRET = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
AWS_NOW = datetime(2013, 5, 24, tzinfo=UTC)


def _signature(headers):
    return re.search(r'Signature=([0-9a-f]+)', headers['authorization']).group(1)


def test_signatures_match_the_aws_examples():
    # "GET Object" and "GET Bucket (List Objects)" from the AWS Signature Version 4 documentation.
    got = s3.sign(
        'GET',
        'https://examplebucket.s3.amazonaws.com/test.txt',
        {'Range': 'bytes=0-9'},
        s3.EMPTY_SHA256,
        AWS_KEY,
        AWS_SECRET,
        'us-east-1',
        AWS_NOW,
    )
    assert 'SignedHeaders=host;range;x-amz-content-sha256;x-amz-date' in got['authorization']
    assert _signature(got) == 'f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41'
    listed = s3.sign(
        'GET',
        'https://examplebucket.s3.amazonaws.com/?prefix=J&max-keys=2',
        {},
        s3.EMPTY_SHA256,
        AWS_KEY,
        AWS_SECRET,
        'us-east-1',
        AWS_NOW,
    )
    assert _signature(listed) == '34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7'


class FakeBucket:
    """An in-memory bucket answering list, head and put like S3 (path-style URLs)."""

    def __init__(self, bucket='images', fail=None):
        self.bucket = bucket
        self.objects = {}
        self.fail = fail
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers['authorization'].startswith('AWS4-HMAC-SHA256 Credential=key-id/')
        if self.fail:
            return httpx.Response(
                self.fail[0], content=f'<Error><Code>{self.fail[1]}</Code></Error>'.encode()
            )
        parts = urlsplit(str(request.url))
        path = unquote(parts.path)
        assert path.startswith(f'/{self.bucket}')
        key = path[len(self.bucket) + 2 :]
        if request.method == 'PUT':
            body = request.content
            assert request.headers['x-amz-content-sha256'] == hashlib.sha256(body).hexdigest()
            etag = hashlib.md5(body).hexdigest()
            self.objects[key] = (body, etag)
            return httpx.Response(200, headers={'ETag': f'"{etag}"'})
        if request.method == 'HEAD':
            if key not in self.objects:
                return httpx.Response(404)
            return httpx.Response(200, headers={'ETag': f'"{self.objects[key][1]}"'})
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        names = sorted(k for k in self.objects if k.startswith(query.get('prefix', '')))
        start = int(query.get('continuation-token', '0'))
        page = names[start : start + int(query.get('max-keys', '1000'))]
        more = start + len(page) < len(names)
        contents = ''.join(
            f'<Contents><Key>{k}</Key><ETag>"{self.objects[k][1]}"</ETag></Contents>' for k in page
        )
        token = f'<NextContinuationToken>{start + len(page)}</NextContinuationToken>' if more else ''
        xml = (
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f'{contents}<IsTruncated>{str(more).lower()}</IsTruncated>{token}</ListBucketResult>'
        )
        return httpx.Response(200, content=xml.encode())


def _client(bucket):
    return s3.S3Client(
        s3.r2_endpoint('acct'), bucket.bucket, 'key-id', 'secret', transport=httpx.MockTransport(bucket)
    )


def test_put_head_and_list_against_a_fake_bucket(monkeypatch):
    bucket = FakeBucket()
    client = _client(bucket)
    assert client.check() is True
    etag = client.put('W001/C001/o 1/002.webp', b'webp bytes', 'image/webp')
    assert etag == hashlib.md5(b'webp bytes').hexdigest()
    assert bucket.requests[-1].headers['content-type'] == 'image/webp'
    assert '/images/W001/C001/o%201/002.webp' in str(bucket.requests[-1].url)
    assert client.head('W001/C001/o 1/002.webp') == etag
    assert client.head('nothing.webp') is None
    monkeypatch.setattr(s3, 'LIST_PAGE', 2)
    for n in range(5):
        client.put(f'W001/x{n}.webp', bytes([n]), 'image/webp')
    listed = client.list('W001/x')
    assert sorted(listed) == [f'W001/x{n}.webp' for n in range(5)]
    assert listed['W001/x0.webp'] == hashlib.md5(b'\x00').hexdigest()


@pytest.mark.parametrize(
    ('status', 'code', 'text'),
    [
        (403, 'SignatureDoesNotMatch', 'refused the access key'),
        (403, 'AccessDenied', 'no permission'),
        (404, 'NoSuchBucket', 'bucket does not exist'),
        (403, 'RequestTimeTooSkewed', 'clock'),
        (500, 'InternalError', 'HTTP 500'),
    ],
)
def test_storage_errors_say_what_to_fix(status, code, text):
    with pytest.raises(s3.S3Error, match=text) as caught:
        _client(FakeBucket(fail=(status, code))).check()
    assert caught.value.code == code


def test_an_unreachable_storage_is_reported():
    def refuse(request):
        raise httpx.ConnectError('refused')

    client = s3.S3Client(s3.r2_endpoint('acct'), 'images', 'k', 's', transport=httpx.MockTransport(refuse))
    with pytest.raises(s3.S3Error, match='Cannot reach the storage'):
        client.check()
