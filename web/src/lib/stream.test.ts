import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, setConsentHandler, setUnauthorizedHandler } from '../api';
import { applyEvent, eventSplitter, postStream, type StreamEvent, type StreamState } from './stream';

const sse = (...events: [string, unknown][]) => events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join('');

function streamResponse(chunks: string[]) {
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

const refusal = (status: number, key: string) => new Response(JSON.stringify({ error: { key, text: key } }), { status });

afterEach(() => {
  vi.unstubAllGlobals();
  setConsentHandler(async () => false);
  setUnauthorizedHandler(() => {});
});

describe('stream events', () => {
  it('joins an event cut between two chunks', () => {
    const split = eventSplitter();
    const whole = sse(['delta', '안녕'], ['delta', '하세요'], ['end', null]);
    const cut = whole.indexOf('하세요') - 3;
    expect([...split(whole.slice(0, cut)), ...split(whole.slice(cut))].map((e) => e.type)).toEqual(['delta', 'delta', 'end']);
  });

  it('builds the answer from deltas and keeps the other fields', () => {
    const events: StreamEvent[] = [
      { type: 'context', data: '{"tokens": 10}' },
      { type: 'thinking', data: '3' },
      { type: 'delta', data: '"가"' },
      { type: 'delta', data: '"나"' },
      { type: 'end', data: 'null' },
    ];
    const state = events.reduce<StreamState>(applyEvent, { text: '' });
    expect(state).toEqual({ text: '가나', context: { tokens: 10 }, thinking: 3, done: true });
  });
});

describe('postStream', () => {
  it('hands every event over in order', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse([sse(['delta', 'a']).slice(0, 10), sse(['delta', 'a']).slice(10) + sse(['delta', 'b'])])));
    const seen: string[] = [];
    await postStream('/x', {}, new AbortController().signal, (e) => seen.push(JSON.parse(e.data)));
    expect(seen).toEqual(['a', 'b']);
  });

  it('asks for consent once and sends again when given', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(refusal(428, 'server.llm.consent_needed')).mockResolvedValueOnce(streamResponse([sse(['delta', 'ok'])]));
    vi.stubGlobal('fetch', fetch);
    setConsentHandler(async () => true);
    const seen: string[] = [];
    await postStream('/x', {}, new AbortController().signal, (e) => seen.push(e.type));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(seen).toEqual(['delta']);
  });

  it('throws the refusal when consent is declined, and sends a lost session to the unlock screen', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => refusal(428, 'server.llm.consent_needed')));
    await expect(postStream('/x', {}, new AbortController().signal, () => {})).rejects.toBeInstanceOf(ApiError);
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    vi.stubGlobal('fetch', vi.fn(async () => refusal(401, 'server.auth.required')));
    await expect(postStream('/x', {}, new AbortController().signal, () => {})).rejects.toMatchObject({ status: 401 });
    expect(unauthorized).toHaveBeenCalledOnce();
  });

  it('stops when the caller aborts', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_, reject) => init.signal!.addEventListener('abort', () => reject(new DOMException('stopped', 'AbortError'))))));
    const controller = new AbortController();
    const running = postStream('/x', {}, controller.signal, () => {});
    controller.abort();
    await expect(running).rejects.toThrow('stopped');
  });
});
