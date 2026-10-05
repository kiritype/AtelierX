"""LLM calls (03-llm). One connection type to start with: OpenAI compatible (LM Studio, llama.cpp, vLLM …).

A provider of type ``mock`` answers without a server; tests and offline UI checks use it.
"""

import asyncio
import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse

import httpx

from .fsutil import read_json, write_json
from .i18n import AppError, Msg

TASKS = (
    'compression',
    'image_prompt',
    'jsx_prompt',
    'authoring',
    'consistency',
    'chat_test',
    'image_review',
    'agent',
)
PROVIDER_PRESETS = {'ollama', 'gemini', 'vertex', 'openrouter', 'deepseek', 'custom'}
VERTEX_PROJECT = re.compile(r'^[a-z][a-z0-9-]{4,28}[a-z0-9]$')
VERTEX_LOCATION = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
DEFAULT_PARAMS = {
    'compression': {'temperature': 0.3},
    'image_prompt': {'temperature': 0.2},
    'jsx_prompt': {'temperature': 0.4},
    'authoring': {'temperature': 0.7},
    'consistency': {'temperature': 0.0},
    'chat_test': {'temperature': 0.8},
    'agent': {'temperature': 0.5},
    'image_review': {'temperature': 0.0, 'max_tokens': 400},
}
LOOPBACK = ('127.0.0.1', 'localhost', '::1')
# Tasks that run while their caller already holds the GPU (VLM review holds it as ``validation``).
GPU_HELD_TASKS = {'image_review'}
THINK = re.compile(r'<think>.*?</think>\s*', re.DOTALL)
TIMEOUT = httpx.Timeout(connect=5, read=600, write=30, pool=5)


def strip_thinking(text):
    """Reasoning models may put their thoughts in <think> blocks; only the answer is kept."""
    text = THINK.sub('', text)
    # An unclosed block means the answer never started.
    return '' if '<think>' in text else text.strip()


def uses_local_gpu(provider):
    """Whether a connection's model runs on this PC's GPU, so it must take turns with image work. Saved as
    ``local_gpu``; without it, a server at this PC's address does."""
    if provider.get('local_gpu') is not None:
        return bool(provider['local_gpu'])
    host = urlparse(provider.get('base_url') or '').hostname or ''
    return provider.get('type') != 'mock' and host in LOOPBACK


class LlmGate:
    """Who may send an LLM request now (architecture: 작업 대기열과 GPU).

    Requests to a model on this PC's GPU share the GPU broker's ``llm`` hold with each other and take turns with image
    generation, VLM review, training and ComfyUI control. Other requests only wait for one of ``limit()`` slots.

    Both are counted under a thread lock, not with asyncio primitives: VLM review calls the LLM from the image worker
    thread in its own event loop, and a semaphore bound to the server's loop cannot be awaited there.
    """

    POLL = 0.5
    SLOT_POLL = 0.1

    def __init__(self, gpu=None, limit=lambda: 2):
        self.gpu, self.limit = gpu, limit
        self._lock = threading.Lock()
        self._running = 0

    async def wait_gpu(self):
        """Yield what holds the GPU while waiting; returns holding it. The caller calls ``end_gpu`` afterwards."""
        if self.gpu is None:
            return
        told = None
        while not self.gpu.try_llm():
            blocker = self.gpu.blocker()
            if blocker != told:
                told = blocker
                yield blocker
            await asyncio.sleep(self.POLL)

    def end_gpu(self):
        if self.gpu is not None:
            self.gpu.end_llm()

    def _size(self):
        try:
            return max(1, int(self.limit() or 1))
        except (TypeError, ValueError):
            return 2

    def _take_slot(self):
        # The limit is read each time, so a changed setting applies at once and running requests count against it.
        with self._lock:
            if self._running >= self._size():
                return False
            self._running += 1
            return True

    @asynccontextmanager
    async def external(self):
        """One of ``limit()`` request slots, from any thread or event loop."""
        while not self._take_slot():
            await asyncio.sleep(self.SLOT_POLL)
        try:
            yield
        finally:
            with self._lock:
                self._running -= 1


# Usage report groupings: connection·model·task, task, work.
USAGE_GROUPS = {'model': ('provider', 'model', 'task'), 'task': ('task',), 'work': ('work',)}


