"""The generation queue's life cycle (#86): what a job goes through, pinned before the worker was split from ComfyUI.

Each test runs one job the way the worker does (status 'running', then run_job) against a fake image server that
can hold a job, fail it or return a blank image.
"""

import io

from PIL import Image

from test_image import FakeComfy

TARGET = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}


def _png(color):
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), color).save(buffer, format='PNG')
    return buffer.getvalue()


class HeldComfy(FakeComfy):
    """A server whose job stays running (or waiting in its queue) until interrupted; a hook runs on submit."""

    def __init__(self, place='running', on_submit=None):
        super().__init__()
        self.place, self.on_submit = place, on_submit
        self.calls = []
        self.interrupted = False

    def request(self, path, body=None, raw=False, timeout=15):
        self.calls.append(path if body is None else (path, body))
        if path == '/prompt':
            self.prompts.append(body['prompt'])
            if self.on_submit:
                self.on_submit()
            return {'prompt_id': 'p1'}
        if path == '/queue':
            if body is not None:
                return {}
            if not self.prompts:
                return {}
            return (
                {'queue_running': [[0, 'p1']]} if self.place == 'running' else {'queue_pending': [[0, 'p1']]}
            )
        if path == '/interrupt':
            self.interrupted = True
            return {}
        if path.startswith('/history/'):
            if self.interrupted:
                return {
                    'p1': {'status': {'status_str': 'error', 'messages': [['execution_interrupted', {}]]}}
                }
            return {}
        return super().request(path, body, raw, timeout)


class BrokenComfy(FakeComfy):
    def __init__(self, history=None, image=None):
        super().__init__()
        self.history, self.image = history, image

    def request(self, path, body=None, raw=False, timeout=15):
        if path.startswith('/history/') and self.history is not None:
            return self.history
        if path.startswith('/view') and self.image is not None:
            return self.image
        return super().request(path, body, raw, timeout)


def _queued(c, comfy, count=1):
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = comfy
    runtime.set_paused(True)  # the test runs jobs itself instead of the worker thread
    runtime.gpu.admit = lambda kind: None  # no nvidia-smi in tests
    c.post(f'/api/works/{wid}/image/jobs', json={'targets': [TARGET], 'count': count})
    return runtime


def _run(runtime, job):
    job['status'] = 'running'
    runtime.run_job(job)
    return job


def test_a_job_cancelled_before_it_is_sent_never_reaches_the_server(unlocked):
    runtime = _queued(unlocked, HeldComfy())
    job = runtime.jobs[0]
    job['status'] = 'cancelling'
    runtime.run_job(job)
    assert job['status'] == 'cancelled'
    assert runtime.comfy.prompts == []


def test_a_running_job_is_interrupted_on_the_server_when_cancelled(unlocked):
    holder = {}
    comfy = HeldComfy('running', on_submit=lambda: holder['job'].update(status='cancelling'))
    runtime = _queued(unlocked, comfy)
    holder['job'] = runtime.jobs[0]
    _run(runtime, holder['job'])
    assert holder['job']['status'] == 'cancelled'
    assert comfy.interrupted and ('/interrupt', {'prompt_id': 'p1'}) in comfy.calls


def test_a_job_still_waiting_in_the_server_queue_is_deleted_there(unlocked):
    holder = {}
    comfy = HeldComfy('pending', on_submit=lambda: holder['job'].update(status='cancelling'))
    runtime = _queued(unlocked, comfy)
    holder['job'] = runtime.jobs[0]
    _run(runtime, holder['job'])
    assert holder['job']['status'] == 'cancelled'
    assert ('/queue', {'delete': ['p1']}) in comfy.calls and not comfy.interrupted


def test_a_server_error_fails_the_job_and_pauses_the_queue(unlocked):
    error = {'p1': {'status': {'status_str': 'error', 'messages': [['execution_error', {'msg': 'boom'}]]}}}
    runtime = _queued(unlocked, BrokenComfy(history=error), count=2)
    runtime.gpu.generation_allowed = lambda: False  # keep the worker thread away from the second job
    runtime.set_paused(False)
    job = _run(runtime, runtime.jobs[0])
    assert job['status'] == 'failed' and job['error'].key == 'server.worker.comfyui_generation_error'
    assert runtime.paused is True
    assert runtime.jobs[1]['status'] == 'queued'


