"""Local LLM requests take turns with image work on the GPU; other connections only share request slots."""

import asyncio
import threading

import pytest

from atelierx.core.i18n import AppError
from atelierx.core.llm import LlmGate, Providers, uses_local_gpu
from atelierx.core.vault import Vault
from atelierx.image.gpu import GpuBroker

MOCK_ON_GPU = {'name': 'gpu mock', 'type': 'mock', 'local_gpu': True}
MOCK_ELSEWHERE = {'name': 'mock', 'type': 'mock'}


def _setup(paths, provider, limit=2):
    image_jobs = []
    broker = GpuBroker(paths, threading.RLock(), lambda: image_jobs)
    llm = Providers(paths, Vault(paths.vault_file))
    llm.save({'schema_version': 1, 'providers': {'local': provider}, 'tasks': {}})
    llm.gate = LlmGate(broker, lambda: limit)
    llm.gate.POLL = 0.01
    return llm, broker, image_jobs


def test_which_connections_use_this_pcs_gpu():
    assert uses_local_gpu({'type': 'openai_compatible', 'base_url': 'http://127.0.0.1:1234/v1'})
    assert uses_local_gpu({'type': 'openai_compatible', 'base_url': 'http://localhost:8080/v1'})
    assert not uses_local_gpu({'type': 'openai_compatible', 'base_url': 'https://api.example.com/v1'})
    assert not uses_local_gpu({'type': 'mock'})
    # The saved choice wins: a server on another PC of the network, or a local proxy to a remote service.
    assert uses_local_gpu(
        {'type': 'openai_compatible', 'base_url': 'http://192.168.0.9/v1', 'local_gpu': True}
    )
    assert not uses_local_gpu(
        {'type': 'openai_compatible', 'base_url': 'http://127.0.0.1:4000/v1', 'local_gpu': False}
    )


def test_a_local_answer_waits_for_the_gpu_and_holds_it_until_done(paths):
    llm, broker, _ = _setup(paths, MOCK_ON_GPU)
    assert broker.acquire('validation', 'reviewing')

    async def run():
        events = []

        async def free_later():
            await asyncio.sleep(0.05)
            broker.release('validation')

        freeing = asyncio.create_task(free_later())
        async for event in llm.stream('chat_test', [{'role': 'user', 'content': 'hi'}]):
            events.append(event)
            if event['type'] == 'text':
                # While the answer comes, the GPU is the LLM's: no image starts and no review takes it.
                assert broker.held_by('llm') and not broker.generation_allowed()
                assert not broker.acquire('validation', 'reviewing')
        await freeing
        return events

    events = asyncio.run(run())
    assert events[0] == {'type': 'waiting', 'holder': 'VLM review'}
    assert events[-1]['type'] == 'done'
    assert broker.holder is None


def test_a_local_request_lets_the_image_in_progress_finish(paths):
    llm, broker, image_jobs = _setup(paths, MOCK_ON_GPU)
    image_jobs.append({'status': 'running'})

    async def run():
        async def finish_later():
            await asyncio.sleep(0.05)
            image_jobs[0]['status'] = 'completed'

        finishing = asyncio.create_task(finish_later())
        answer = await llm.complete('compression', [{'role': 'user', 'content': 'x'}])
        await finishing
        return answer

    assert asyncio.run(run())['provider'] == 'local'
    assert broker.holder is None


def test_stopping_or_failing_gives_the_gpu_back(paths):
    llm, broker, _ = _setup(paths, MOCK_ON_GPU)

    async def stop_midway():
        stream = llm.stream('agent', [{'role': 'user', 'content': 'a b c d'}])
        async for event in stream:
            if event['type'] == 'text':
                assert broker.held_by('llm')
                break
        await stream.aclose()

    asyncio.run(stop_midway())
    assert broker.holder is None

    async def cancel_while_waiting():
        broker.acquire('training', 'training')
        task = asyncio.create_task(llm.complete('compression', [{'role': 'user', 'content': 'x'}]))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_while_waiting())
    assert broker.holder == 'training'
    broker.release('training')

    unreachable = {
        'name': 'down',
        'type': 'openai_compatible',
        'base_url': 'http://127.0.0.1:9/v1',
        'default_model': 'm',
    }
    llm, broker, _ = _setup(paths, unreachable)
    with pytest.raises(AppError):
        asyncio.run(llm.complete('compression', [{'role': 'user', 'content': 'x'}]))
    assert broker.holder is None


def test_the_vlm_review_does_not_wait_for_itself(paths):
    llm, broker, _ = _setup(paths, MOCK_ON_GPU)
    broker.acquire('validation', 'reviewing')
    answer = asyncio.run(
        asyncio.wait_for(llm.complete('image_review', [{'role': 'user', 'content': 'x'}]), 1)
    )
    assert 'verdict' in answer['text'] and broker.holder == 'validation'


def test_other_connections_skip_the_gpu_and_share_request_slots(paths):
    llm, broker, _ = _setup(paths, MOCK_ELSEWHERE, limit=2)
    broker.acquire('training', 'training')
    running, most = 0, 0
    original = llm._complete

    async def slow(*args):
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.03)
        running -= 1
        return await original(*args)

    llm._complete = slow

    async def run():
        calls = [llm.complete('compression', [{'role': 'user', 'content': str(n)}]) for n in range(5)]
        return await asyncio.wait_for(asyncio.gather(*calls), 2)

    assert len(asyncio.run(run())) == 5
    assert most == 2
    assert broker.holder == 'training'