class Providers:
    def __init__(self, paths, vault):
        self.paths, self.vault = paths, vault
        self.file = paths.data / 'providers.json'
        self.gate = LlmGate()

    def doc(self):
        return read_json(self.file) or {'schema_version': 1, 'providers': {}, 'tasks': {}}

    def save(self, doc):
        for provider in doc.get('providers', {}).values():
            preset = provider.get('preset')
            if preset is not None and (not isinstance(preset, str) or preset not in PROVIDER_PRESETS):
                raise AppError(Msg('server.llm.invalid_preset', 'Choose a supported provider preset.'))
            if preset == 'vertex':
                project = provider.get('vertex_project')
                location = provider.get('vertex_location')
                if provider.get('type') != 'vertex_openai':
                    raise AppError(
                        Msg(
                            'server.llm.invalid_vertex_type',
                            'Vertex preset requires the Vertex OpenAI connection type.',
                        )
                    )
                if not isinstance(project, str) or not VERTEX_PROJECT.fullmatch(project):
                    raise AppError(
                        Msg('server.llm.invalid_vertex_project', 'Enter a valid Google Cloud project ID.')
                    )
                if not isinstance(location, str) or not (
                    location == 'global' or VERTEX_LOCATION.fullmatch(location)
                ):
                    raise AppError(
                        Msg('server.llm.invalid_vertex_location', 'Enter a valid Vertex AI location.')
                    )
                host = (
                    'aiplatform.googleapis.com'
                    if location == 'global'
                    else f'{location}-aiplatform.googleapis.com'
                )
                provider['base_url'] = (
                    f'https://{host}/v1/projects/{project}/locations/{location}/endpoints/openapi'
                )
            if provider.get('type') == 'mock':
                continue
            url = urlparse(provider.get('base_url') or '')
            if (
                url.scheme not in ('http', 'https')
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise AppError(
                    Msg(
                        'server.llm.invalid_url',
                        'Use an HTTP(S) base URL without credentials, query or fragment.',
                    )
                )
            if provider.get('key') and not str(provider['key']).startswith('secret:'):
                raise AppError(
                    Msg(
                        'server.llm.secret_reference',
                        'Save credentials in Settings and select the saved entry.',
                    )
                )
        write_json(self.file, doc)
        return doc

    def _on_gpu(self, provider, task):
        return task not in GPU_HELD_TASKS and uses_local_gpu(provider)

    def is_local(self, provider):
        host = urlparse(provider.get('base_url') or '').hostname or ''
        return provider.get('type') == 'mock' or provider.get('trusted') or host in LOOPBACK

    def resolve(self, task, override=None):
        """Provider, model and params for a task: the override, the task setting, then the `local` provider's default."""
        doc = self.doc()
        task_setting = doc.get('tasks', {}).get(task, {})
        override = override or {}
        setting = {**task_setting, **override}
        provider_id = setting.get('provider') or 'local'
        provider = doc.get('providers', {}).get(provider_id)
        if provider is None:
            raise AppError(
                Msg('server.llm.no_provider', 'LLM connection {id} does not exist.', id=provider_id)
            )
        # A per-run provider choice is independent of the task's saved model. Reuse the
        # task model only when no provider is selected for the run; otherwise use the selected
        # provider's default unless the run explicitly supplies a model.
        provider_overridden = 'provider' in override
        model = override.get('model') or (
            provider.get('default_model')
            if provider_overridden
            else task_setting.get('model') or provider.get('default_model')
        )
        if not model and provider.get('type') != 'mock':
            raise AppError(
                Msg(
                    'server.llm.no_model',
                    'Choose a model for {name} in Settings → LLM.',
                    name=provider.get('name'),
                )
            )
        params = {**DEFAULT_PARAMS.get(task, {}), **(setting.get('params') or {})}
        return {'id': provider_id, **provider}, model, params

    def require_consent(self, work, task, override=None):
        """External connections need the work's consent first (03-llm: 외부 전송 확인). Local ones never ask."""
        provider, _, _ = self.resolve(task, override)
        if self.is_local(provider) or provider['id'] in (work.doc().get('llm_consent') or []):
            return
        raise AppError(
            Msg(
                'server.llm.consent_needed',
                "Sending the contents of {work} to {name}. That service's terms and data handling apply.",
                work=work.name,
                name=provider.get('name'),
                provider=provider['id'],
            ),
            428,
        )

    # --- usage (data/usage/YYYY-MM.jsonl, one line per answered request) ------------------------------------------

    def usage_months(self):
        """Months that have a usage file, newest first."""
        folder = self.paths.data / 'usage'
        months = [p.stem for p in folder.glob('*.jsonl')] if folder.is_dir() else []
        return sorted((m for m in months if re.fullmatch(r'\d{4}-\d{2}', m)), reverse=True)

    def usage_entries(self, month):
        if not re.fullmatch(r'\d{4}-\d{2}', str(month or '')):
            return []
        path = self.paths.data / 'usage' / f'{month}.jsonl'
        entries = []
        if path.is_file():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def usage(self, month, by='model'):
        """Requests and tokens of one month (YYYY-MM), grouped by connection·model·task, by task or by work.

        ``unknown`` counts requests whose server did not report tokens; their tokens are not in the sums.
        """
        fields = USAGE_GROUPS.get(by, USAGE_GROUPS['model'])
        rows = {}
        for entry in self.usage_entries(month):
            key = tuple(entry.get(f) for f in fields)
            row = rows.setdefault(
                key,
                {
                    **dict(zip(fields, key)),
                    'requests': 0,
                    'unknown': 0,
                    'input_tokens': 0,
                    'output_tokens': 0,
                },
            )
            row['requests'] += 1
            if entry.get('input_tokens') is None and entry.get('output_tokens') is None:
                row['unknown'] += 1
            row['input_tokens'] += entry.get('input_tokens') or 0
            row['output_tokens'] += entry.get('output_tokens') or 0
        return sorted(rows.values(), key=lambda r: -r['requests'])

    def usage_tasks(self, month):
        """The tasks that appear in the month, for the request log's filter (whatever the grouping)."""
        return sorted({e.get('task') for e in self.usage_entries(month) if e.get('task')})

    def usage_log(self, month, offset=0, limit=50, work=None, task=None):
        """The month's requests one by one, newest first, optionally only one work or task."""
        entries = [
            e
            for e in reversed(self.usage_entries(month))
            if (not work or e.get('work') == work) and (not task or e.get('task') == task)
        ]
        offset, limit = max(0, int(offset)), min(max(1, int(limit)), 500)
        return {'total': len(entries), 'offset': offset, 'rows': entries[offset : offset + limit]}

    def _headers(self, provider):
        key = provider.get('key')
        if key and str(key).startswith('secret:'):
            secret = self.vault.reveal(str(key)[len('secret:') :])
            if not secret:
                raise AppError(
                    Msg(
                        'server.llm.missing_key',
                        'The selected credential is missing or empty. Save it in Settings.',
                    )
                )
            return {'Authorization': f'Bearer {secret}'}
        return {}

    def _url(self, provider, path):
        return (provider.get('base_url') or '').rstrip('/') + path

    def _unreachable(self, provider):
        return AppError(
            Msg(
                'server.llm.unreachable',
                'Cannot reach {name} ({url}). Check that the server is running and the address is right.',
                name=provider.get('name'),
                url=provider.get('base_url'),
            ),
            502,
        )

    def _http_error(self, provider, response):
        # An upstream error may echo authorization or request contents. Never persist/display it verbatim.
        detail = {
            401: 'Check the credential; Google Cloud access tokens expire and must be replaced.',
            403: 'Check API access, project permissions and enabled services.',
            404: 'Check the API base URL and model ID. Model listing may be unsupported.',
            429: 'Quota or rate limit reached. Check the service account and retry later.',
        }.get(
            response.status_code,
            'The service rejected the request. Check its supported parameters and status.',
        )
        return AppError(
            Msg(
                'server.llm.http_error',
                '{name} answered {status}: {detail}',
                name=provider.get('name'),
                status=response.status_code,
                detail=detail or '',
            ),
            502,
        )

    async def models(self, provider_id):
        provider = self.doc().get('providers', {}).get(provider_id)
        if provider is None:
            raise AppError(
                Msg('server.llm.no_provider', 'LLM connection {id} does not exist.', id=provider_id), 404
            )
        if provider.get('type') == 'mock':
            return ['mock']
        if provider.get('type') == 'vertex_openai':
            # Vertex's OpenAI endpoint does not provide the usual model catalog.
            return list(
                dict.fromkeys([m for m in [provider.get('default_model'), *provider.get('models', {})] if m])
            )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
                response = await client.get(self._url(provider, '/models'), headers=self._headers(provider))
        except httpx.HTTPError as exc:
            raise self._unreachable(provider) from exc
        if response.status_code >= 400:
            raise self._http_error(provider, response)
        return [m.get('id') for m in response.json().get('data', []) if m.get('id')]

    async def probe(self, provider_id):
        """Explicit, billable test using only fixed synthetic content, never the open work."""
        override = {'provider': provider_id, 'params': {'max_tokens': 128, 'temperature': 0}}
        messages = [{'role': 'user', 'content': 'Reply with the single word OK.'}]
        result = await self.complete('connection_test', messages, override=override)
        if not result['text']:
            raise AppError(
                Msg(
                    'server.llm.empty_test',
                    'The service returned no visible answer. Check the model and token limit.',
                ),
                502,
            )
        pieces = []
        async for event in self.stream('connection_test', messages, override=override):
            if event['type'] == 'text':
                pieces.append(event['text'])
        if not ''.join(pieces).strip():
            raise AppError(
                Msg('server.llm.empty_stream', 'The streaming test returned no visible answer.'), 502
            )
        return {'ok': True, 'model': result['model'], 'completion': True, 'stream': True}

    def _log_usage(self, provider, model, task, work_id, usage):
        # Every answered request is counted; servers that report no tokens leave them empty (shown as unknown).
        usage = usage or {}
        now = datetime.now().astimezone()
        line = {
            'at': now.isoformat(timespec='seconds'),
            'provider': provider['id'],
            'model': model,
            'task': task,
            'work': work_id,
            'input_tokens': usage.get('prompt_tokens'),
            'output_tokens': usage.get('completion_tokens'),
        }
        folder = self.paths.data / 'usage'
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / f'{now:%Y-%m}.jsonl').open('a', encoding='utf-8') as file:
            file.write(json.dumps(line, ensure_ascii=False) + '\n')

    async def complete(self, task, messages, work_id=None, override=None, json_mode=False):
        """One full answer, with reasoning removed. Returns ``{text, model, provider, usage}``."""
        resolved = self.resolve(task, override)
        if self._on_gpu(resolved[0], task):
            async for _ in self.gate.wait_gpu():
                pass
            try:
                return await self._complete(resolved, task, messages, work_id, json_mode)
            finally:
                self.gate.end_gpu()
        async with self.gate.external():
            return await self._complete(resolved, task, messages, work_id, json_mode)

    async def _complete(self, resolved, task, messages, work_id, json_mode):
        provider, model, params = resolved
        if provider.get('type') == 'mock':
            return {
                'text': mock_answer(task, messages),
                'model': 'mock',
                'provider': provider['id'],
                'usage': None,
            }
        body = {'model': model, 'messages': messages, 'stream': False, **params}
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    self._url(provider, '/chat/completions'), json=body, headers=self._headers(provider)
                )
                if response.status_code == 400 and json_mode:
                    # Some servers reject json_object; the instructions already ask for JSON.
                    body.pop('response_format')
                    response = await client.post(
                        self._url(provider, '/chat/completions'), json=body, headers=self._headers(provider)
                    )
        except httpx.HTTPError as exc:
            raise self._unreachable(provider) from exc
        if response.status_code >= 400:
            raise self._http_error(provider, response)
        data = response.json()
        usage = data.get('usage')
        self._log_usage(provider, model, task, work_id, usage)
        text = data['choices'][0]['message'].get('content') or ''
        return {'text': strip_thinking(text), 'model': model, 'provider': provider['id'], 'usage': usage}

    async def stream(self, task, messages, work_id=None, override=None):
        """Yield ``{'type': 'text', 'text': …}`` pieces of the answer, occasional ``{'type': 'thinking', 'chars': n}`` and
        last ``{'type': 'done', 'finish_reason': …}`` (``length`` when the answer hit the output limit).

        Reasoning arrives either in separate delta fields or inside <think> … </think>; it is counted, never shown.
        While the request waits for the GPU, ``{'type': 'waiting', 'holder': Msg}`` says what it waits for.
        """
        resolved = self.resolve(task, override)
        if self._on_gpu(resolved[0], task):
            async for holder in self.gate.wait_gpu():
                yield {'type': 'waiting', 'holder': holder}
            try:
                async for event in self._stream(resolved, task, messages, work_id):
                    yield event
            finally:
                self.gate.end_gpu()
            return
        async with self.gate.external():
            async for event in self._stream(resolved, task, messages, work_id):
                yield event

    async def _stream(self, resolved, task, messages, work_id):
        provider, model, params = resolved
        if provider.get('type') == 'mock':
            pieces = mock_answer(task, messages).split(' ')
            for n, piece in enumerate(pieces):
                yield {'type': 'text', 'text': piece if n == len(pieces) - 1 else piece + ' '}
            yield {'type': 'done', 'finish_reason': 'stop'}
            return
        body = {
            'model': model,
            'messages': messages,
            'stream': True,
            'stream_options': {'include_usage': True},
            **params,
        }
        state = {'inside': False, 'buffer': '', 'thought': 0, 'reported': 0}
        usage = None
        finish_reason = None
        try:
            async with (
                httpx.AsyncClient(timeout=TIMEOUT) as client,
                client.stream(
                    'POST',
                    self._url(provider, '/chat/completions'),
                    json=body,
                    headers=self._headers(provider),
                ) as response,
            ):
                if response.status_code >= 400:
                    await response.aread()
                    raise self._http_error(provider, response)
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    payload = line[5:].strip()
                    if payload == '[DONE]':
                        break
                    data = json.loads(payload)
                    usage = data.get('usage') or usage
                    choices = data.get('choices') or []
                    delta = (choices[0].get('delta') or {}) if choices else {}
                    finish_reason = (choices[0].get('finish_reason') if choices else None) or finish_reason
                    reasoning = delta.get('reasoning_content') or delta.get('reasoning') or ''
                    state['thought'] += len(reasoning)
                    for event in _split_think(state, delta.get('content') or ''):
                        yield event
                    if state['thought'] - state['reported'] >= 200:
                        state['reported'] = state['thought']
                        yield {'type': 'thinking', 'chars': state['thought']}
                if state['buffer'] and not state['inside']:
                    yield {'type': 'text', 'text': state['buffer']}
        except httpx.HTTPError as exc:
            raise self._unreachable(provider) from exc
        self._log_usage(provider, model, task, work_id, usage)
        yield {'type': 'done', 'finish_reason': finish_reason}