def test_an_all_black_image_or_no_image_is_a_failure_and_nothing_is_saved(unlocked):
    runtime = _queued(unlocked, BrokenComfy(image=_png((0, 0, 0))))
    job = _run(runtime, runtime.jobs[0])
    assert job['status'] == 'failed' and job['error'].key == 'server.worker.an_all_black_image_came_back'
    assert not list(runtime.paths.output.rglob('*.png'))

    empty = {'p1': {'status': {'status_str': 'success'}, 'outputs': {'output': {'images': []}}}}
    runtime.comfy = BrokenComfy(history=empty)
    job = runtime.jobs[0]
    runtime.retry(job['id'])
    again = _run(runtime, runtime.jobs[-1])
    assert again['status'] == 'failed' and again['error'].key == 'server.worker.comfyui_returned_no_image'


def test_a_failed_job_is_retried_as_a_new_job_with_the_same_request(unlocked):
    runtime = _queued(unlocked, BrokenComfy(image=_png((0, 0, 0))))
    failed = _run(runtime, runtime.jobs[0])
    runtime.retry(failed['id'])
    fresh = runtime.jobs[-1]
    assert fresh['id'] != failed['id'] and fresh['status'] == 'queued'
    assert fresh['seed'] == failed['seed'] and fresh['snapshot'] == failed['snapshot']
    assert 'error' not in fresh and 'prompt_id' not in fresh

    runtime.comfy = FakeComfy()
    done = _run(runtime, fresh)
    assert done['status'] == 'completed' and done['image_url'].endswith('.png')
    refused = None
    try:
        runtime.retry(done['id'])
    except ValueError as error:
        refused = error
    assert refused is not None


def test_a_restart_marks_unfinished_work_interrupted_and_keeps_the_rest(unlocked):
    runtime = _queued(unlocked, FakeComfy(), count=3)
    first, second, _ = runtime.jobs
    first['status'] = 'running'
    second['status'] = 'cancelling'
    runtime.persist()
    runtime.jobs = []
    runtime.load_queue()
    assert [j['status'] for j in runtime.jobs] == ['interrupted', 'interrupted', 'queued']
    assert runtime.paused is True
    runtime.retry(runtime.jobs[0]['id'])
    assert runtime.jobs[-1]['status'] == 'queued'


def test_clearing_finished_jobs_and_cancelling_the_waiting_ones(unlocked):
    runtime = _queued(unlocked, FakeComfy(), count=3)
    done = _run(runtime, runtime.jobs[0])
    assert done['status'] == 'completed'
    runtime.cancel_queued()
    assert [j['status'] for j in runtime.jobs] == ['completed', 'cancelled', 'cancelled']
    assert runtime.remove_finished()['removed'] == 3 and runtime.jobs == []


class PaintService:
    """An image service that is not ComfyUI: no GPU turn, answers on the second check."""

    id = 'paint'
    local_gpu = False
    wait_limit = result_limit = 60

    def __init__(self):
        self.sent, self.checks = [], 0

    def busy(self):
        return False

    def submit(self, job):
        self.sent.append(job['snapshot']['positive'])
        return {'id': 'remote-1', 'record': {'prompt': job['snapshot']['positive']}}

    def poll(self, job, sent):
        self.checks += 1
        return None if self.checks < 2 else {'image': _png((10, 120, 200))}

    def cancel(self, job, sent):
        return True


def test_a_job_runs_on_the_service_it_names_without_comfyui(unlocked):
    runtime = _queued(unlocked, HeldComfy())
    paint = PaintService()
    runtime.services['paint'] = paint
    job = runtime.jobs[0]
    assert job['service'] == 'comfyui'
    job['service'] = 'paint'
    _run(runtime, job)
    assert job['status'] == 'completed' and job['prompt_id'] == 'remote-1'
    assert paint.sent and paint.checks == 2 and runtime.comfy.prompts == []

    job = runtime.jobs[0]
    job['service'] = 'nowhere'
    runtime.jobs.append({**job, 'id': 'x', 'status': 'running'})
    failed = runtime.run_job(runtime.jobs[-1]) or runtime.jobs[-1]
    assert failed['status'] == 'failed' and failed['error'].key == 'server.worker.unknown_service'
