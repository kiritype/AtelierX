// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { get } from '../api';
import { useUnsaved } from '../components/Unsaved';
import { t } from '../i18n';
import GlobalToolsWindow from './GlobalToolsWindow';
import WorkSelect from './WorkSelect';
import WorkWindow from './WorkWindow';

vi.mock('./TestScreen', () => ({ default: () => null }));
vi.mock('../events', () => ({ useServerEvents: vi.fn() }));
vi.mock('../api', async original => ({ ...await original<typeof import('../api')>(), get: vi.fn() }));
vi.mock('../components/AppSettings', () => ({ default: ({ request }: { request?: { section: string } }) => {
  const [dirty, setDirty] = useState(false);
  useUnsaved('test-settings', dirty);
  return <button data-section={request?.section ?? 'general'} onClick={() => setDirty(true)}>Edit settings</button>;
} }));
vi.mock('../components/image/StyleExplorer', () => ({ default: ({ openSettings }: { openSettings: () => void }) =>
  <button onClick={openSettings}>Image connection settings</button>,
}));

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

it('opens all app settings and image destinations before a work is selected', async () => {
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/works') return { works: [] };
    if (url === '/api/ui-state') return {};
    return {};
  });
  const openTools = vi.fn();
  const openWork = vi.fn();
  const host = await render(<WorkSelect onOpen={openWork} onOpenTools={openTools} onLock={vi.fn()} />);
  const settings = [...host.querySelectorAll('button')].find(button => button.textContent?.trim() === t('works.app_settings'))!;
  await act(async () => settings.click());
  expect(openTools).toHaveBeenLastCalledWith('settings');
  const single = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === t('works.image_only'))!;
  await act(async () => single.click());
  expect(openTools).toHaveBeenLastCalledWith('single');
  const image = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === t('menu.image'))!;
  for (const view of ['single', 'explorer', 'presets', 'queue']) {
    await act(async () => image.click());
    const item = [...host.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(button => button.textContent === t(`image_menu.${view}`))!;
    await act(async () => item.click());
    expect(openTools).toHaveBeenLastCalledWith(view);
  }
  expect(openWork).not.toHaveBeenCalled();
});

it('moves keyboard focus through the image menu and returns it on Escape', async () => {
  vi.mocked(get).mockImplementation(async url => url === '/api/works' ? { works: [] } : {});
  const openTools = vi.fn();
  const host = await render(<WorkSelect onOpen={vi.fn()} onOpenTools={openTools} onLock={vi.fn()} />);
  const trigger = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === t('menu.image'))!;
  trigger.focus();
  const press = async (key: string) => act(async () => {
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });
  await press('ArrowDown');
  expect(trigger.getAttribute('aria-expanded')).toBe('true');
  expect(document.activeElement?.textContent).toBe(t('image_menu.single'));
  await press('ArrowDown');
  expect(document.activeElement?.textContent).toBe(t('image_menu.explorer'));
  await press('Escape');
  expect(trigger.getAttribute('aria-expanded')).toBe('false');
  expect(document.activeElement).toBe(trigger);
  expect(openTools).not.toHaveBeenCalled();
});

it('starts app settings in General, opens image settings from a tool, and guards pending settings changes', async () => {
  const close = vi.fn();
  const confirm = vi.fn(() => false);
  vi.stubGlobal('confirm', confirm);
  try {
    const host = await render(<GlobalToolsWindow initialView="settings" onClose={close} />);
    const findButton = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === label)!;
    expect(host.querySelector('[data-section]')?.getAttribute('data-section')).toBe('general');
    await act(async () => findButton('Edit settings').click());
    await act(async () => findButton(t('image_menu.explorer')).click());
    await act(async () => findButton('Image connection settings').click());
    expect(host.querySelector('[data-section]')?.getAttribute('data-section')).toBe('image');
    await act(async () => findButton(t('tools.back')).click());
    expect(confirm).toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await act(async () => findButton(t('tools.back')).click());
    expect(close).toHaveBeenCalledOnce();
  } finally {
    vi.unstubAllGlobals();
  }
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
