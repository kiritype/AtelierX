import asyncio

import httpx
import pytest

from atelierx import __version__
from atelierx.core import about
from atelierx.core.fsutil import write_json
from atelierx.core.i18n import AppError, Msg
from atelierx.core.update_notice import DAY_MS, RETRIES, UpdateNotices


def test_retry_budget_persists_and_success_does_not_schedule_periodic_checks(paths, monkeypatch):
    async def scenario():
        now = [1_000_000]
        calls = []

        async def fail():
            calls.append(now[0])
            e = AppError(Msg('offline', 'offline'))
            e.retryable = True
            raise e

        monkeypatch.setattr(about, 'check_update', fail)
        n = UpdateNotices(paths)
        n.clock = lambda: now[0]
        with pytest.raises(AppError):
            await n.check(startup=True)
        for i, delay in enumerate(RETRIES):
            now[0] += delay - 1
            assert await n.check(startup=True) is None
            now[0] += 1
            n = UpdateNotices(paths)
            n.clock = lambda: now[0]
            with pytest.raises(AppError):
                await n.check(startup=True)
            assert n.status()['retries'] == i + 1
        assert len(calls) == 4
        assert await n.check(startup=True) is None
        now[0] += DAY_MS
        assert await n.check() is None  # no new cycle until a new startup

        async def success():
            return {'current': __version__, 'latest': '9.9.9', 'newer': True}

        monkeypatch.setattr(about, 'check_update', success)
        await n.check(startup=True)
        assert n.status()['next_retry'] is None
        now[0] += DAY_MS
        assert await n.check() is None

    asyncio.run(scenario())


def test_manual_and_automatic_requests_coalesce_and_old_checked_at_is_not_success(paths, monkeypatch):
    async def scenario():
        n = UpdateNotices(paths)
        write_json(n.path, {'checked_at': n.clock(), 'checked_version': __version__})
        release = asyncio.Event()
        calls = []

        async def success():
            calls.append(1)
            await release.wait()
            return {'current': __version__, 'latest': '9.9.9', 'newer': True}

        monkeypatch.setattr(about, 'check_update', success)
        a = asyncio.create_task(n.check(startup=True))
        await asyncio.sleep(0)
        b = asyncio.create_task(n.check(manual=True))
        await asyncio.sleep(0)
        release.set()
        assert await a == await b
        assert len(calls) == 1
        assert n.status()['last_success']

    asyncio.run(scenario())


def test_rate_limit_is_honored_by_manual_checks_and_failure_keeps_last_release(paths, monkeypatch):
    async def scenario():
        n = UpdateNotices(paths)
        n.clock = lambda: 1000
        n.record({'current': __version__, 'latest': '9.9.9', 'newer': True}, 500)

        async def limited():
            e = AppError(Msg('limited', 'limited'))
            e.retryable, e.retry_at = True, 9_000_000
            raise e

        monkeypatch.setattr(about, 'check_update', limited)
        with pytest.raises(AppError):
            await n.check(manual=True)
        state = n.status(True)
        assert state['last_success'] == 500 and state['available_version'] == '9.9.9'
        assert state['next_retry'] == 9_000_000
        with pytest.raises(AppError) as error:
            await n.check(manual=True)
        assert error.value.status == 429
        assert n.status(False)['next_retry'] is None

    asyncio.run(scenario())


def test_http_rate_limit_and_invalid_release(monkeypatch):
    original = httpx.AsyncClient

    def client(**kwargs):
        return original(
            transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={'Retry-After': '120'})),
            **kwargs,
        )

    monkeypatch.setattr(about.httpx, 'AsyncClient', client)
    with pytest.raises(AppError) as error:
        asyncio.run(about.check_update())
    assert error.value.retryable and error.value.retry_at > 0
