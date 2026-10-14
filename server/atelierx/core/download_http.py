"""HTTPS downloads with origin-scoped credentials across redirects."""

import urllib.error
import urllib.parse
import urllib.request


def origin(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme.lower(), parsed.hostname, 443 if parsed.port is None else parsed.port


class DownloadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if origin(newurl)[0] != 'https':
            raise urllib.error.URLError('Downloads require HTTPS')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and origin(req.full_url) != origin(newurl):
            for header in ('Authorization', 'Cookie', 'Proxy-authorization'):
                redirected.remove_header(header)
        return redirected


def download_open(request, timeout=30):
    if origin(request.full_url)[0] != 'https':
        raise urllib.error.URLError('Downloads require HTTPS')
    return urllib.request.build_opener(DownloadRedirect()).open(request, timeout=timeout)
