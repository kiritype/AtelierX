// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from '../../api';
import { t } from '../../i18n';
import ImageGallery from './ImageGallery';

vi.mock('../../api', async (original) => ({ ...await original<typeof import('../../api')>(), get: vi.fn() }));
vi.mock('../Toasts', () => ({ useToast: () => vi.fn() }));
vi.mock('./DeploymentExport', () => ({ DeploymentExport: ({ scope }: { scope: Record<string, string> }) => <div data-testid="export-scope">{JSON.stringify(scope)}</div> }));
vi.mock('./DeployUpload', () => ({ DeployUpload: ({ scope }: { scope: Record<string, string> }) => <div data-testid="upload-scope">{JSON.stringify(scope)}</div> }));

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
const pause = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); };
const settle = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); }); };
const click = async (element: HTMLElement) => { await act(async () => element.click()); await pause(); };
const gallery = (workId: string) => <ImageGallery workId={workId} openLab={() => {}} openTools={() => {}} />;
const image = (path: string, workId: string, folder = '') => ({
  path, filename: path.split('/').at(-1), folder, kind: 'image', image_url: '/image', thumbnail_url: '/thumb',
  has_record: false, work_id: workId, character_id: '', outfit_id: '', expression_id: '', outfit_name: '',
  expression_name: '', rating: '', model_family: '', postprocessed: false, created_at: '', sha256: '',
  human_status: 'unreviewed', note: '', auto_status: 'pending', auto_reason: '', adopted: false,
});

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  vi.mocked(get).mockImplementation(async (url) => {
    if (url.startsWith('/api/image/gallery/tree')) {
      const work = new URL(url, 'http://localhost').searchParams.get('library_work');
      return { works: work ? [{ id: work, count: 1, characters: [] }] : [{ id: 'w0', count: 1, characters: [] }, { id: 'w1', count: 1, characters: [] }],
        folders: work ? [{ path: `_single/${work}`, count: 1 }] : [], expressions: [], revision: 1 };
    }
    if (url.startsWith('/api/image/gallery?')) {
      const query = new URL(url, 'http://localhost').searchParams;
      const work = query.get('library_work') ?? 'global';
      const folder = query.get('folder');
      return { results: [image(folder ?? `${work}/image.png`, work, folder ?? '')],
        total: 1, page: Number(query.get('page') ?? 1), pages: 1, snapshot: `${work}-snapshot`, newer: 0 };
    }
    if (url === '/api/image/review/rounds') return { rounds: [], enabled: false };
    if (url.startsWith('/api/works/')) return [];
    return {};
  });
});

afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.clearAllMocks(); });

it('starts work scoped, keeps the current work boundary for single images, and loads global data only on opt-in', async () => {
  await act(async () => root.render(<QueryClientProvider client={qc}>{gallery('w0')}</QueryClientProvider>));
  await pause();
  const initialTree = vi.mocked(get).mock.calls.find(([url]) => url.startsWith('/api/image/gallery/tree'))?.[0] as string;
  const initialList = vi.mocked(get).mock.calls.find(([url]) => url.startsWith('/api/image/gallery?'))?.[0] as string;
  expect(initialTree).toContain('library_work=w0');
  expect(new URL(initialList, 'http://localhost').searchParams.get('library_work')).toBe('w0');
  expect(new URL(initialList, 'http://localhost').searchParams.has('work')).toBe(false);

  await click([...host.querySelectorAll<HTMLButtonElement>('.gallery-toolbar button')]
    .find(button => button.textContent === t('gallery.export'))!);
  expect(host.querySelector('[data-testid="export-scope"]')?.textContent).toBe('{"work":"w0"}');
  await click([...host.querySelectorAll<HTMLButtonElement>('.gallery-toolbar button')]
    .find(button => button.textContent === t('deploy.upload_title'))!);
  expect(host.querySelector('[data-testid="upload-scope"]')?.textContent).toBe('{"work":"w0"}');

  const singleFolder = [...host.querySelectorAll<HTMLButtonElement>('.gallery-tree .tree-link')]
    .at(-1)!;
  await click(singleFolder);
  const singleList = vi.mocked(get).mock.calls.map(([url]) => url as string)
    .find(url => url.startsWith('/api/image/gallery?') && new URL(url, 'http://localhost').searchParams.has('folder'))!;
  expect(new URL(singleList, 'http://localhost').searchParams.get('library_work')).toBe('w0');

  await click([...host.querySelectorAll<HTMLButtonElement>('.gallery-tree .tree-link')]
    .find(button => button.textContent === t('gallery.load_full_library'))!);
  await settle();
  const globalTree = vi.mocked(get).mock.calls.map(([url]) => url as string)
    .find(url => url.startsWith('/api/image/gallery/tree') && !url.includes('library_work='))!;
  const globalList = vi.mocked(get).mock.calls.map(([url]) => url as string)
    .find(url => url.startsWith('/api/image/gallery?') && !new URL(url, 'http://localhost').searchParams.has('library_work'))!;
  expect(globalTree).toBeTruthy();
  expect(globalList).toBeTruthy();
  expect(host.querySelector('.gallery-cell')?.getAttribute('data-gallery-path')).toContain('global/');

  await click([...host.querySelectorAll<HTMLButtonElement>('.gallery-tree .tree-link')]
    .find(button => button.textContent === t('gallery.return_to_work'))!);
  await settle();
  expect(host.querySelector('.gallery-cell')?.getAttribute('data-gallery-path')).toContain('w0/');
  expect(host.querySelector('.gallery-cell')?.getAttribute('data-gallery-path')).not.toContain('global/');
  expect(vi.mocked(get).mock.calls.some(([url]) => String(url).startsWith('/api/image/gallery?') && String(url).includes('library_work=w0'))).toBe(true);
});

