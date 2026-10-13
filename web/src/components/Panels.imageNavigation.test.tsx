// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { t } from '../i18n';
import { get } from '../api';
import Panels from './Panels';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), get: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
const open = vi.fn();

beforeEach(async () => {
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['tree', 'work'], [
    { type: 'item', kind: 'character', name: 'Example.md', path: 'Example.md', id: 'C001' },
    { type: 'item', kind: 'character', name: 'No ID.md', path: 'No ID.md' },
  ]);
  vi.mocked(get).mockResolvedValue([]);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(
    <QueryClientProvider client={qc}><Panels panel="image" workId="work"
      info={{ name: 'Example', doc: {}, presets: [], effective: { linked: [], sources: {}, values: {} } }}
      activePath={null} open={open} closeKey={() => {}} renamePath={() => {}} /></QueryClientProvider>,
  ));
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
});

it('opens single-image generation independently and exposes preparation and job management views', async () => {
  for (const view of ['single', 'presets', 'models', 'board', 'queue']) {
    const entry = [...host.querySelectorAll('.tree-row')].find((row) => row.textContent === t('image_menu.' + view));
    expect(entry).toBeTruthy();
    await act(async () => (entry as HTMLElement).click());
    expect(open).toHaveBeenLastCalledWith({ type: 'image', view, characterId: undefined });
  }
});

it('keeps character-scoped gallery, generation, training and document shortcuts', async () => {
  const row = [...host.querySelectorAll('.character-row')].find((row) => row.textContent?.includes('C001')) as HTMLElement;
  await act(async () => row.click());
  expect(open).toHaveBeenLastCalledWith({ type: 'image', view: 'gallery', characterId: 'C001' });
  const buttons = row.querySelectorAll('button');
  await act(async () => buttons[0].click());
  expect(open).toHaveBeenLastCalledWith({ type: 'image', view: 'generate', characterId: 'C001' });
  await act(async () => buttons[1].click());
  expect(open).toHaveBeenLastCalledWith({ type: 'image', view: 'lora', characterId: 'C001' });
  await act(async () => buttons[2].click());
  expect(open).toHaveBeenLastCalledWith({ type: 'item', path: 'Example.md' });
  const noId = [...host.querySelectorAll('.character-row')].find((row) => row.textContent?.includes('No ID')) as HTMLElement;
  await act(async () => noId.click());
  expect(open).toHaveBeenLastCalledWith({ type: 'item', path: 'No ID.md' });
});
