// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, post, put } from '../api';
import { t } from '../i18n';
import type { WorkInfo } from '../types';
import { UnsavedRegistry } from '../lib/unsaved';
import { TabScope } from './Unsaved';
import ImageDesign from './ImageDesign';

vi.mock('../api', async original => ({ ...await original<typeof import('../api')>(), get: vi.fn(), put: vi.fn(), post: vi.fn() }));
let host: HTMLDivElement; let root: Root; let qc: QueryClient; let registry: UnsavedRegistry;
const url = '/api/works/work/image/characters/C001';
const key = ['design', 'work', 'C001'];
const info: WorkInfo = { name: 'Test', doc: { id: 'W001' }, presets: [], effective: { linked: [], values: {}, sources: {} } };
const design = { trigger: 'w001_c001', appearance: { prompt: ['blue eyes'], negative: ['hat'] },
  outfits: { o01: { name: 'Uniform', code: '01', slots: { top: { prompt: ['white shirt'], negative: [] }, shoes: { ref: 'global:boots' } }, negative: ['logo'] } },
  default_outfit: 'o01', retired_outfit_ids: ['o02'], next_outfit_number: 3 };
let server: { design: typeof design | null; revision: string | null };
const openImage = vi.fn(); const beforeConvert = vi.fn(async () => true);
const button = (key: string, within: ParentNode = host) => [...within.querySelectorAll('button')].find(b => b.textContent === t(key))!;
const appearance = () => host.querySelector<HTMLTextAreaElement>('textarea')!;
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
async function click(key: string, within: ParentNode = host) { await act(async () => button(key, within).click()); await settle(); }
async function edit(value: string, input = appearance()) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function mount(characterId: string | undefined = 'C001') {
  await act(async () => root.render(<QueryClientProvider client={qc}><TabScope registry={registry} tab="character">
    <ImageDesign workId="work" characterId={characterId} info={info}
      onReview={vi.fn()} openImage={openImage} beforeConvert={beforeConvert} />
  </TabScope></QueryClientProvider>));
  await settle();
}
async function expandLlm() {
  await act(async () => { const details = host.querySelector<HTMLDetailsElement>('.image-design-assist')!; details.open = true; details.dispatchEvent(new Event('toggle')); });
  await settle();
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('confirm', vi.fn(() => true));
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  server = { design: structuredClone(design), revision: 'r0' };
  registry = new UnsavedRegistry(); qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  vi.mocked(get).mockImplementation(async path => path === url ? structuredClone(server) : path === '/api/providers' ? { providers: {}, tasks: {} } : { slots: [{ id: 'top', name: 'Top' }, { id: 'shoes', name: 'Shoes' }] });
  vi.mocked(put).mockImplementation(async (_, body) => { server = { design: (body as typeof server).design, revision: 'r1' }; return structuredClone(server); });
  vi.mocked(post).mockResolvedValue({}); beforeConvert.mockResolvedValue(true);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.unstubAllGlobals(); });

it('opens an editable empty form without marking it dirty, saving or loading an LLM connection', async () => {
  server = { design: null, revision: null }; await mount();
  expect(appearance().value).toBe(''); expect(registry.dirty('character')).toBe(false);
  expect(button('common.save').disabled).toBe(true);
  expect(host.querySelector<HTMLDetailsElement>('.image-design-assist')!.open).toBe(false);
  expect(get).not.toHaveBeenCalledWith('/api/providers'); expect(post).not.toHaveBeenCalled(); expect(put).not.toHaveBeenCalled();
  await edit('(blue eyes, long hair:1.2), ');
  expect(appearance().value).toBe('(blue eyes, long hair:1.2), ');
  expect(registry.canSave('character')).toBe(true);
  await click('common.save');
  expect(put).toHaveBeenCalledWith(url, expect.objectContaining({ base_revision: null, design: expect.objectContaining({ appearance: { prompt: ['(blue eyes, long hair:1.2)'], negative: [] } }) }));
  expect(registry.dirty('character')).toBe(false); expect(appearance().disabled).toBe(false);
  await edit('green eyes'); await click('common.save');
  expect(put).toHaveBeenLastCalledWith(url, expect.objectContaining({ base_revision: 'r1' }));
});

it('keeps existing data editable and restores displayed text and the latest revision on revert', async () => {
  await mount(); await edit('red eyes');
  server = { design: { ...structuredClone(design), appearance: { prompt: ['green eyes'], negative: [] } }, revision: 'r2' };
  await act(async () => { qc.setQueryData(key, server); });
  await settle();
  expect(appearance().value).toBe('red eyes'); expect(registry.dirty('character')).toBe(true);
  vi.mocked(confirm).mockReturnValueOnce(false); await click('image.design.revert');
  expect(appearance().value).toBe('red eyes');
  await click('image.design.revert');
  expect(appearance().value).toBe('green eyes'); expect(registry.dirty('character')).toBe(false);
  await edit('gold eyes'); await click('common.save');
  expect(put).toHaveBeenLastCalledWith(url, expect.objectContaining({ base_revision: 'r2' }));
});

