// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { post } from '../../api';
import { t } from '../../i18n';
import { PresetModelBadge, PresetModelsContent } from './PresetModels';
import type { PresetModelCheck } from '../../imageTypes';

vi.mock('../../api', () => ({ post: vi.fn(), get: vi.fn(), ApiError: class extends Error {} }));
let host: HTMLDivElement, root: Root, qc: QueryClient;
const reply: PresetModelCheck = { token: 'test', connected: true, local: true, has_key: true, items: [
  { id: 'file', kind: 'lora', name: 'Ink', size: 1048576, status: 'missing', downloadable: true,
    presets: [{ id: 'one', name: 'First' }, { id: 'two', name: 'Second' }], civitai: null, version: 'v2', license: null, candidates: [] },
] };
const button = (key: string) => [...host.querySelectorAll('button')].find(b => b.textContent === t(key))!;
beforeEach(async () => {
  vi.useFakeTimers(); vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.mocked(post).mockResolvedValue(reply);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><PresetModelsContent ids={['one', 'two']} /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.useRealTimers(); });
it('starts with no selections and queues only selected dependency ids', async () => {
  expect(post).not.toHaveBeenCalled();
  await act(async () => { button('preset_models.check').click(); await vi.advanceTimersByTimeAsync(1); });
  const checkbox = host.querySelector('input[type="checkbox"]') as HTMLInputElement;
  expect(checkbox.checked).toBe(false);
  expect(button('preset_models.download').disabled).toBe(true);
  await act(async () => checkbox.click());
  expect(host.textContent).toContain(t('preset_models.selected', { n: 1, size: '1.0 MB' }));
  await act(async () => button('preset_models.download').click());
  expect(post).toHaveBeenCalledWith('/api/image/presets/resources/download', { token: 'test', selected: ['file'] });
});
it('select-all excludes files unavailable for automatic download', async () => {
  vi.mocked(post).mockResolvedValue({ ...reply, items: [...reply.items, { ...reply.items[0], id: 'unknown', name: 'Unknown', downloadable: false, status: 'unverified' }] });
  await act(async () => { button('preset_models.check').click(); await vi.advanceTimersByTimeAsync(1); });
  await act(async () => button('preset_models.select_all').click());
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].map(i => i.checked)).toEqual([true, false]);
});
it('updates preset status after the download dialog has unmounted', async () => {
  vi.mocked(post).mockResolvedValue({ ...reply, items: reply.items.map(i => ({ ...i, status: 'running', downloadable: false })) });
  await act(async () => { button('preset_models.check').click(); await vi.advanceTimersByTimeAsync(1); });
  await act(async () => root.render(<QueryClientProvider client={qc}><PresetModelBadge id="one" /></QueryClientProvider>));
  expect(host.textContent).toContain(t('preset_models.state.running'));
  vi.mocked(post).mockResolvedValue({ ...reply, items: reply.items.map(i => ({ ...i, status: 'ready', downloadable: false })) });
  await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
  expect(host.textContent).toContain(t('preset_models.state.ready'));
  expect(host.textContent).not.toContain(t('preset_models.state.running'));
});
