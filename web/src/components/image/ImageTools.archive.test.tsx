// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import ImageTools from './ImageTools';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));

it('archives selected images and restores them from the persistent archive view', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const all = ['first', 'second'].map(id => ({ id, name: id, source: 'gallery', path: id + '.png', width: 10, height: 10, format: 'PNG' }));
  const archived = new Set<string>();
  vi.mocked(get).mockImplementation(async url => {
    if (url.startsWith('/api/image/tools/items')) {
      const view = url.includes('archived=1');
      const items = all.filter(item => archived.has(item.id) === view);
      return { items, total: items.length, archived_total: archived.size };
    }
    if (url.startsWith('/api/image/tools/ids')) return { ids: all.filter(item => archived.has(item.id) === url.includes('archived=1')).map(item => item.id) };
    if (url === '/api/image/tools/batches') return { batches: [] };
    if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
    if (url.includes('/analyze')) return { item: all.find(item => url.endsWith(item.id)), prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
    return { available: false };
  });
  vi.mocked(post).mockImplementation(async (url, body) => {
    if (url === '/api/image/tools/archive') {
      const change = body as { ids: string[]; archived: boolean };
      change.ids.forEach(id => change.archived ? archived.add(id) : archived.delete(id));
      return { ok: true };
    }
    throw new Error('Unexpected API call');
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
  const firstCard = () => [...host.querySelectorAll('.tools-card')].find(card => card.getAttribute('title')?.startsWith('first'));
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ImageTools openLab={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    await act(async () => (firstCard()!.querySelector('input') as HTMLInputElement).click());
    await act(async () => button(t('tools.archive_selected')).click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(archived.has('first')).toBe(true);
    expect(firstCard()).toBeUndefined();
    await act(async () => button(t('tools.show_archived', { n: 1 })).click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(firstCard()?.textContent).toContain(t('tools.archived'));
    await act(async () => (firstCard()!.querySelector('input') as HTMLInputElement).click());
    await act(async () => button(t('tools.restore_archived')).click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(archived.has('first')).toBe(false);
    expect(firstCard()).toBeUndefined();
    await act(async () => button(t('tools.show_active')).click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(firstCard()).toBeDefined();
    expect(vi.mocked(post)).toHaveBeenCalledTimes(2);
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});

it('ignores a select-all response from the previous view', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  let resolveIds!: (value: { ids: string[] }) => void;
  const item = { id: 'first', name: 'first', source: 'gallery', path: 'first.png', width: 10, height: 10, format: 'PNG' };
  vi.mocked(get).mockImplementation(async url => {
    if (url.startsWith('/api/image/tools/ids')) return new Promise(resolve => { resolveIds = resolve; });
    if (url.startsWith('/api/image/tools/items')) return { items: url.includes('archived=1') ? [] : [item], total: url.includes('archived=1') ? 0 : 1, archived_total: 0 };
    if (url === '/api/image/tools/batches') return { batches: [] };
    if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
    if (url.includes('/analyze')) return { item, prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
    return { available: false };
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ImageTools openLab={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    await act(async () => button(t('tools.select_all')).click());
    await act(async () => button(t('tools.show_archived', { n: 0 })).click());
    await act(async () => resolveIds({ ids: ['first'] }));
    expect(button(t('tools.select_all'))).toBeDefined();
    expect(button(t('tools.restore_archived')).hasAttribute('disabled')).toBe(true);
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});

it('returns to the last valid page after archiving its only image', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const all = Array.from({ length: 201 }, (_, i) => ({ id: String(i), name: String(i), source: 'gallery', path: `${i}.png`, width: 10, height: 10, format: 'PNG' }));
  const archived = new Set<string>();
  vi.mocked(get).mockImplementation(async url => {
    if (url.startsWith('/api/image/tools/items')) {
      const offset = Number(new URL(url, 'http://local').searchParams.get('offset'));
      const active = all.filter(item => !archived.has(item.id));
      return { items: active.slice(offset, offset + 200), total: active.length, archived_total: archived.size };
    }
    if (url === '/api/image/tools/batches') return { batches: [] };
    if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
    if (url.includes('/analyze')) return { item: all.find(item => url.endsWith(item.id)), prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
    return { available: false };
  });
  vi.mocked(post).mockImplementation(async (_, body) => {
    (body as { ids: string[] }).ids.forEach(id => archived.add(id));
    return { ok: true };
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ImageTools openLab={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    await act(async () => button(t('bulk.next')).click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    const only = host.querySelector('.tools-card input') as HTMLInputElement;
    await act(async () => only.click());
    await act(async () => button(t('tools.archive_selected')).click());
    for (let attempt = 0; attempt < 10 && !host.textContent?.includes('1–200 / 200'); attempt++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    }
    expect(archived.has('200')).toBe(true);
    expect(host.textContent).toContain('1–200 / 200');
    expect(host.textContent).not.toContain('201–200');
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});

it('returns to the work list after an upload from archived view', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const items: { id: string; name: string; source: string; path: string; width: number; height: number; format: string }[] = [];
  vi.mocked(get).mockImplementation(async url => {
    if (url.startsWith('/api/image/tools/items')) return { items: url.includes('archived=1') ? [] : items, total: url.includes('archived=1') ? 0 : items.length, archived_total: 0 };
    if (url === '/api/image/tools/batches') return { batches: [] };
    if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
    if (url.includes('/analyze')) return { item: items[0], prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
    return { available: false };
  });
  const previousFetch = globalThis.fetch;
  globalThis.fetch = vi.fn(async () => {
    items.push({ id: 'uploaded', name: 'uploaded', source: 'upload', path: 'uploaded.png', width: 10, height: 10, format: 'PNG' });
    return { ok: true, json: async () => ({ added: [{ id: 'uploaded' }], skipped: [] }) } as Response;
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ImageTools openLab={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    await act(async () => button(t('tools.show_archived', { n: 0 })).click());
    const event = new Event('drop', { bubbles: true });
    Object.defineProperty(event, 'dataTransfer', { value: { files: [new File(['image'], 'uploaded.png', { type: 'image/png' })] } });
    await act(async () => host.querySelector('.tools-list')!.dispatchEvent(event));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(button(t('tools.show_archived', { n: 0 }))).toBeDefined();
    expect(host.querySelector('.tools-card')?.getAttribute('title')).toContain('uploaded');
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); globalThis.fetch = previousFetch; }
});
