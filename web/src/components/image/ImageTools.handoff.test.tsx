// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { it, expect, vi } from 'vitest';
import ImageTools from './ImageTools';
import { get } from '../../api';
import { sendToTools, takeToolHandoff } from '../../lib/toolHandoff';
import { t } from '../../i18n';
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn() }));
it('selects the handed image and censor tab before mount and while already open', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  takeToolHandoff();
  const items = ['first', 'second'].map(id => ({ id, name: id, source: 'gallery', path: id + '.png', width: 10, height: 10, format: 'PNG' }));
  vi.mocked(get).mockImplementation(async url => {
    if (url.startsWith('/api/image/tools/items')) return { items };
    if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
    if (url.includes('/analyze')) return { item: items.find(i => url.endsWith(i.id)), prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
    return { available: false };
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const render = (active: boolean) => <QueryClientProvider client={qc}>
    <div data-hidden><ImageTools active={false} openLab={() => {}} /></div>
    <div data-target><ImageTools active={active} openLab={() => {}} /></div>
  </QueryClientProvider>;
  try {
    await act(async () => { root.render(render(false)); });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    sendToTools('first');
    await act(async () => { root.render(render(true)); });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    const target = host.querySelector('[data-target]')!;
    expect(host.querySelector('[data-hidden] .tools-card.current')?.getAttribute('title')).toContain('second');
    expect(target.querySelector('.tools-card.current')?.getAttribute('title')).toContain('first');
    expect((target.querySelector('.tools-card.current input') as HTMLInputElement).checked).toBe(true);
    expect([...target.querySelectorAll('button')].find(b => b.textContent === t('tools.tab.censor'))?.className).toContain('on');
    await act(async () => sendToTools('second'));
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    expect(target.querySelector('.tools-card.current')?.getAttribute('title')).toContain('second');
    expect((target.querySelector('.tools-card.current input') as HTMLInputElement).checked).toBe(true);
    const later = { ...items[0], id: 'page-two', name: 'page-two', path: 'page-two.png' };
    vi.mocked(get).mockImplementation(async url => {
      if (url.startsWith('/api/image/tools/items')) return { items: url.includes('offset=200') ? [later] : items, total: 201 };
      if (url === '/api/image/tools/ids') return { ids: [...Array.from({ length: 200 }, (_, i) => String(i)), later.id] };
      if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
      if (url.includes('/analyze')) return { item: later, prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
      return { available: false };
    });
    await act(async () => sendToTools(later.id));
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    expect(vi.mocked(get).mock.calls.some(([url]) => url.includes('/tools/items?offset=200'))).toBe(true);
    expect(target.querySelector('.tools-card.current')?.getAttribute('title')).toContain('page-two');
    expect((target.querySelector('.tools-card.current input') as HTMLInputElement).checked).toBe(true);
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});
