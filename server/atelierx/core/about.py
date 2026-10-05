"""Version information and the update check (Help menu).

The packaged app has ``BUILD-MANIFEST.json`` (version, build time, commit) and ``THIRD_PARTY_NOTICES.md`` beside the
executable; a development run has neither. The update check asks GitHub for the latest release (prereleases are not
"latest") only when the user asks, or at start when the setting is on. Nothing is downloaded or installed.
"""

import re

import httpx

from .. import __version__
from .fsutil import read_json
from .i18n import AppError, Msg

REPO = 'kiritype/AtelierX'
LINKS = {
    'repository': f'https://github.com/{REPO}',
    'manual': 'https://atelierx.cftm.net/',
    'releases': f'https://github.com/{REPO}/releases',
}
COPYRIGHT = '© 2026 kiritype'
LATEST_URL = f'https://api.github.com/repos/{REPO}/releases/latest'
NOTES_LIMIT = 6000


def info(paths):
    manifest = read_json(paths.root / 'BUILD-MANIFEST.json') or {}
    return {
        'version': __version__,
        'packaged': bool(manifest),
        'built_at': manifest.get('built_at'),
        'commit': manifest.get('commit'),
        'copyright': COPYRIGHT,
        'license': 'MIT',
        'links': LINKS,
        'notices': (paths.root / 'THIRD_PARTY_NOTICES.md').is_file(),
        'offline_manual': (paths.root / 'manual' / 'index.html').is_file(),
    }


def notices(paths):
    path = paths.root / 'THIRD_PARTY_NOTICES.md'
    if not path.is_file():
        raise AppError(Msg('server.about.no_notices', 'The license notices come with the packaged app.'), 404)
    return path.read_text(encoding='utf-8')


def version_key(text):
    """(major, minor, patch) of ``v0.0.2`` or ``0.0.2``; None for anything else (prereleases included)."""
    found = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(text or '').strip())
    return tuple(int(n) for n in found.groups()) if found else None


async def check_update(current=__version__, url=LATEST_URL):
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={'Accept': 'application/vnd.github+json', 'User-Agent': f'AtelierX/{current}'},
            )
    except httpx.HTTPError as exc:
        raise AppError(
            Msg('server.about.update_unreachable', 'Could not reach GitHub to check for updates.'), 502
        ) from exc
    if response.status_code != 200:
        raise AppError(
            Msg(
                'server.about.update_failed',
                'The update check failed (HTTP {status}).',
                status=response.status_code,
            ),
            502,
        )
    data = response.json()
    latest = data.get('tag_name') or ''
    newer = (version_key(latest) or (0, 0, 0)) > (version_key(current) or (0, 0, 0))
    return {
        'current': current,
        'latest': latest,
        'newer': newer,
        'url': data.get('html_url') or LINKS['releases'],
        'published_at': data.get('published_at'),
        'notes': (data.get('body') or '')[:NOTES_LIMIT],
    }
