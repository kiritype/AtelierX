"""Job queue (architecture: 작업 대기열과 GPU). In 0단계 jobs run mock work so the flows can be tried."""

import asyncio
import secrets
import traceback

from .i18n import AppError, Msg
from .lifecycle import CANCELLED, CANCELLING, DONE, FAILED, QUEUED, RUNNING
from .works import now_iso


class Jobs:
    def __init__(self, events):
        self.events = events
        self.jobs = {}
        # Batch LLM jobs to a model on this PC's GPU (compression, image prompts, formatting) run one at a time; the
        # GPU itself is shared with image work through the LLM gate (core/llm.py).
        self._gpu = asyncio.Lock()

    def list(self):
        return sorted(self.jobs.values(), key=lambda j: j['created_at'], reverse=True)

    def submit(self, kind, title, runner, gpu=False, work_id=None):
        job_id = secrets.token_hex(6)
        job = {
            'id': job_id,
            'kind': kind,
            'title': title,
            'status': QUEUED,
            'progress': 0,
            'result': None,
            'error': None,
            'work_id': work_id,
            'created_at': now_iso(),
        }
        self.jobs[job_id] = job
        self.events.publish('job', job)
        job['_task'] = asyncio.get_running_loop().create_task(self._run(job, runner, gpu))
        return self.public(job)

    def public(self, job):
        return {k: v for k, v in job.items() if not k.startswith('_')}

    async def _run(self, job, runner, gpu):
        async def progress(value):
            job['progress'] = value
            self.events.publish('job', self.public(job))

        try:
            if gpu:
                async with self._gpu:
                    job['status'] = RUNNING
                    self.events.publish('job', self.public(job))
                    job['result'] = await runner(progress)
            else:
                job['status'] = RUNNING
                self.events.publish('job', self.public(job))
                job['result'] = await runner(progress)
            job['status'], job['progress'] = DONE, 100
            self.events.publish(
                'notice',
                {
                    'key': 'notice.job_done',
                    'text': f'{job["title"]} 완료',
                    'job': job['id'],
                    'result': job['result'],
                },
            )
        except asyncio.CancelledError:
            job['status'] = CANCELLED
        except AppError as error:
            job['status'], job['error'] = FAILED, error.msg.as_dict()
        except Exception as error:  # noqa: BLE001 - surface unexpected failures as a failed job, not a crash
            traceback.print_exc()
            job['status'] = FAILED
            job['error'] = Msg('server.jobs.failed', 'The job failed: {error}', error=str(error)).as_dict()
        self.events.publish('job', self.public(job))

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise AppError(Msg('server.jobs.missing', 'This job does not exist.'), 404)
        if job['status'] in (QUEUED, RUNNING):
            job['status'] = CANCELLING
            self.events.publish('job', self.public(job))
            job['_task'].cancel()
        return self.public(job)