it('does not show the previous work when the active work changes', async () => {
  function Work({ id }: { id: string }) { return <ImageGallery workId={id} openLab={() => {}} openTools={() => {}} />; }
  await act(async () => root.render(<QueryClientProvider client={qc}><Work id="w0" /></QueryClientProvider>));
  await pause();
  expect(host.querySelector('.gallery-cell')?.getAttribute('data-gallery-path')).toContain('w0/');
  await act(async () => root.render(<QueryClientProvider client={qc}><Work id="w1" /></QueryClientProvider>));
  await pause();
  expect(host.querySelector('.gallery-cell')?.getAttribute('data-gallery-path')).toContain('w1/');
  expect(host.querySelector('.gallery-cell')?.getAttribute('data-gallery-path')).not.toContain('w0/');
  expect(vi.mocked(get).mock.calls.some(([url]) => String(url).startsWith('/api/image/gallery?') && String(url).includes('library_work=w1'))).toBe(true);
});

it('can use exactly one checked image from the current work as a reference', async () => {
  const getFixture = vi.mocked(get).getMockImplementation()!;
  const first = image('w0/first.png', 'w0');
  const second = image('w0/second.png', 'w0');
  const other = image('w1/other.png', 'w1');
  vi.mocked(get).mockImplementation(async url => {
    if (!url.startsWith('/api/image/gallery?')) return getFixture(url);
    const scoped = new URL(url, 'http://localhost').searchParams.has('library_work');
    const results = scoped ? [first, second] : [first, other];
    return { results, total: results.length, page: 1, pages: 1, snapshot: scoped ? 'work' : 'global', newer: 0 };
  });
  const openReference = vi.fn();
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <ImageGallery workId="w0" openLab={() => {}} openTools={() => {}} openReference={openReference} />
  </QueryClientProvider>));
  await settle();
  const action = () => [...host.querySelectorAll<HTMLButtonElement>('button')]
    .find(button => button.textContent === t('reference.use_selected'));
  const check = (path: string) => click(host.querySelector<HTMLInputElement>(`input.gallery-check[aria-label="${path}"]`)!);

  expect(action()).toBeUndefined();
  await check(first.path);
  expect(action()).toBeDefined();
  await check(second.path);
  expect(action()).toBeUndefined();
  await check(second.path);
  await click(action()!);
  expect(openReference).toHaveBeenCalledExactlyOnceWith(first.path);

  await click([...host.querySelectorAll<HTMLButtonElement>('.gallery-tree .tree-link')]
    .find(button => button.textContent === t('gallery.load_full_library'))!);
  await settle();
  await check(other.path);
  expect(host.querySelector<HTMLInputElement>(`input.gallery-check[aria-label="${other.path}"]`)?.checked).toBe(true);
  expect(action()).toBeUndefined();
  expect(openReference).toHaveBeenCalledTimes(1);
});

const pathsInGallery = () => [...host.querySelectorAll('[data-gallery-path]')]
  .map(cell => cell.getAttribute('data-gallery-path'));
const newImagesButton = () => [...host.querySelectorAll<HTMLButtonElement>('.gallery-toolbar button')]
  .find(button => button.textContent === t('gallery.new_images', { n: 2 }));

