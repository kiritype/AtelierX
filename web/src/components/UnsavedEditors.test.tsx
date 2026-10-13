// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, patch, put } from '../api';
import { t } from '../i18n';
import { UnsavedRegistry } from '../lib/unsaved';
import { TabScope } from './Unsaved';
import GlossaryTab from './GlossaryTab';
import RelationsTab from './RelationsTab';
import WorkSettings from './WorkSettings';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), get: vi.fn(), put: vi.fn(), patch: vi.fn() }));
vi.mock('./RunLlmSelector', () => ({ default: () => null }));
vi.mock('@xyflow/react', async (original) => ({ ...await original<typeof import('@xyflow/react')>(), ReactFlow: () => null }));
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
let registry: UnsavedRegistry;
const relation = { people: [{ id: 'N01', name: 'Original' }], relations: [], facts: [], layout: {}, view: [], revision: 'r0' };
type Screen = 'glossary' | 'relations' | 'settings';
const advance = (ms = 1) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}
async function mount(screen: Screen) {
  await act(async () => root.render(<QueryClientProvider client={qc}><TabScope registry={registry} tab="tab">
    {screen === 'glossary' ? <GlossaryTab workId="work" /> : screen === 'relations' ? <RelationsTab workId="work" openItem={() => {}} /> :
      <WorkSettings workId="work" info={{ name: 'Test', doc: { scale: 'single', language: 'ko', char: 'C001' }, presets: [], effective: { linked: [], sources: {}, values: {} } }} />}
  </TabScope></QueryClientProvider>));
  if (screen === 'relations') await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === t('relations.table'))!.click());
}
function input(screen: Screen) {
  return host.querySelector(screen === 'glossary' ? 'tbody input' : screen === 'relations' ? 'input[placeholder="' + t('relations.name') + '"]' : 'input[placeholder="C001"]') as HTMLInputElement;
}
async function edit(screen: Screen, value = 'New') {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input(screen), value);
    input(screen).dispatchEvent(new Event('input', { bubbles: true }));
  });
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  registry = new UnsavedRegistry();
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['relations', 'work'], relation);
  qc.setQueryData(['glossary', 'work'], { terms: [{ use: 'Original', avoid: [], note: '' }], revision: 'r0' });
  vi.mocked(get).mockResolvedValue({});
  vi.mocked(put).mockImplementation(async (_, body) => ({ ...(body as object), revision: 'r1' }));
  vi.mocked(patch).mockResolvedValue({});
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  vi.useRealTimers();
});

it.each<Screen>(['glossary', 'relations', 'settings'])('registers %s immediately and saves before the close/leave/lock guard proceeds', async (screen) => {
  await mount(screen);
  expect(registry.dirty('tab')).toBe(false);
  await edit(screen);
  expect(registry.dirtyTabs(['tab'])).toEqual(['tab']);
  expect(registry.canSave('tab')).toBe(true);
  expect(put).not.toHaveBeenCalled();
  expect(patch).not.toHaveBeenCalled();
  let result = false;
  await act(async () => { result = await registry.save('tab'); });
  expect(result).toBe(true);
  expect(registry.dirty('tab')).toBe(false);
  expect(screen === 'settings' ? patch : put).toHaveBeenCalledTimes(1);
});

it.each<Screen>(['glossary', 'relations', 'settings'])('keeps %s open with its input on a failed save, then permits retry', async (screen) => {
  await mount(screen);
  await edit(screen);
  const api = screen === 'settings' ? patch : put;
  vi.mocked(api).mockRejectedValueOnce(new ApiError(500, { key: 'failure', text: 'Failed' }));
  let result = true;
  await act(async () => { result = await registry.save('tab'); });
  expect(result).toBe(false);
  expect(registry.dirty('tab')).toBe(true);
  expect(input(screen).value).toBe('New');
  await act(async () => { result = await registry.save('tab'); });
  expect(result).toBe(true);
  expect(registry.dirty('tab')).toBe(false);
});

it.each<Screen>(['glossary', 'relations'])('waits for an in-flight %s save and flushes the subsequent edit before close', async (screen) => {
  await mount(screen);
  const pending = deferred<object>();
  vi.mocked(put).mockReturnValueOnce(pending.promise);
  await edit(screen, 'A');
  await advance(600);
  await edit(screen, 'B');
  let completed = false;
  let close!: Promise<boolean>;
  await act(async () => { close = registry.save('tab').then((ok) => { completed = true; return ok; }); });
  expect(completed).toBe(false);
  expect(registry.dirty('tab')).toBe(true);
  await act(async () => {
    pending.resolve(screen === 'relations' ? { ...relation, people: [{ id: 'N01', name: 'A' }], revision: 'r1' } : { revision: 'r1' });
    expect(await close).toBe(true);
  });
  expect(put).toHaveBeenCalledTimes(2);
  expect(put).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining(screen === 'relations' ? { revision: 'r1' } : { base_revision: 'r1' }));
  expect(input(screen).value).toBe('B');
  expect(registry.dirty('tab')).toBe(false);
});

it('does not mark settings edited during a save as clean', async () => {
  await mount('settings');
  await edit('settings', 'A');
  const pending = deferred<object>();
  vi.mocked(patch).mockReturnValueOnce(pending.promise);
  let close!: Promise<boolean>;
  await act(async () => { close = registry.save('tab'); });
  await edit('settings', 'B');
  await act(async () => { pending.resolve({}); expect(await close).toBe(false); });
  expect(registry.dirty('tab')).toBe(true);
  expect(input('settings').value).toBe('B');
  await act(async () => { expect(await registry.save('tab')).toBe(true); });
  expect(patch).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ char: 'B' }));
});

it.each<Screen>(['glossary', 'relations'])('refuses to close %s if another edit arrives during the final flush', async (screen) => {
  await mount(screen);
  await edit(screen, 'A');
  const pending = deferred<object>();
  vi.mocked(put).mockReturnValueOnce(pending.promise);
  let close!: Promise<boolean>;
  await act(async () => { close = registry.save('tab'); });
  await edit(screen, 'B');
  await act(async () => {
    pending.resolve(screen === 'relations' ? { ...relation, revision: 'r1' } : { revision: 'r1' });
    expect(await close).toBe(false);
  });
  expect(registry.dirty('tab')).toBe(true);
  expect(input(screen).value).toBe('B');
  await act(async () => { expect(await registry.save('tab')).toBe(true); });
});

it.each<Screen>(['glossary', 'relations'])('does not save discarded newer input after an in-flight %s request finishes', async (screen) => {
  await mount(screen);
  const pending = deferred<object>();
  vi.mocked(put).mockReturnValueOnce(pending.promise);
  await edit(screen, 'A');
  await advance(600);
  await edit(screen, 'B');
  await advance(600); // The second write is already queued behind the first.
  await act(async () => root.render(null));
  await act(async () => pending.resolve(screen === 'relations' ? { ...relation, revision: 'r1' } : { revision: 'r1' }));
  await advance(1000);
  expect(put).toHaveBeenCalledTimes(1);
  expect(registry.dirty('tab')).toBe(false);
});

it.each<Screen>(['glossary', 'relations'])('discards pending %s debounce only after its tab is actually unmounted', async (screen) => {
  await mount(screen);
  await edit(screen);
  await act(async () => root.render(null));
  await advance(1000);
  expect(put).not.toHaveBeenCalled();
  expect(registry.dirty('tab')).toBe(false);
});

