// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import ImageGallery, { type GalleryItem } from './ImageGallery';

vi.mock('../../api', async (original) => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));
vi.mock('../Toasts', () => ({ useToast: () => vi.fn() }));

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
let statuses: Record<string, GalleryItem['human_status']>;
let delayNext: (() => Promise<void>) | null;
let failNext: boolean;

const items = Array.from({ length: 61 }, (_, index): GalleryItem => ({
  path: `folder/${String(index).padStart(3, '0')}.png`, filename: `${index}.png`, folder: 'folder',
  kind: 'image', image_url: `/image/${index}`, thumbnail_url: `/thumb/${index}`, has_record: true,
  work_id: 'w0', character_id: 'c0', outfit_id: 'o0', expression_id: 'e0', outfit_name: 'Outfit',
  expression_name: 'Smile', rating: '', model_family: '', postprocessed: false, created_at: '', sha256: '',
  human_status: 'unreviewed', note: `note ${index}`, auto_status: 'pending', auto_reason: '', adopted: false,
}));
const annotated = (item: GalleryItem): GalleryItem => ({ ...item, human_status: statuses[item.path] ?? 'unreviewed' });
const pause = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); };
const click = async (element: HTMLElement) => { await act(async () => element.click()); await pause(); };
const currentPath = () => host.querySelector('.gallery-detail-side > .mono')?.textContent;
const nav = (direction: 'prev' | 'next') => host.querySelector<HTMLButtonElement>(`.gallery-detail .nav.${direction}`)!;

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  statuses = {}; delayNext = null; failNext = false;
  vi.mocked(get).mockImplementation(async (url) => {
    if (url === '/api/image/gallery/tree') return { works: [], folders: [], expressions: [], revision: 1 };
    if (url === '/api/image/review/rounds') return { rounds: [], enabled: false };
    if (url === '/api/works/w0/image/designs') return [];
    if (url.startsWith('/api/image/gallery/detail?')) {
      const path = new URL(url, 'http://localhost').searchParams.get('path')!;
      const item = annotated(items.find(value => value.path === path)!);
      return { ...item, record: { positive: `prompt ${path}`, settings: { model: path } }, history: [], adopted_path: null };
    }
    if (url.startsWith('/api/image/gallery?')) {
      const query = new URL(url, 'http://localhost').searchParams;
      expect(query.get('work')).toBe('w0');
      expect(query.get('sort')).toBe('oldest');
      if (query.get('direction') === 'next' && delayNext) await delayNext();
      if (query.get('direction') && failNext) { failNext = false; throw new Error('load failed'); }
      const matched = items.filter(item => !query.get('human_status') || annotated(item).human_status === query.get('human_status'));
      const anchor = query.get('anchor');
      const rank = items.findIndex(item => item.path === anchor);
      const anchorIndex = rank < 0 ? null : matched.filter(item => items.indexOf(item) < rank).length;
      const included = anchorIndex !== null && matched[anchorIndex]?.path === anchor;
      const direction = query.get('direction');
      const candidate = anchorIndex === null ? null : direction === 'prev' ? anchorIndex - 1 : direction === 'next' ? anchorIndex + Number(included) : null;
      const targetIndex = candidate !== null && candidate >= 0 && candidate < matched.length ? candidate : null;
      const page = targetIndex !== null ? Math.floor(targetIndex / 60) + 1 : anchorIndex !== null
        ? Math.floor(Math.min(anchorIndex, Math.max(0, matched.length - 1)) / 60) + 1 : Number(query.get('page') ?? 1);
      return { results: matched.slice((page - 1) * 60, page * 60).map(annotated), total: matched.length,
        page, page_size: 60, pages: Math.ceil(matched.length / 60), snapshot: '1000', newer: 0,
        anchor_index: anchorIndex, anchor_in_results: included, target_index: targetIndex };
    }
    return {};
  });
  vi.mocked(post).mockImplementation(async (url, body) => {
    if (url === '/api/image/gallery/review') {
      const review = body as { verdict: GalleryItem['human_status']; items: { path: string }[] };
      for (const item of review.items) statuses[item.path] = review.verdict;
      return { ok: true };
    }
    return {};
  });
});
afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.clearAllMocks(); });

async function renderOldestUnreviewed() {
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <ImageGallery workId="w0" openLab={() => {}} openTools={() => {}} />
  </QueryClientProvider>));
  await pause();
  const selects = host.querySelectorAll<HTMLSelectElement>('.gallery-toolbar select');
  await act(async () => { selects[1].value = 'unreviewed'; selects[1].dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => { selects[3].value = 'oldest'; selects[3].dispatchEvent(new Event('change', { bubbles: true })); });
  await pause();
}

