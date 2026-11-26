// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, post, put } from '../api';
import { t } from '../i18n';
import type { WorkCovers } from '../types';
import WorkCoverSettings from './WorkCoverSettings';

vi.mock('../api', async (original) => ({
  ...await original<typeof import('../api')>(), get: vi.fn(), post: vi.fn(), put: vi.fn(),
}));
vi.mock('./Toasts', () => ({ useToast: () => vi.fn() }));

const endpoint = '/api/works/W001/covers';
const cover = (id: string) => ({ id, name: id + '.png', url: endpoint + '/' + id });
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
let state: WorkCovers;

const wait = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); });
const click = async (button: HTMLButtonElement) => {
  await act(async () => button.click());
  await wait();
};
const button = (text: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === text)!;
const labelled = (text: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(item => item.getAttribute('aria-label') === text)!;
const itemNames = () => [...host.querySelectorAll('.work-cover-row .grow')].map(item => item.textContent);

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  state = { items: [cover('A'), cover('B')], primary_id: 'A', revision: 'r0' };
  vi.mocked(get).mockImplementation(async (url) => {
    if (url === endpoint) return state;
    const query = new URL(String(url), 'http://localhost');
    if (query.pathname === '/api/image/gallery' && query.searchParams.get('library_work') === 'W001') {
      return { results: [{ path: 'W001/C001/images/o01/smile/gallery.png', filename: 'gallery.png', thumbnail_url: '/gallery.png' }], pages: 1 };
    }
    throw new Error(String(url));
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  vi.resetAllMocks();
});

async function renderCovers() {
  await act(async () => root.render(<QueryClientProvider client={qc}><WorkCoverSettings workId="W001" /></QueryClientProvider>));
  await wait();
}

it('saves representative and ordering changes and promotes the first remaining image on deletion', async () => {
  let revision = 0;
  vi.mocked(put).mockImplementation(async (_, value) => {
    const change = value as { ids: string[]; primary_id: string | null; base_revision: string };
    expect(change.base_revision).toBe(state.revision);
    state = { items: change.ids.map(cover), primary_id: change.primary_id, revision: 'r' + ++revision };
    return state;
  });
  await renderCovers();
  expect(itemNames()).toEqual(['A.png', 'B.png']);

  await click(button(t('work_covers.make_primary')));
  expect(state.primary_id).toBe('B');
  await click(labelled(t('work_covers.move_up_name', { name: 'B.png' })));
  expect(itemNames()).toEqual(['B.png', 'A.png']);
  expect(state.primary_id).toBe('B');
  await click(labelled(t('work_covers.remove_name', { name: 'B.png' })));
  expect(itemNames()).toEqual(['A.png']);
  expect(state.primary_id).toBe('A');
});

it('reloads stale revisions and adds a cover from the current work gallery', async () => {
  vi.mocked(put).mockImplementationOnce(async () => {
    state = { items: [cover('A'), cover('B'), cover('C')], primary_id: 'A', revision: 'r1' };
    throw new ApiError(409, { key: 'server.save.stale', text: 'Stale' });
  });
  vi.mocked(post).mockImplementationOnce(async (_, value) => {
    expect(value).toEqual({ gallery_path: 'W001/C001/images/o01/smile/gallery.png', base_revision: 'r1' });
    state = { items: [...state.items, cover('gallery')], primary_id: 'A', revision: 'r2' };
    return state;
  });
  await renderCovers();
  await click(button(t('work_covers.make_primary')));
  expect(itemNames()).toEqual(['A.png', 'B.png', 'C.png']);

  await click(button(t('work_covers.add_gallery')));
  expect(get).toHaveBeenCalledWith('/api/image/gallery?library_work=W001&work=W001&page=1&page_size=24');
  await click(button('gallery.png'));
  expect(itemNames()).toEqual(['A.png', 'B.png', 'C.png', 'gallery.png']);
  expect(host.querySelector('.work-cover-gallery-dialog')).toBeNull();
});
