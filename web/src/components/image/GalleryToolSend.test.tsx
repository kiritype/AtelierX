// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import GalleryToolSend from './GalleryToolSend';
import { ApiError, post } from '../../api';
import { takeToolHandoff } from '../../lib/toolHandoff';
import { t } from '../../i18n';
import type { GenerationRecord } from '../../imageTypes';
const { toast } = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock('../Toasts', () => ({ useToast: () => toast }));
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), post: vi.fn() }));
let host: HTMLDivElement, root: Root, qc: QueryClient;
const open = vi.fn();
beforeEach(() => {
  vi.clearAllMocks(); takeToolHandoff();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); qc.clear(); });
async function render(record?: GenerationRecord, shortcut = false) {
  await act(async () => root.render(<QueryClientProvider client={qc}><GalleryToolSend path="image_censor.png" record={record} openTools={open} shortcut={shortcut} /></QueryClientProvider>));
}
async function send() { await act(async () => host.querySelector('button')!.click()); }
it('sends the recorded source by default and selects an existing item only when the toast is followed', async () => {
  vi.mocked(post).mockResolvedValue({ ok: true, added: [], items: [{ id: 'existing', path: 'source.png' }] });
  await render({ postprocessing: { op: 'censor', source_image: 'source_censor.png', previous: { op: 'censor', source_image: 'source.png' } } });
  await send();
  expect(post).toHaveBeenCalledWith('/api/image/tools/gallery', { paths: ['source.png'] });
  expect(open).not.toHaveBeenCalled();
  expect(toast.mock.calls[0][0].text).toBe(t('gallery.already_in_tools'));
  toast.mock.calls[0][0].action.run();
  expect(takeToolHandoff()).toBe('existing'); expect(open).toHaveBeenCalledOnce();
});
it('allows sending the current censored image instead of its source', async () => {
  vi.mocked(post).mockResolvedValue({ ok: true, added: [{ id: 'new' }], items: [{ id: 'new' }] });
  await render({ op: 'censor', source: { source: 'gallery', path: 'source.png' } });
  await act(async () => host.querySelector('input')!.click()); await send();
  expect(post).toHaveBeenCalledWith('/api/image/tools/gallery', { paths: ['image_censor.png'] });
});
it('reports that an archived gallery image was restored', async () => {
  vi.mocked(post).mockResolvedValue({ ok: true, added: [], restored: 1, items: [{ id: 'existing', path: 'image_censor.png' }] });
  await render(); await send();
  expect(toast.mock.calls[0][0].text).toBe(t('gallery.restored_in_tools'));
});
it('reports a full list in the selected language without navigating', async () => {
  vi.mocked(post).mockRejectedValue(new ApiError(400, { key: 'server.workspace.the_image_tools_list_holds_up', text: 'Full', values: { max_items: 2000 } }));
  await render(); await send();
  expect(toast.mock.calls[0][0].tone).toBe('error'); expect(open).not.toHaveBeenCalled();
  expect(host.textContent).toContain(t('gallery.original_unknown'));
});
it('uses 4 for the selected source but ignores typing, modifiers, repeats and duplicate sends', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(post).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await render({ op: 'censor', source: { source: 'gallery', path: 'source.png' } }, true);
  const field = document.createElement('textarea'); host.append(field);
  await act(async () => {
    field.dispatchEvent(new KeyboardEvent('keydown', { key: '4', bubbles: true }));
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '4', ctrlKey: true }));
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '4', repeat: true }));
  });
  expect(post).not.toHaveBeenCalled();
  await act(async () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '4' }));
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '4' }));
  });
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith('/api/image/tools/gallery', { paths: ['source.png'] });
  await act(async () => finish({ added: [], items: [{ id: 'existing' }] }));
  expect(host.querySelector('button')?.getAttribute('aria-keyshortcuts')).toBe('4');
});
