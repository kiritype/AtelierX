"""How much a model reads and writes (03-llm: 모델 맥락 길이).

Services that tell it are asked directly; for the rest a short table of known models fills in. Every value can be
changed by the user in Settings → LLM, and the saved value always wins.
"""

import re
from urllib.parse import quote, urlparse

LOOPBACK = ('127.0.0.1', 'localhost', '::1')
# Models whose services do not report limits (Vertex AI's OpenAI endpoint, DeepSeek). Input tokens.
KNOWN = (
    (re.compile(r'^(?:google/)?gemini-'), 1_048_576),
    (re.compile(r'^(?:deepseek/)?deepseek-(?:chat|reasoner)$'), 131_072),
)
MAX_TOKENS = 100_000_000


def known(model):
    """The table's context length for ``model``, or None."""
    name = str(model or '').strip().lower()
    for pattern, context in KNOWN:
        if pattern.search(name):
            return {'context': context, 'max_output': None, 'capabilities': []}
    return None


def valid_tokens(value):
    return value is None or (
        isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_TOKENS
    )


def _root(base_url):
    url = urlparse(base_url or '')
    return f'{url.scheme}://{url.netloc}'


def _int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= MAX_TOKENS else None


def ollama_limits(data):
    """``/api/show``: ``model_info["<architecture>.context_length"]`` (the architecture name may differ from the model
    name), lowered to ``num_ctx`` when the model is set to use less."""
    info = data.get('model_info') or {}
    arch = info.get('general.architecture')
    context = _int(info.get(f'{arch}.context_length')) if arch else None
    if context is None:
        context = next((_int(v) for k, v in info.items() if k.endswith('.context_length') and _int(v)), None)
    match = re.search(r'^\s*num_ctx\s+(\d+)', str(data.get('parameters') or ''), re.MULTILINE)
    if match and context and _int(match.group(1)):
        context = min(context, int(match.group(1)))
    if context is None:
        return None
    return {'context': context, 'max_output': None, 'capabilities': list(data.get('capabilities') or [])}


async def read(provider, model, client, secret):
    """Ask the connection's service for ``model``'s limits; None when it cannot tell. ``secret()`` gives the key."""
    url = urlparse(provider.get('base_url') or '')
    host, root = (url.hostname or '').lower(), _root(provider.get('base_url'))

    if provider.get('preset') == 'ollama' or host == 'ollama.com' or url.port == 11434:
        key = secret()
        response = await client.post(
            f'{root}/api/show',
            json={'model': model},
            headers={'Authorization': f'Bearer {key}'} if key else {},
        )
        return ollama_limits(response.json()) if response.status_code == 200 else None

    if host == 'generativelanguage.googleapis.com':
        key = secret()
        name = model.removeprefix('models/')
        response = await client.get(
            f'{root}/v1beta/models/{quote(name, safe="")}', headers={'x-goog-api-key': key} if key else {}
        )
        if response.status_code != 200:
            return None
        data = response.json()
        context = _int(data.get('inputTokenLimit'))
        if context is None:
            return None
        return {'context': context, 'max_output': _int(data.get('outputTokenLimit')), 'capabilities': []}

    if host == 'openrouter.ai':
        response = await client.get((provider.get('base_url') or '').rstrip('/') + '/models')
        if response.status_code != 200:
            return None
        entry = next((m for m in response.json().get('data') or [] if m.get('id') == model), None)
        if not entry or _int(entry.get('context_length')) is None:
            return None
        top = entry.get('top_provider') or {}
        return {
            'context': _int(entry['context_length']),
            'max_output': _int(top.get('max_completion_tokens')),
            'capabilities': [],
        }

    if host in LOOPBACK:
        # LM Studio: the loaded length when the model is in memory, else the model's maximum.
        response = await client.get(f'{root}/api/v0/models/{quote(model, safe="")}')
        if response.status_code != 200:
            return None
        data = response.json()
        context = _int(data.get('loaded_context_length')) or _int(data.get('max_context_length'))
        if context is None:
            return None
        return {'context': context, 'max_output': None, 'capabilities': []}
    return None
