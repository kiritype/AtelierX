// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from '../../api';
import { t } from '../../i18n';
import ImageGallery, { type GalleryItem } from './ImageGallery';

vi.mock('../../api', async (original) => ({ ...await original<typeof import('../../api')>(), get: vi.fn() }));
vi.mock('../Toasts', () => ({ useToast: () => vi.fn() }));

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

const items = ['a', 'b', 'c', 'd'].map((name): GalleryItem => ({
  path: `${name}.png`, filename: `${name}.png`, folder: '', kind: 'image',
  image_url: `/image/${name}`, thumbnail_url: `/thumb/${name}`, has_record: true,
  work_id: 'w0', character_id: 'c0', outfit_id: 'o0', expression_id: 'e0',
  outfit_name: 'Outfit', expression_name: 'Smile', rating: '', model_family: '',
  postprocessed: false, created_at: '', sha256: '', human_status: 'unreviewed',
  note: '', auto_status: 'pending', auto_reason: '', adopted: false,
}));

const flush = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); };
const click = async (button: HTMLButtonElement) => { await act(async () => button.click()); await flush(); };
const byText = (value: string) => [...host.querySelectorAll<HTMLButtonElement>('.gallery-detail button')]
  .find(button => button.textContent?.trim() === value)!;

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  vi.mocked(get).mockImplementation(async (url) => {
    if (url === '/api/image/gallery/tree') return { works: [], folders: [], expressions: [], revision: 1 };
    if (url.startsWith('/api/image/gallery?')) return { results: items, total: items.length, page: 1, pages: 1, snapshot: 'snap', newer: 0 };
    if (url.startsWith('/api/image/gallery/detail?')) {
      const path = new URL(url, 'http://localhost').searchParams.get('path')!;
      const item = items.find(value => value.path === path)!;
      return { ...item, record: { positive: `prompt ${path}`, seed: items.indexOf(item), settings: { model: path } }, history: [], adopted_path: null };
    }
    if (url === '/api/image/review/rounds') return { rounds: [], enabled: false };
    if (url === '/api/works/w0/image/designs') return [];
    if (url === '/api/image/presets') return [];
    return {};
  });
});

afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.clearAllMocks(); });

it('keeps one record and preset control through real modal navigation, expansion and reopening', async () => {
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <ImageGallery workId="w0" openLab={() => {}} openTools={() => {}} />
  </QueryClientProvider>));
  await flush();
  await click(host.querySelector<HTMLButtonElement>('.gallery-open')!);

  for (const [index, name] of ['a', 'b', 'c', 'd', 'c', 'b'].entries()) {
    expect(host.querySelector('.gallery-detail .mono')?.textContent).toContain(`${name}.png`);
    expect([...host.querySelectorAll('.gallery-detail button')].filter(button => button.textContent === t('gallery.open_record'))).toHaveLength(1);
    expect([...host.querySelectorAll('.gallery-detail button')].filter(button => button.textContent === t('gallery.save_preset'))).toHaveLength(1);
    await click(byText(t('gallery.open_record')));
    const record = host.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${t('gallery.record_json')}"]`)!;
    expect(record.readOnly).toBe(true);
    expect(JSON.parse(record.value).positive).toBe(`prompt ${name}.png`);
    record.focus(); record.select();
    await act(async () => record.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })));
    expect(host.querySelector('.gallery-detail .mono')?.textContent).toContain(`${name}.png`);
    if (index !== 0) await click(byText(t('gallery.close_record')));
    if (index === 2) {
      await click(byText(t('gallery.save_preset')));
      expect(host.querySelectorAll('.gallery-detail .save-preset')).toHaveLength(1);
      expect(host.querySelector('.gallery-detail .save-preset')?.textContent).toContain('c.png');
    }
    if (index < 5) await click(host.querySelector<HTMLButtonElement>(index >= 3 ? '.gallery-detail .nav.prev' : '.gallery-detail .nav.next')!);
  }

  await click(host.querySelector<HTMLButtonElement>('.gallery-detail .ghost')!);
  expect(host.querySelector('.gallery-detail')).toBeNull();
  await click(host.querySelector<HTMLButtonElement>('.gallery-open')!);
  expect([...host.querySelectorAll('.gallery-detail button')].filter(button => button.textContent === t('gallery.open_record'))).toHaveLength(1);
  expect(host.querySelector(`textarea[aria-label="${t('gallery.record_json')}"]`)).toBeNull();
});
