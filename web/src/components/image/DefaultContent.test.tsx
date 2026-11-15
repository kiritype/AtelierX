// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import DefaultContent from './DefaultContent';
import type { ContentPreview } from '../../imageTypes';

vi.mock('../../api', () => ({ get: vi.fn(), post: vi.fn(), ApiError: class extends Error {} }));
const pack = { id: 'default', kind: 'presets' as const, title: 'Styles', description: '', version: '1', min_app_version: '0.0.0', compatible: true, author: 'Example', license: 'CC0' };
const look: ContentPreview = { token: 'preview', pack, items: ['new', 'same', 'modified'].map((state, i) => ({ key: `presets:${i}`, id: String(i), kind: 'presets', name: state, group: '', state: state as 'new' | 'same' | 'modified', before: state === 'new' ? null : { name: 'local' }, after: { name: state }, dependencies: [], preview_url: null })) };
let host: HTMLDivElement, root: Root, qc: QueryClient;
const button = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label)!;
beforeEach(async () => {
  vi.useFakeTimers(); vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.mocked(get).mockImplementation(async url => url.endsWith('/status') ? { configured: true, installed: [] } : { packs: [pack] });
  vi.mocked(post).mockImplementation(async url => url.endsWith('/preview') ? look : { written: ['0'], kind: 'presets', version: '1' });
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><DefaultContent /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.useRealTimers(); });
it('selects new items, keeps edits, and continues to models in the same dialog without starting downloads', async () => {
  await act(async () => button(t('content.presets.button')).click());
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
  expect(host.querySelector<HTMLSelectElement>('select')?.value).toBe('skip');
  await act(async () => button(t('content.import_selected', { n: 1 })).click());
  expect(post).toHaveBeenCalledWith('/api/image/content/import', { token: 'preview', choices: { 'presets:0': 'add', 'presets:1': 'skip', 'presets:2': 'skip' } });
  expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);
  expect(host.querySelector('[role="dialog"]')?.contains(document.activeElement)).toBe(true);
  expect(button(t('preset_models.check'))).toBeDefined();
  expect(vi.mocked(post).mock.calls.some(([url]) => url.includes('/resources/'))).toBe(false);
});
it('supports Escape and restores focus to the original import button', async () => {
  const opener = button(t('content.presets.button'));
  await act(async () => { opener.focus(); opener.click(); });
  const dialog = host.querySelector('[role="dialog"]')!;
  expect(dialog.getAttribute('aria-modal')).toBe('true');
  await act(async () => dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(opener);
});
it('shows a retry after a catalog failure without writing content', async () => {
  vi.mocked(get).mockRejectedValueOnce(new Error('Offline'));
  await act(async () => button(t('content.presets.button')).click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('Offline');
  expect(post).not.toHaveBeenCalled();
  vi.mocked(get).mockResolvedValue({ packs: [pack] });
  await act(async () => button(t('content.retry')).click());
  expect(host.querySelector('input[type="checkbox"]')).not.toBeNull();
});