function mockGalleryRefresh(initialCount: number) {
  const getFixture = vi.mocked(get).getMockImplementation()!;
  const original = Array.from({ length: initialCount }, (_, index) => image('w0/old-' + index + '.png', 'w0'));
  const updated = [...original, image('w0/new-1.png', 'w0'), image('w0/new-2.png', 'w0')];
  let latest = original;
  let finishRefresh: () => void = () => {};
  const refreshResponse = new Promise<void>(resolve => { finishRefresh = resolve; });
  const requests: URLSearchParams[] = [];
  vi.mocked(get).mockImplementation(async url => {
    if (!url.startsWith('/api/image/gallery?')) return getFixture(url);
    const params = new URL(url, 'http://localhost').searchParams;
    const page = Number(params.get('page'));
    const snapshot = params.get('snapshot');
    requests.push(params);
    if (params.get('outfit') !== 'o0') {
      return { results: [image('w0/other-scope.png', 'w0')], total: 1, page, pages: 1, snapshot: 'other', newer: 0 };
    }
    if (!snapshot && latest === updated) await refreshResponse;
    const results = snapshot === 'before' ? original : latest;
    return { results: results.slice((page - 1) * 60, page * 60), total: results.length, page,
      page_size: 60, pages: Math.ceil(results.length / 60), snapshot: snapshot ?? (results === original ? 'before' : 'after'),
      newer: latest.length - results.length };
  });

  return {
    requests, finishRefresh,
    async notifyNewImages() {
      latest = updated;
      await act(async () => { await qc.invalidateQueries({ queryKey: ['gallery'] }); });
      await settle();
    },
  };
}

async function openOutfitGallery() {
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <ImageGallery workId="w0" characterId="c0" outfitId="o0" openLab={() => {}} openTools={() => {}} />
  </QueryClientProvider>));
  await settle();
  const select = async (value: string) => {
    const dropdown = [...host.querySelectorAll<HTMLSelectElement>('.gallery-toolbar select')]
      .find(element => [...element.options].some(option => option.value === value))!;
    await act(async () => {
      dropdown.value = value;
      dropdown.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await settle();
  };
  await select('unreviewed');
  await select('oldest');
}

it.each([1, 60])('adopts the refreshed snapshot and keeps the gallery controls (%s existing images)', async initialCount => {
  const { requests, finishRefresh, notifyNewImages } = mockGalleryRefresh(initialCount);
  await openOutfitGallery();
  expect(pathsInGallery()).toHaveLength(initialCount);

  await notifyNewImages();
  expect(newImagesButton()).toBeDefined();
  await click(newImagesButton()!);
  expect(pathsInGallery()).toHaveLength(initialCount);

  await act(async () => { finishRefresh(); });
  await settle();
  expect(newImagesButton()).toBeUndefined();
  expect(requests.some(params => params.get('snapshot') === 'after' && params.get('work') === 'w0' &&
    params.get('character') === 'c0' && params.get('outfit') === 'o0' &&
    params.get('human_status') === 'unreviewed' && params.get('sort') === 'oldest')).toBe(true);

  if (initialCount === 60) {
    const nextPage = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '›');
    expect(nextPage).toBeDefined();
    await click(nextPage!);
    await settle();
    expect(requests.some(params => params.get('snapshot') === 'after' && params.get('page') === '2')).toBe(true);
  }
  expect(pathsInGallery()).toEqual(initialCount === 60
    ? ['w0/new-1.png', 'w0/new-2.png']
    : ['w0/old-0.png', 'w0/new-1.png', 'w0/new-2.png']);
});

it('keeps the latest scope when an earlier refresh finishes', async () => {
  const { requests, finishRefresh, notifyNewImages } = mockGalleryRefresh(1);
  await openOutfitGallery();
  await notifyNewImages();
  await click(newImagesButton()!);
  expect(requests.at(-1)?.get('outfit')).toBe('o0');

  const thisWork = [...host.querySelectorAll<HTMLButtonElement>('.gallery-tree .tree-link')]
    .find(button => button.textContent === t('gallery.this_work_images'));
  await click(thisWork!);
  await settle();
  expect(pathsInGallery()).toEqual(['w0/other-scope.png']);

  await act(async () => { finishRefresh(); });
  await settle();
  expect(pathsInGallery()).toEqual(['w0/other-scope.png']);
  expect(requests.at(-1)?.get('snapshot')).toBe('other');
});
