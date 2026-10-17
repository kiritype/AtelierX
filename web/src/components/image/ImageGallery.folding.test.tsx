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

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

const works = Array.from({ length: 20 }, (_, wi) => ({
  id: `w${wi}`, count: 100,
  characters: Array.from({ length: 20 }, (_, ci) => ({
    id: `c${ci}`, count: 5,
    outfits: Array.from({ length: 5 }, (_, oi) => ({ id: `o${oi}`, name: `Outfit ${oi}`, count: 1 })),
  })),
}));

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  vi.mocked(get).mockImplementation(async (url) => {
    if (url === '/api/image/gallery/tree') return { works, folders: [], expressions: [], revision: 1 };
    if (url.startsWith('/api/image/gallery?')) return {
      results: [{ path: 'image.png', filename: 'image.png', thumbnail_url: '/thumb', kind: 'image', work_id: 'w0',
        character_id: 'c0', expression_id: 'e0', expression_name: 'Smile', human_status: 'unreviewed', auto_status: 'pending' }],
      total: 120, page: 1, pages: 2, snapshot: 'snap', newer: 0,
    };
    if (url === '/api/image/review/rounds') return { rounds: [], enabled: false };
    if (url === '/api/works/w0/image/designs') return [];
    return {};
  });
});

afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); });

it('keeps scope, filters, selection and page while folding a long tree and its panel', async () => {
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <ImageGallery workId="w0" characterId="c0" outfitId="o0" openLab={() => {}} openTools={() => {}} />
  </QueryClientProvider>));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(host.querySelectorAll('.gallery-branch-toggle')).toHaveLength(420);
  expect(host.querySelector('.gallery-scope-path')?.textContent).toBe('w0 → c0 → Outfit 0');

  const gallery = host.querySelector('.gallery')!;
  const controls = host.querySelectorAll<HTMLSelectElement>('.gallery-toolbar select');
  await act(async () => {
    controls[1].value = 'pass';
    controls[1].dispatchEvent(new Event('change', { bubbles: true }));
  });
  const nextPage = [...host.querySelectorAll<HTMLButtonElement>('.gallery-scroll button')].find((b) => b.textContent === '›')!;
  await act(async () => nextPage.click());
  await act(async () => host.querySelector<HTMLInputElement>('.gallery-check')!.click());
  expect(host.textContent).toContain(t('gallery.selected', { n: 1 }));

  const workToggle = host.querySelector<HTMLButtonElement>('.gallery-branch-toggle')!;
  workToggle.focus();
  await act(async () => workToggle.click());
  expect(workToggle.getAttribute('aria-expanded')).toBe('false');
  expect(host.querySelector('.gallery-scope-path')?.textContent).toBe('w0 → c0 → Outfit 0');
  expect(host.querySelectorAll('.gallery-branch-toggle')).toHaveLength(400);
  expect(document.activeElement).toBe(workToggle);

  const panelToggle = host.querySelector<HTMLButtonElement>('.gallery-scopebar button')!;
  panelToggle.focus();
  await act(async () => panelToggle.click());
  expect(gallery.classList.contains('tree-collapsed')).toBe(true);
  expect(host.querySelector('.gallery-tree')).toBeNull();
  expect(panelToggle.getAttribute('aria-expanded')).toBe('false');
  expect(host.textContent).toContain(t('gallery.selected', { n: 1 }));
  expect(host.querySelector('.gallery-scope-path')?.textContent).toBe('w0 → c0 → Outfit 0');
  expect(host.textContent).toContain('2 / 2');
  expect(controls[1].value).toBe('pass');

  await act(async () => panelToggle.click());
  expect(host.querySelector('.gallery-tree')).toBeTruthy();
  expect(host.querySelector<HTMLButtonElement>('.gallery-branch-toggle')?.getAttribute('aria-expanded')).toBe('false');

  await act(async () => host.querySelector<HTMLButtonElement>('.gallery-branch-toggle')!.click());
  const characterToggle = host.querySelectorAll<HTMLButtonElement>('.gallery-branch-toggle')[1];
  const linksBefore = host.querySelectorAll('.gallery-tree .tree-link').length;
  await act(async () => characterToggle.click());
  expect(characterToggle.getAttribute('aria-expanded')).toBe('false');
  expect(host.querySelectorAll('.gallery-tree .tree-link')).toHaveLength(linksBefore - 5);
  expect(host.querySelector('.gallery-scope-path')?.textContent).toBe('w0 → c0 → Outfit 0');
  expect(host.querySelector('.gallery-tree-row .tree-link')?.textContent).toContain(t('gallery.this_work'));
});
