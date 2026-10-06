// Streaming answers (#87): the chat test and the agent panel post a request and read `text/event-stream` events
// (event: <type>\ndata: <json>) until the server ends it. One client for both, so consent, a lost session, errors
// and stopping work the same way everywhere.

import { useEffect, useMemo, useRef } from 'react';
import { ApiError, askConsent, notifyUnauthorized } from '../api';
import { tm } from '../i18n';

export type StreamEvent = { type: string; data: string };

// Turns chunks of the body into whole events; an event cut between two chunks waits for the rest.
export function eventSplitter() {
  let buffer = '';
  return (chunk: string): StreamEvent[] => {
    buffer += chunk;
    const parts = buffer.split('\n\n');
    buffer = parts.pop()!;
    const out: StreamEvent[] = [];
    for (const raw of parts) {
      const type = /event: (\w+)/.exec(raw)?.[1];
      const data = /data: (.*)/s.exec(raw)?.[1];
      if (type && data !== undefined) out.push({ type, data });
    }
    return out;
  };
}

// The fields both screens keep while an answer arrives.
export type StreamState = { text: string; context?: unknown; thinking?: number; waiting?: string; error?: string; done?: boolean };

export function applyEvent<T extends StreamState>(state: T, event: StreamEvent): T {
  const { type, data } = event;
  if (type === 'context') return { ...state, context: JSON.parse(data) };
  if (type === 'thinking') return { ...state, thinking: Number(data) };
  if (type === 'waiting') return { ...state, waiting: tm(JSON.parse(data)) };
  if (type === 'delta') return { ...state, text: state.text + JSON.parse(data) };
  if (type === 'error') return { ...state, error: tm(JSON.parse(data)) };
  if (type === 'end') return { ...state, done: true };
  return state;
}

// POST `body` and hand every event to `onEvent` until the stream ends. Asks for consent once when an external
// connection needs it, sends a lost session to the unlock screen, and throws ApiError for a refused request.
// Stopping is the caller's `signal`; the fetch then rejects with an AbortError.
export async function postStream(url: string, body: unknown, signal: AbortSignal, onEvent: (event: StreamEvent) => void) {
  const request = () => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), credentials: 'same-origin', signal });
  let response = await request();
  if (response.status === 428) {
    const error = (await response.json()).error;
    if (!(await askConsent(error, url))) throw new ApiError(428, error);
    response = await request();
  }
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized();
    const error = (await response.json().catch(() => null))?.error;
    throw new ApiError(response.status, error ?? { key: 'error.unknown', text: response.statusText });
  }
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  const split = eventSplitter();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const event of split(decoder.decode(value, { stream: true }))) onEvent(event);
  }
}

// Who owns the answer on its way: starting one hands out its AbortController, leaving the screen (or changing `deps`)
// stops it, and only the request still in charge may clear the shared state when it ends.
export function useStreamOwner(deps: unknown[]) {
  const current = useRef<AbortController | null>(null);
  const gone = useRef(false);
  useEffect(() => {
    gone.current = false;
    return () => {
      gone.current = true;
      current.current?.abort();
    };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return useMemo(
    () => ({
      begin() {
        const controller = new AbortController();
        current.current = controller;
        return controller;
      },
      stop: () => current.current?.abort(),
      // True when this request was still the current one, which is then released.
      finish(controller: AbortController) {
        if (current.current !== controller) return false;
        current.current = null;
        return true;
      },
      busy: () => current.current !== null,
      gone: () => gone.current,
    }),
    [],
  );
}

export const streamErrorText = (err: unknown) => (err instanceof ApiError ? tm(err.msg) : String((err as Error)?.message ?? err));
