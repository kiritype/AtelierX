// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { get } from '../api';
import { t } from '../i18n';
import WorkSelect from './WorkSelect';
import WorkWindow from './WorkWindow';

vi.mock('./TestScreen', () => ({ default: () => null }));
vi.mock('../events', () => ({ useServerEvents: vi.fn() }));
vi.mock('../api', async original => ({ ...await original<typeof import('../api')>(), get: vi.fn() }));

const mounted: { root: ReturnType<typeof createRoot>; qc: QueryClient; host: HTMLElement }[] = [];
afterEach(async () => {
  for (const { root, qc, host } of mounted.splice(0)) {
    await act(async () => root.unmount());
    qc.clear();
    host.remove();
  }
  vi.clearAllMocks();
});

async function render(ui: React.ReactNode) {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  mounted.push({ root, qc, host });
  await act(async () => root.render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>));
  return host;
}

it('opens global Tools from the work list before a work is selected', async () => {
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/works') return { works: [] };
    if (url === '/api/ui-state') return {};
    return {};
  });
  const openTools = vi.fn();
  const host = await render(<WorkSelect onOpen={vi.fn()} onOpenTools={openTools} onLock={vi.fn()} />);
  const tools = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes(t('menu.tools')));
  expect(tools).toBeTruthy();
  await act(async () => tools!.click());
  const explorer = [...host.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(button => button.textContent === t('image_menu.explorer'));
  expect(explorer).toBeTruthy();
  await act(async () => explorer!.click());
  expect(openTools).toHaveBeenCalledOnce();
});

it('redirects an active legacy explorer tab and removes explorer from Image navigation', async () => {
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/works/story') return { name: 'Story', doc: {}, effective: { linked: [], values: {} }, presets: [] };
    if (url === '/api/ui-state') return { works: { story: {
      tabs: [{ type: 'item', path: 'chapter.md' }, { type: 'image', view: 'explorer' }],
      active: 'image:explorer', pinned: ['image:explorer'],
    } } };
    return [];
  });
  const openTools = vi.fn();
  const host = await render(<WorkWindow workId="story" onOpenTools={openTools} onLeave={vi.fn()} onLock={vi.fn()} />);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(openTools).toHaveBeenCalledOnce();
  expect([...host.querySelectorAll('.tab-title')].map(tab => tab.textContent)).toEqual(['chapter.md']);
  const imageMenu = [...host.querySelectorAll<HTMLButtonElement>('.menu-title')].find(button => button.textContent === t('menu.image'))!;
  await act(async () => imageMenu.click());
  expect([...host.querySelectorAll('[role="menuitem"]')].some(item => item.textContent === t('image_menu.explorer'))).toBe(false);
});

it('ignores work keyboard shortcuts while global Tools covers the work', async () => {
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/works/story') return { name: 'Story', doc: {}, effective: { linked: [], values: {} }, presets: [] };
    if (url === '/api/ui-state') return { works: {} };
    return [];
  });
  const host = await render(<WorkWindow workId="story" active={false} onLeave={vi.fn()} onLock={vi.fn()} />);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  await act(async () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', ctrlKey: true, bubbles: true }));
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F5', bubbles: true }));
  });
  expect(host.querySelector(`input[placeholder="${t('editor.quick_open_hint')}"]`)).toBeNull();
  expect(host.querySelector('.test-button.primary')).toBeNull();
});
