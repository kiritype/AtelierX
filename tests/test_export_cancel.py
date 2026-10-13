import asyncio
import threading
from types import SimpleNamespace

import pytest

from atelierx.core import exporter
from atelierx.core.events import Events
from atelierx.core.jobs import Jobs
from atelierx.core.work_jobs import WorkJobs


@pytest.mark.parametrize('pause_at', ['first.md', 'second.md', '_keywords.md'])
def test_cancel_waits_for_current_write_and_stops_following_files(tmp_path, monkeypatch, pause_at):
    target = tmp_path / 'output'
    work = SimpleNamespace(
        id='W001',
        name='Synthetic',
        folder=tmp_path / 'work',
        doc=lambda: {'language': 'en'},
        item_paths=lambda: ['first.md', 'second.md'],
        read_item=lambda path: {'path': path, 'body': path, 'kind': 'main', 'meta': {}},
    )
    entered, release = threading.Event(), threading.Event()
    writes = []
    original = exporter.atomic_write_text

    def write(path, content):
        if path.name == pause_at:
            entered.set()
            assert release.wait(5)
        original(path, content)
        writes.append(path.name)

    monkeypatch.setattr(exporter, 'atomic_write_text', write)

    async def scenario():
        jobs = Jobs(Events())
        service = WorkJobs(SimpleNamespace(root=tmp_path / 'app'), None, None, jobs.events, jobs)
        public = service.export(work, {'target': str(target)})
        task = jobs.jobs[public['id']]['_task']
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert jobs.cancel(public['id'])['status'] == 'cancelling'
            await asyncio.sleep(0)
            assert jobs.jobs[public['id']]['status'] == 'cancelling'
            assert not (target / pause_at).exists()
            jobs.cancel(public['id'])
            task.cancel()  # A second cancellation from shutdown must also drain the thread.
            await asyncio.sleep(0)
            assert not task.done()
            assert jobs.jobs[public['id']]['status'] == 'cancelling'
        finally:
            release.set()
        await task
        assert jobs.jobs[public['id']]['status'] == 'cancelled'
        expected = ['first.md', 'second.md', '_keywords.md']
        assert writes == expected[: expected.index(pause_at) + 1]
        assert sorted(p.name for p in target.iterdir()) == sorted(writes)
        before = list(writes)
        assert jobs.cancel(public['id'])['status'] == 'cancelled'
        await asyncio.sleep(0)
        assert writes == before

    asyncio.run(scenario())


def test_cancel_before_export_does_not_create_target(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(exporter.ExportCancelled):
        exporter.export(None, tmp_path / 'output', cancel=cancel)
    assert not (tmp_path / 'output').exists()


def test_job_cancelled_before_runner_starts_reaches_terminal_state():
    async def scenario():
        jobs = Jobs(Events())

        async def runner(_):
            pytest.fail('cancelled queued job must not start writing')

        job = jobs.submit('export', 'Synthetic', runner)
        jobs.cancel(job['id'])
        await asyncio.gather(jobs.jobs[job['id']]['_task'], return_exceptions=True)
        assert jobs.jobs[job['id']]['status'] == 'cancelled'

    asyncio.run(scenario())


def test_cancel_after_last_write_is_done_leaves_successful_result(tmp_path):
    async def scenario():
        work = SimpleNamespace(
            id='W001',
            name='Synthetic',
            folder=tmp_path / 'work',
            doc=lambda: {'language': 'en'},
            item_paths=list,
        )
        jobs = Jobs(Events())
        service = WorkJobs(SimpleNamespace(root=tmp_path / 'app'), None, None, jobs.events, jobs)
        job = service.export(work, {'target': str(tmp_path / 'output')})
        await jobs.jobs[job['id']]['_task']
        result = jobs.cancel(job['id'])
        assert result['status'] == 'done'
        assert result['result']['written'] == ['_keywords.md']
        assert (tmp_path / 'output' / '_keywords.md').is_file()

    asyncio.run(scenario())


def test_event_loop_shutdown_drains_export_writer(tmp_path, monkeypatch):
    entered = threading.Event()
    original = exporter.export
    jobs = Jobs(Events())
    target = tmp_path / 'output'
    work = SimpleNamespace(
        id='W001',
        name='Synthetic',
        folder=tmp_path / 'work',
        doc=lambda: {'language': 'en'},
        item_paths=list,
    )

    def export(work, target, overwrite, root, cancel):
        entered.set()
        assert cancel.wait(5)
        return original(work, target, overwrite, root, cancel)

    monkeypatch.setattr(exporter, 'export', export)

    async def scenario():
        service = WorkJobs(SimpleNamespace(root=tmp_path / 'app'), None, None, jobs.events, jobs)
        service.export(work, {'target': str(target)})
        assert await asyncio.to_thread(entered.wait, 5)
        # asyncio.run cancels every remaining Task as this main coroutine exits.

    asyncio.run(scenario())
    assert next(iter(jobs.jobs.values()))['status'] == 'cancelled'
    assert not target.exists()
