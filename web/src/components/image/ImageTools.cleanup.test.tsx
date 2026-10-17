// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import ImageTools from './ImageTools';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));

it('hides and restores a workspace image without deleting its file', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.removeItem('atelierx.tools.hidden');
  const items = ['first', 'second'].map(id => ({ id, name: id, source: 'gallery', path: id + '.png', width: 10, height: 10, format: 'PNG' }));
  vi.mocked(get).mockImplementation(async url => {
    if (url.startsWith('/api/image/tools/items')) return { items, total: 2 };
    if (url === '/api/image/tools/batches') return { batches: [] };
    if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
    if (url.includes('/analyze')) return { item: items.find(item => url.endsWith(item.id)), prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
    return { available: false };
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ImageTools openLab={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    const firstCard = () => [...host.querySelectorAll('.tools-card')].find(card => card.getAttribute('title')?.startsWith('first'));
    await act(async () => (firstCard()!.querySelector('input') as HTMLInputElement).click());
    await act(async () => button(t('tools.hide_from_workspace')).click());
    expect(firstCard()).toBeUndefined();
    expect(JSON.parse(localStorage.getItem('atelierx.tools.hidden') || '[]')).toContain('first');
    expect(vi.mocked(post)).not.toHaveBeenCalled();
    await act(async () => button(t('tools.show_hidden', { n: 1 })).click());
    expect(firstCard()?.textContent).toContain(t('tools.hidden'));
    await act(async () => (firstCard()!.querySelector('input') as HTMLInputElement).click());
    await act(async () => button(t('tools.restore_hidden')).click());
    expect(JSON.parse(localStorage.getItem('atelierx.tools.hidden') || '[]')).not.toContain('first');
    expect(vi.mocked(post)).not.toHaveBeenCalled();
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});
