// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, post, put } from '../api';
import { t } from '../i18n';
import type { Item, WorkInfo } from '../types';
import ItemEditor from './ItemEditor';
import type { MenuItem } from './ui';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock('./LazyCodeEditor', () => ({ default: ({ value, onChange, menu }: { value: string; onChange: (text: string) => void; menu?: (selection: { text: string }) => MenuItem[] }) =>
  <div><pre data-testid="body">{value}</pre><button onClick={() => onChange('New prompt that must survive')}>edit text</button>
    {menu && <button onClick={() => menu({ text: value })[0]?.items?.[0]?.run?.()}>convert selection</button>}</div> }));

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
const key = ['item', 'work', 'main.md'];
const original: Item = { path: 'main.md', name: 'main', meta: { kind: 'main', id: 'M001' }, kind: 'main', body: '', hash: 'old', meta_error: null, size: 0 };
const saved = { ...original, body: 'New prompt that must survive', hash: 'saved' };
const info: WorkInfo = { name: 'Test', doc: { id: 'W001' }, presets: [], effective: { linked: [], sources: {}, values: { count: 'chars' } } };
const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find((el) => el.textContent?.trim() === label);
  expect(button, label).toBeTruthy();
  await act(async () => button!.click());
  await settle();
}

beforeEach(async () => {
  vi.clearAllMocks();
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(key, original);
  vi.mocked(get).mockImplementation(async (url) => {
    if (url.endsWith('/tree')) return [{ type: 'item', path: 'other.md', name: 'other' }];
    if (url.endsWith('/api/settings')) return { autosave: { enabled: false } };
    if (url.includes('/file?')) return original;
    return {};
  });
  vi.mocked(put).mockResolvedValue(saved);
  vi.mocked(post).mockRejectedValue(new ApiError(400, { key: 'test.llm', text: 'LLM unavailable' }));
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><ItemEditor workId="work" path="main.md" info={info} onStatus={() => {}} onReview={() => {}} /></QueryClientProvider>));
  await settle();
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
});

it.each(['compression', 'content_review', 'consistency', 'format'])('preserves the edited body when %s returns 400', async (action) => {
  await click('edit text');
  await click(t('llm_tools.title'));
  await click(t(`llm_tools.${action}`));
  if (action === 'consistency') await act(async () => (host.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
  await click(t('llm_tools.run'));
  expect(put).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ body: saved.body, base_hash: 'old' }));
  expect(post).toHaveBeenCalledTimes(1);
  expect(host.querySelector('[data-testid="body"]')?.textContent).toBe(saved.body);
  expect(host.querySelector('.dialog')).not.toBeNull();
});

it('does not restore an older in-flight file read after saving for a failed LLM action', async () => {
  await click('edit text');
  let finishRead!: (item: Item) => void;
  vi.mocked(get).mockImplementationOnce(() => new Promise((resolve) => { finishRead = resolve; }));
  let read!: Promise<void>;
  await act(async () => { read = qc.invalidateQueries({ queryKey: key }); });
  await click(t('llm_tools.title'));
  await click(t('llm_tools.compression'));
  await click(t('llm_tools.run'));
  await act(async () => { finishRead(original); await read; });
  await settle();
  expect(host.querySelector('[data-testid="body"]')?.textContent).toBe(saved.body);
  expect(qc.getQueryData<Item>(key)?.hash).toBe('saved');
});

it('keeps the input and does not call the LLM when saving fails', async () => {
  vi.mocked(put).mockRejectedValue(new ApiError(409, { key: 'test.save', text: 'Save conflict' }));
  await click('edit text');
  await click(t('llm_tools.title'));
  await click(t('llm_tools.compression'));
  await click(t('llm_tools.run'));
  expect(post).not.toHaveBeenCalled();
  expect(host.querySelector('[data-testid="body"]')?.textContent).toBe(saved.body);
  expect(host.querySelector('.dialog')).not.toBeNull();
});

it('keeps an image draft across inner tabs and blocks range conversion until the design is saved', async () => {
  const character: Item = { ...original, kind: 'character', meta: { kind: 'character', id: 'C001' }, body: 'Blue eyes' };
  const imageKey = ['design', 'work', 'C001'];
  const image = { design: { appearance: { prompt: ['blue eyes'], negative: [] }, outfits: {} }, revision: 'r0' };
  vi.mocked(get).mockImplementation(async url => url.endsWith('/C001') ? image : url.endsWith('/api/settings') ? { autosave: { enabled: false } } : {});
  await act(async () => { qc.setQueryData(key, character); qc.setQueryData(imageKey, image); });
  await settle(); await click(t('inner.image'));
  await act(async () => {
    const input = host.querySelector<HTMLTextAreaElement>('.image-design textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, 'green eyes');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await click(t('inner.body')); await click('convert selection');
  expect(post).not.toHaveBeenCalled(); expect(put).not.toHaveBeenCalled();
  await click(t('inner.image'));
  expect(host.querySelector<HTMLTextAreaElement>('.image-design textarea')!.value).toBe('green eyes');
  vi.mocked(put).mockImplementation(async (_, body) => ({ design: (body as typeof image).design, revision: 'r1' }));
  await click(t('common.save'));
  await click(t('inner.body')); await click('convert selection');
  expect(post).toHaveBeenCalledWith('/api/works/work/image/characters/C001/convert', { range: { part: 'appearance', text: 'Blue eyes' } });
});
