// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, put } from '../api';
import { t } from '../i18n';
import RelationsTab from './RelationsTab';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), get: vi.fn(), put: vi.fn() }));
vi.mock('./RunLlmSelector', () => ({ default: () => null }));
vi.mock('@xyflow/react', async (original) => ({ ...await original<typeof import('@xyflow/react')>(), ReactFlow: () => null }));
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
const initial = { people: [{ id: 'N01', name: 'Original' }], relations: [], facts: [], layout: {}, view: [], revision: 'r0' };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}
const advance = (ms = 1) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find((el) => el.textContent?.trim() === label);
  expect(button).toBeTruthy();
  await act(async () => button!.click());
}
async function edit(value: string) {
  const input = host.querySelector('input[placeholder="' + t('relations.name') + '"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
function name() { return (host.querySelector('input[placeholder="' + t('relations.name') + '"]') as HTMLInputElement).value; }

beforeEach(async () => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['relations', 'work'], initial);
  vi.mocked(get).mockResolvedValue(initial);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><RelationsTab workId="work" openItem={() => {}} /></QueryClientProvider>));
  await click(t('relations.table'));
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  vi.useRealTimers();
});

it.each([100, 700])('preserves edits during a delayed save and serializes them (next debounce %i ms)', async (delay) => {
  const first = deferred<typeof initial>();
  vi.mocked(put).mockReturnValueOnce(first.promise).mockImplementation(async (_, body) => ({ ...(body as typeof initial), revision: 'r2' }));
  await edit('A');
  await advance(600);
  expect(put).toHaveBeenCalledTimes(1);
  await edit('B');
  await advance(delay);
  expect(put).toHaveBeenCalledTimes(1);
  await act(async () => first.resolve({ ...initial, people: [{ id: 'N01', name: 'A' }], revision: 'r1' }));
  await advance(1);
  expect(name()).toBe('B');
  await advance(600);
  expect(put).toHaveBeenCalledTimes(2);
  expect(put).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ people: [{ id: 'N01', name: 'B' }], revision: 'r1' }));
  expect(name()).toBe('B');
  expect(qc.getQueryData(['relations', 'work'])).toMatchObject({ revision: 'r2' });
});

it.each([500, 409])('keeps input after status %i and offers a retry', async (status) => {
  vi.mocked(put).mockRejectedValueOnce(new ApiError(status, { key: 'failure', text: 'Failed' }))
    .mockImplementation(async (_, body) => ({ ...(body as typeof initial), revision: 'r1' }));
  await edit('B');
  await advance(600);
  expect(name()).toBe('B');
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  await act(async () => qc.setQueryData(['relations', 'work'], { ...initial, revision: 'external' }));
  await advance();
  expect(name()).toBe('B');
  await click(t('common.save'));
  await advance();
  expect(put).toHaveBeenCalledTimes(2);
  expect(put).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ revision: 'r0' }));
  expect(name()).toBe('B');
  expect(host.querySelector('[role="alert"]')).toBeNull();
});

