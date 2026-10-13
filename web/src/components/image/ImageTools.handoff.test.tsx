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
    if (url === '/api/image/tools/items') return { items };
    if (url === '/api/image/tools/methods') return { methods: ['local'], features: {} };
    if (url.includes('/analyze')) return { item: items.find(i => url.endsWith(i.id)), prompt: { source: '', positive: '', negative: '', settings: {} }, text_keys: [], exif: {} };
    return { available: false };
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    sendToTools('first');
    await act(async () => { root.render(<QueryClientProvider client={qc}><ImageTools openLab={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    expect(host.querySelector('.tools-card.current')?.getAttribute('title')).toContain('first');
    expect((host.querySelector('.tools-card.current input') as HTMLInputElement).checked).toBe(true);
    expect([...host.querySelectorAll('button')].find(b => b.textContent === t('tools.tab.censor'))?.className).toContain('on');
    await act(async () => sendToTools('second'));
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    expect(host.querySelector('.tools-card.current')?.getAttribute('title')).toContain('second');
    expect((host.querySelector('.tools-card.current input') as HTMLInputElement).checked).toBe(true);
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});
