"""The image job queue (20-generation, #86): jobs in order, the pause switch and the lock that guards both.

Everything that adds, finds or changes jobs goes through this object: generation, the lab, tools, review rounds,
LoRA training and the completeness board. It knows nothing about how a job is run; the worker and the generation
services do that. The queue survives restarts in state/image/queue.json.
"""

import copy
import uuid
from contextlib import contextmanager

from ..core.i18n import Msg
from ..core.lifecycle import ACTIVE, FINISHED, RETRYABLE, normalize
from .util import atomic_json, now, read_json

FINISHED_SHOWN = 1000
MAX_QUEUED = 5000
# What a retried job keeps from the one it replaces: the request, never the outcome.
RETRY_KEYS = (
    'work_id',
    'service',
    'character_id',
    'outfit_id',
    'expression_id',
    'expression_name',
    'outfit_name',
    'rating',
    'seed',
    'snapshot',
    'kind',
    'title',
    'lab_group',
    'lab_index',
    'lab_row',
    'lab_column',
    'lab_variant',
    'lab_sweep',
    'lab_source',
    'review_requested',
    'tool_item',
    'tag_settings',
    'post_op',
    'post_method',
    'post_options',
    'post_prefix',
    'post_source',
    'post_mask',
    'batch_id',
    'resume',
)


class JobQueue:
    def __init__(self, path, lock):
        self.path = path
        # Shared with the GPU broker and the review rounds, which take it first when they need both.
        self.lock = lock
        self.jobs = []
        self.paused = False

    # --- persistence -------------------------------------------------------------------------------------------------
    def load(self):
        saved = read_json(self.path, {}) or {}
        with self.lock:
            self.jobs = saved.get('jobs') or []
            self.paused = bool(saved.get('paused'))
            for job in self.jobs:
                normalize(job)  # names from before #89 ('completed')
                # Work cut off by a restart cannot be resumed; it is marked so it can be retried.
                if job['status'] in ACTIVE:
                    job.update(status='interrupted', progress=Msg('server.worker.interrupted', 'Interrupted'))

    def persist(self):
        with self.lock:
            atomic_json(self.path, {'schema_version': 1, 'paused': self.paused, 'jobs': self.jobs})

    @contextmanager
    def editing(self):
        """Change several jobs at once under the lock; the queue is saved when the block ends."""
        with self.lock:
            yield self.jobs
            self.persist()

    # --- reading -----------------------------------------------------------------------------------------------------
    def get(self, job_id):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == job_id), None)
        if job is None:
            raise ValueError(Msg('server.queue.job_not_found', 'Job not found.'))
        return job

    def by_id(self):
        with self.lock:
            return {j['id']: j for j in self.jobs}

    def select(self, test):
        with self.lock:
            return [j for j in self.jobs if test(j)]

    def queued_count(self):
        with self.lock:
            return sum(j['status'] == 'queued' for j in self.jobs)

    def any_queued(self):
        with self.lock:
            return any(j['status'] == 'queued' for j in self.jobs)

    def any_active(self, test=None):
        """A job (of those ``test`` accepts) is on its way through a service."""
        with self.lock:
            return any(j['status'] in ACTIVE and (test is None or test(j)) for j in self.jobs)

    def public(self, gpu_status):
        with self.lock:
            finished = [i for i, j in enumerate(self.jobs) if j['status'] in FINISHED]
            hidden = set(finished[:-FINISHED_SHOWN])
            return {
                'paused': self.paused,
                'gpu': gpu_status,
                'jobs': [
                    {k: v for k, v in j.items() if k not in ('snapshot', 'workflow')}
                    for i, j in enumerate(self.jobs)
                    if i not in hidden
                ],
            }

    # --- changing ----------------------------------------------------------------------------------------------------
    def check_room(self, adding):
        """Refuse ``adding`` more jobs when the queue would pass its limit. The whole queue is written on every
        change, so it stays small enough to save quickly (#209: 5,000 jobs are about 30 MB and 0.7 s a save; 20,000
        would be 120 MB and 2.7 s)."""
        with self.lock:
            waiting = self.queued_count()
            if waiting + adding > MAX_QUEUED:
                raise ValueError(
                    Msg(
                        'server.queue.too_many',
                        '{waiting} jobs are waiting; {adding} more would pass the limit of {limit}. '
                        'Let the queue run first, or queue fewer.',
                        waiting=f'{waiting:,}',
                        adding=f'{adding:,}',
                        limit=f'{MAX_QUEUED:,}',
                    )
                )

    def add(self, prepared, before_save=None):
        """Append new jobs, refusing when too many would wait. ``before_save`` sees them first (under the lock)."""
        with self.lock:
            # Checked again under the same lock: another request may have queued jobs since the early check.
            self.check_room(len(prepared))
            self.jobs.extend(prepared)
            if before_save:
                before_save(prepared)
            self.persist()

    def update(self, job, **fields):
        with self.lock:
            job.update(fields)
            self.persist()

    def status_of(self, job):
        with self.lock:
            return job['status']

    def take_next(self, pick, **fields):
        """Mark the job ``pick`` chooses from the queued ones as taken (``fields``) and return it, or None."""
        with self.lock:
            job = pick(self.jobs)
            if job is not None:
                job.update(fields)
                self.persist()
            return job

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job['status'] == 'queued':
                job['status'] = 'cancelled'
            elif job['status'] == 'running':
                job['status'] = 'cancelling'
            self.persist()

    def cancel_waiting(self, job_ids):
        """Cancel those of ``job_ids`` that have not started. Returns how many."""
        with self.lock:
            count = 0
            for job in self.jobs:
                if job['id'] in job_ids and job['status'] == 'queued':
                    job['status'] = 'cancelled'
                    count += 1
            if count:
                self.persist()
            return count

    def cancel_queued(self):
        """Cancel every waiting job; the running one still finishes."""
        with self.lock:
            for job in self.jobs:
                if job['status'] == 'queued':
                    job['status'] = 'cancelled'
            self.persist()

    def retry(self, job_id, attach=None):
        """A new queued job with the request of a failed, cancelled or interrupted one."""
        with self.lock:
            old = self.get(job_id)
            if old['status'] not in RETRYABLE:
                raise ValueError(
                    Msg(
                        'server.queue.only_failed_cancelled_or_interrupted_jobs',
                        'Only failed, cancelled or interrupted jobs can be retried.',
                    )
                )
            job = {k: copy.deepcopy(v) for k, v in old.items() if k in RETRY_KEYS}
            job.update(id=uuid.uuid4().hex, status='queued', created_at=now())
            if attach:
                attach(old, job)
            self.jobs.append(job)
            self.persist()
            return job

    def remove_finished(self, job_id=None):
        with self.lock:
            if job_id is not None and self.get(job_id)['status'] not in FINISHED:
                raise ValueError(
                    Msg(
                        'server.queue.only_finished_jobs_can_be_cleared',
                        'Only finished jobs can be cleared. Cancel running or queued ones first.',
                    )
                )
            removed = {
                j['id']
                for j in self.jobs
                if j['status'] in FINISHED and (job_id is None or j['id'] == job_id)
            }
            self.jobs = [j for j in self.jobs if j['id'] not in removed]
            self.persist()
            return len(removed)

    def set_paused(self, paused):
        with self.lock:
            self.paused = bool(paused)
            self.persist()
            return self.paused
