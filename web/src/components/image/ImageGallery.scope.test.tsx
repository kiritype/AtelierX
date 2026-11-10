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
      return { results: [{ path: folder ?? `${work}/image.png`, filename: `${work}.png`, folder: folder ?? '',
        kind: 'image', image_url: '/image', thumbnail_url: '/thumb', has_record: false, work_id: work,
        character_id: '', outfit_id: '', expression_id: '', outfit_name: '', expression_name: '', rating: '', model_family: '',
        postprocessed: false, created_at: '', sha256: '', human_status: 'unreviewed', note: '', auto_status: 'pending', auto_reason: '', adopted: false }],
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