def _split_think(state, piece):
    """Route streamed text around <think> … </think>, holding back a tag that may continue in the next piece."""
    state['buffer'] += piece
    while state['buffer']:
        buffer = state['buffer']
        if state['inside']:
            end = buffer.find('</think>')
            if end < 0:
                state['thought'] += max(0, len(buffer) - 8)
                state['buffer'] = buffer[-8:]
                return
            state['thought'] += end
            state['buffer'], state['inside'] = buffer[end + len('</think>') :].lstrip(), False
            continue
        start = buffer.find('<think>')
        if start < 0:
            hold = next(
                (i for i in range(min(6, len(buffer)), 0, -1) if '<think>'.startswith(buffer[-i:])), 0
            )
            out, state['buffer'] = buffer[: len(buffer) - hold], buffer[len(buffer) - hold :]
            if out:
                yield {'type': 'text', 'text': out}
            return
        if start:
            yield {'type': 'text', 'text': buffer[:start]}
        state['buffer'], state['inside'] = buffer[start + len('<think>') :], True


def parse_json(text):
    """The first JSON object in an answer (models sometimes wrap it in ``` fences or add a sentence)."""
    text = strip_thinking(text)
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find('{') : text.rfind('}') + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def mock_answer(task, messages):
    last = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
    if task == 'chat_test':
        return f'(모의 응답) "{last[:60]}"에 대한 답입니다. 설정 → LLM에서 실제 연결을 고르면 진짜 응답이 나옵니다.'
    if task == 'agent':
        from .agent import mock_reply

        return mock_reply(messages)
    if task == 'image_review':
        return '{"verdict": "pass", "evidence": "(모의 검수) 모의 연결은 그림을 보지 않고 통과로 답합니다."}'
    return '{}'