it('refreshes a clean editor when a conversion is applied elsewhere', async () => {
  await mount();
  await act(async () => { qc.setQueryData(key, { design: { ...design, appearance: { prompt: ['silver hair'], negative: [] } }, revision: 'applied' }); });
  await settle();
  expect(appearance().value).toBe('silver hair'); expect(registry.dirty('character')).toBe(false);
  await edit('blue eyes'); expect(registry.dirty('character')).toBe(true);
  await edit('silver hair'); expect(registry.dirty('character')).toBe(false);
});

it('keeps input and the original revision after a conflict, and refuses guarded navigation', async () => {
  await mount(); await edit('red eyes');
  await act(async () => { qc.setQueryData(key, { ...server, revision: 'r2' }); });
  await settle();
  vi.mocked(put).mockRejectedValueOnce(new ApiError(409, { key: 'server.image.design.stale', text: 'Conflict' }));
  await act(async () => { expect(await registry.save('character')).toBe(false); });
  expect(put).toHaveBeenCalledWith(url, expect.objectContaining({ base_revision: 'r0' }));
  expect(appearance().value).toBe('red eyes'); expect(registry.dirty('character')).toBe(true);
});

it('waits for a pending save without submitting twice when the close guard also saves', async () => {
  await mount(); await edit('red eyes');
  let resolve!: (value: unknown) => void;
  vi.mocked(put).mockReturnValueOnce(new Promise(r => { resolve = r; }));
  let first!: Promise<boolean>; let second!: Promise<boolean>;
  await act(async () => { first = registry.save('character'); });
  await act(async () => { second = registry.save('character'); });
  expect(put).toHaveBeenCalledTimes(1);
  await act(async () => { server = { design: { ...design, appearance: { prompt: ['red eyes'], negative: ['hat'] } }, revision: 'r1' }; resolve(server); expect(await first).toBe(true); expect(await second).toBe(true); });
  expect(registry.dirty('character')).toBe(false);
});

it('runs whole-text conversion only on request and only after the document save succeeds', async () => {
  await mount(); await expandLlm(); expect(get).toHaveBeenCalledWith('/api/providers'); expect(post).not.toHaveBeenCalled();
  await edit('red eyes'); expect(button('image.design.convert_all').disabled).toBe(true);
  await click('image.design.convert_all'); expect(beforeConvert).not.toHaveBeenCalled();
  await click('common.save'); beforeConvert.mockResolvedValueOnce(false);
  await click('image.design.convert_all'); expect(post).not.toHaveBeenCalled();
  await click('image.design.convert_all'); expect(post).toHaveBeenCalledWith(url + '/convert', { llm: undefined });
});

it('offers cancel, save and discard before image navigation and stays on a failed save', async () => {
  await mount(); await edit('red eyes'); await click('flow.generate');
  expect(openImage).not.toHaveBeenCalled(); await click('common.cancel', host.querySelector('.dialog')!);
  expect(appearance().value).toBe('red eyes'); expect(host.querySelector('.dialog')).toBeNull();
  await click('flow.generate');
  vi.mocked(put).mockRejectedValueOnce(new Error('offline'));
  await click('image.design.save_continue'); expect(openImage).not.toHaveBeenCalled(); expect(host.querySelector('.dialog')).not.toBeNull();
  await click('image.design.save_continue'); expect(openImage).toHaveBeenCalledWith('generate', 'C001', 'o01'); expect(registry.dirty('character')).toBe(false);
  openImage.mockClear(); await edit('gold eyes'); await click('flow.gallery'); await click('leave.discard');
  expect(openImage).toHaveBeenCalledWith('gallery', 'C001', 'o01'); expect(appearance().value).toBe('red eyes'); expect(registry.dirty('character')).toBe(false);
});

it('preserves shared references and retired IDs, and assigns a new default after deletion', async () => {
  await mount(); await click('image.design.add_outfit'); await click('common.save');
  expect(server.design?.outfits).toHaveProperty('o03'); expect(server.design?.outfits.o01.slots.shoes.ref).toBe('global:boots');
  await click('common.delete'); await click('common.save');
  expect(server.design?.retired_outfit_ids).toEqual(['o02', 'o01']); expect(server.design?.default_outfit).toBe('o03');
});

it('keeps the ID requirement without creating a form or loading image settings', async () => {
  await act(async () => root.render(<QueryClientProvider client={qc}><ImageDesign workId="work" info={info} onReview={vi.fn()} /></QueryClientProvider>));
  expect(host.textContent).toBe(t('image.need_id')); expect(get).not.toHaveBeenCalled(); expect(put).not.toHaveBeenCalled();
});
