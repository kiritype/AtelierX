import urllib.error
import urllib.request

import pytest

from atelierx.core.download_http import DownloadRedirect, download_open
from atelierx.image.model_download import ModelDownloads


@pytest.mark.parametrize(
    'destination,kept',
    [
        ('https://civitai.com/next', True),
        ('https://civitai.com:443/next', True),
        ('https://cdn.example.invalid/file', False),
        ('https://civitai.com:444/file', False),
    ],
)
def test_redirect_scopes_credentials_and_preserves_range(destination, kept):
    request = urllib.request.Request(
        'https://civitai.com/start',
        headers={
            'Authorization': 'Bearer dummy',
            'Cookie': 'dummy=1',
            'Range': 'bytes=4-',
        },
    )
    result = DownloadRedirect().redirect_request(request, None, 302, 'Found', {}, destination)
    assert bool(result.get_header('Authorization')) == kept
    assert bool(result.get_header('Cookie')) == kept
    assert result.get_header('Range') == 'bytes=4-'


def test_plain_http_is_rejected_without_network():
    request = urllib.request.Request('https://civitai.com/start')
    with pytest.raises(urllib.error.URLError):
        DownloadRedirect().redirect_request(
            request, None, 302, 'Found', {}, 'http://cdn.example.invalid/file'
        )
    with pytest.raises(urllib.error.URLError):
        download_open(urllib.request.Request('http://civitai.com/file'))


def test_initial_credentials_require_exact_origin():
    downloads = object.__new__(ModelDownloads)
    downloads.key = lambda: 'dummy'
    assert downloads._request('https://civitai.com/file').get_header('Authorization')
    for url in (
        'https://civitai.com.external.invalid/file',
        'http://civitai.com/file',
        'https://civitai.com:444/file',
    ):
        assert not downloads._request(url).get_header('Authorization')
