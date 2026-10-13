import asyncio
import threading

import pytest

from atelierx.core import updater as module
from atelierx.core.admission import Admission, AdmissionMiddleware
from atelierx.core.i18n import AppError
from atelierx.core.updater import Updater


def test_apply_rechecks_work_started_after_preparation(paths, monkeypatch):
    up = Updater(paths, busy=lambda: ['training'])
    up._set(state='ready', version='v9.9.9')
    monkeypatch.setattr(up, 'packaged', lambda: True)
    monkeypatch.setattr(module, 'launch', lambda _: pytest.fail('must not launch'))
    with pytest.raises(AppError, match='training'):
        up.apply()
    assert up.status()['state'] == 'ready'
    assert not up.folder.exists()
    assert not up.admission.stopping


def test_apply_closes_admission_before_launch_and_recovers_on_failure(paths, monkeypatch):
    up = Updater(paths)
    up._set(state='ready', version='v9.9.9')
    monkeypatch.setattr(up, 'packaged', lambda: True)
    observed = []

    def launch(_):
        def request():
            with pytest.raises(AppError), up.admission.enter():
                pytest.fail('new work entered after busy check')
            observed.append(True)

        thread = threading.Thread(target=request)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        raise OSError('launch failed')

    monkeypatch.setattr(module, 'launch', launch)
    with pytest.raises(OSError):
        up.apply()
    assert observed == [True]
    with up.admission.enter():
        pass
    monkeypatch.setattr(module, 'launch', lambda _: None)
    assert up.apply()['state'] == 'restarting'
    with pytest.raises(AppError), up.admission.enter():
        pass


def test_stream_request_blocks_apply_until_response_finishes():
    async def scenario():
        admission = Admission()
        started, release = asyncio.Event(), asyncio.Event()

        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            started.set()
            await release.wait()
            await send({'type': 'http.response.body', 'body': b'done'})

        async def noop(*_):
            pass

        middleware = AdmissionMiddleware(app, admission)
        task = asyncio.create_task(
            middleware({'type': 'http', 'method': 'POST', 'path': '/api/work/w/chat/send'}, noop, noop)
        )
        await started.wait()
        with pytest.raises(AppError), admission.stop(list):
            pass
        release.set()
        await task
        with admission.stop(list):
            pass

    asyncio.run(scenario())


def test_http_work_is_rejected_after_apply(unlocked, monkeypatch):
    up = unlocked.app.state.app.updater
    up._set(state='ready', version='v9.9.9')
    monkeypatch.setattr(up, 'packaged', lambda: True)
    monkeypatch.setattr(module, 'launch', lambda _: None)
    assert unlocked.post('/api/update/apply').status_code == 200
    assert unlocked.post('/api/works', json={'name': 'blocked'}).status_code == 409
    assert unlocked.get('/api/works').status_code == 409
    assert unlocked.get('/api/update/status').status_code == 200


@pytest.mark.parametrize('kind', ['download', 'install', 'deploy', 'convert', 'job'])
def test_apply_refuses_background_and_cancelling_work(unlocked, monkeypatch, kind):
    state = unlocked.app.state.app
    up = state.updater
    up._set(state='ready', version='v9.9.9')
    monkeypatch.setattr(up, 'packaged', lambda: True)
    monkeypatch.setattr(module, 'launch', lambda _: pytest.fail('must not launch'))
    if kind == 'download':
        state.image.model_downloads.jobs.append({'status': 'running'})
    elif kind == 'install':
        state.image.installs.run = {'status': 'cancelling', 'section': 'models'}
    elif kind == 'deploy':
        monkeypatch.setattr(
            state.image.deploy,
            'active',
            lambda: [{'status': 'cancelling', 'done': 0, 'total': 1, 'target_name': 'test'}],
        )
    elif kind == 'convert':
        state.image.convert.tasks['test'] = {'status': 'running', 'done': 0, 'total': 1}
    else:
        state.jobs.jobs['test'] = {'status': 'cancelling'}
    assert unlocked.post('/api/update/apply').status_code == 409
    assert up.status()['state'] == 'ready'