it('navigates both ways across 60/61 boundaries and keeps the current image after filtering it out', async () => {
  await renderOldestUnreviewed();
  expect(host.querySelectorAll('.gallery-open')).toHaveLength(60);
  await click(host.querySelectorAll<HTMLButtonElement>('.gallery-open')[59]);
  expect(currentPath()).toBe(items[59].path);
  await click(nav('next'));
  expect(currentPath()).toBe(items[60].path);
  expect(host.textContent).toContain(t('gallery.position', { current: 61, total: 61 }));
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })));
  await pause();
  expect(currentPath()).toBe(items[59].path);
  const note = host.querySelector<HTMLTextAreaElement>('.gallery-detail textarea')!;
  await act(async () => note.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })));
  expect(currentPath()).toBe(items[59].path);

  const pass = [...host.querySelectorAll<HTMLButtonElement>('.gallery-detail button')]
    .find(button => button.textContent?.trim().startsWith(t('gallery.human.pass')))!;
  await click(pass);
  expect(currentPath()).toBe(items[59].path);
  expect(host.textContent).toContain(t('gallery.outside_filter'));
  expect(host.querySelector<HTMLTextAreaElement>('.gallery-detail textarea')?.value).toBe('note 59');
  expect(host.querySelector('.gallery-detail .prompt-box')?.textContent).toBe(`prompt ${items[59].path}`);
  await click(nav('next'));
  expect(currentPath()).toBe(items[60].path);
  await click(nav('prev'));
  expect(currentPath()).toBe(items[58].path);
  await click(host.querySelector<HTMLButtonElement>('.gallery-detail .ghost')!);
  expect(host.querySelector('.gallery-detail')).toBeNull();
  expect(host.querySelectorAll('.gallery-open')).toHaveLength(60);
});

it('ignores rapid navigation while loading, preserves selection on failure, and ignores a stale response after close', async () => {
  await renderOldestUnreviewed();
  await click(host.querySelectorAll<HTMLButtonElement>('.gallery-open')[59]);
  let release!: () => void;
  delayNext = () => new Promise<void>(resolve => { release = resolve; });
  await act(async () => nav('next').click());
  expect(nav('next').disabled).toBe(true);
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })));
  expect(vi.mocked(get).mock.calls.filter(([url]) => url.includes('direction=next'))).toHaveLength(1);
  await act(async () => release()); await pause();
  expect(currentPath()).toBe(items[60].path);

  failNext = true;
  await click(nav('prev'));
  expect(currentPath()).toBe(items[60].path);
  await click(nav('prev'));
  expect(currentPath()).toBe(items[59].path);

  await act(async () => nav('next').click());
  await click(host.querySelector<HTMLButtonElement>('.gallery-detail .ghost')!);
  await act(async () => release()); await pause();
  expect(host.querySelector('.gallery-detail')).toBeNull();
});

it('keeps the last-page image open when its verdict removes the last page, then closes on page one', async () => {
  await renderOldestUnreviewed();
  const nextPage = [...host.querySelectorAll<HTMLButtonElement>('.gallery-scroll button')]
    .find(button => button.textContent?.trim() === '›')!;
  await click(nextPage);
  expect(host.querySelectorAll('.gallery-open')).toHaveLength(1);
  await click(host.querySelector<HTMLButtonElement>('.gallery-open')!);
  expect(currentPath()).toBe(items[60].path);
  await click(nav('prev'));
  expect(currentPath()).toBe(items[59].path);
  await click(nav('next'));
  expect(currentPath()).toBe(items[60].path);
  const pass = [...host.querySelectorAll<HTMLButtonElement>('.gallery-detail button')]
    .find(button => button.textContent?.trim().startsWith(t('gallery.human.pass')))!;
  await click(pass);
  expect(currentPath()).toBe(items[60].path);
  expect(host.textContent).toContain(t('gallery.outside_filter'));
  expect(nav('next')).toBeNull();
  await click(host.querySelector<HTMLButtonElement>('.gallery-detail .ghost')!);
  expect(host.querySelectorAll('.gallery-open')).toHaveLength(60);
});

it('keeps the reviewed path when an earlier navigation response arrives afterward', async () => {
  await renderOldestUnreviewed();
  await click(host.querySelectorAll<HTMLButtonElement>('.gallery-open')[59]);
  let release!: () => void;
  delayNext = () => new Promise<void>(resolve => { release = resolve; });
  await act(async () => nav('next').click());
  const pass = [...host.querySelectorAll<HTMLButtonElement>('.gallery-detail button')]
    .find(button => button.textContent?.trim().startsWith(t('gallery.human.pass')))!;
  await click(pass);
  expect(currentPath()).toBe(items[59].path);
  expect(host.textContent).toContain(t('gallery.outside_filter'));
  delayNext = null;
  await act(async () => release()); await pause();
  expect(currentPath()).toBe(items[59].path);
  await click(nav('next'));
  expect(currentPath()).toBe(items[60].path);
});
