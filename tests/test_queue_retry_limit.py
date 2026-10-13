"""Retries share the queue limit with normal submissions (#228)."""

import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, RLock

import pytest

from atelierx.image.job_queue import MAX_QUEUED, JobQueue


def queue_at(tmp_path, waiting):
    queue = JobQueue(tmp_path / 'queue.json', RLock())
    queue.jobs = [{'id': str(i), 'status': 'queued'} for i in range(waiting)]
    queue.jobs.append({'id': 'failed', 'status': 'failed', 'snapshot': {'prompt': 'test'}})
    queue.persist()
    return queue


def test_retry_uses_the_last_slot_and_survives_reload(tmp_path):
    queue = queue_at(tmp_path, MAX_QUEUED - 1)
    attached = []
    retried = queue.retry('failed', attach=lambda old, new: attached.append(new['id']))
    assert queue.queued_count() == MAX_QUEUED
    assert attached == [retried['id']]
    assert retried['snapshot'] == {'prompt': 'test'}
    assert retried['snapshot'] is not queue.get('failed')['snapshot']
    queue.load()
    assert queue.queued_count() == MAX_QUEUED


def test_full_queue_refuses_retry_before_attach_or_persistence(tmp_path):
    queue = queue_at(tmp_path, MAX_QUEUED)
    before = copy.deepcopy(queue.jobs)
    saved = queue.path.read_bytes()
    attached = []
    with pytest.raises(ValueError) as error:
        queue.retry('failed', attach=lambda old, new: attached.append(new))
    assert error.value.args[0].key == 'server.queue.too_many'
    assert queue.jobs == before
    assert queue.path.read_bytes() == saved
    assert attached == []


def test_concurrent_add_and_retry_cannot_both_take_the_last_slot(tmp_path):
    queue = queue_at(tmp_path, MAX_QUEUED - 1)
    start = Barrier(2)
    attached = []

    def submit(retry):
        start.wait(timeout=5)
        try:
            if retry:
                queue.retry('failed', attach=lambda old, new: attached.append(new['id']))
            else:
                queue.add([{'id': 'new', 'status': 'queued'}])
            return 'accepted'
        except ValueError as error:
            return error.args[0].key

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [False, True]))
    assert sorted(results) == ['accepted', 'server.queue.too_many']
    assert queue.queued_count() == MAX_QUEUED
    assert bool(attached) == (results[1] == 'accepted')
    queue.load()
    assert queue.queued_count() == MAX_QUEUED
