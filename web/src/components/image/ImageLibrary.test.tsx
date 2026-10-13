// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, put } from '../../api';
import { t } from '../../i18n';
import { UnsavedRegistry } from '../../lib/unsaved';
import { TabScope } from '../Unsaved';
import ImageLibrary from './ImageLibrary';

vi.mock('../../api', async (original) => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), put: vi.fn() }));
vi.mock('../TagInput', () => ({ default: () => null }));
vi.mock('../Toasts', () => ({ useToast: () => () => {} }));
vi.mock('./LibraryImport', () => ({ default: () => null }));

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
let registry: UnsavedRegistry;
const initial = { id: 'one', name: 'Original', prompt: [], negative: [], scope: 'work', revision: 'old' };
const latest = { ...initial, name: 'Remote change', revision: 'new' };
const key = ['image-lib', 'expressions', 'work'];
const advance = () => act(async () => { await vi.advanceTimersByTimeAsync(1); });
const name = () => host.querySelector('.image-lib-edit label input') as HTMLInputElement;
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find((el) => el.textContent?.trim() === label);
  expect(button).toBeTruthy();
  await act(async () => button!.click());
  await advance();
}
async function edit(value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(name(), value);
    name().dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(async () => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(key, { one: initial });
  qc.setQueryData(['image-lib-rules'], { slots: [], ratings: [], targets: [] });
  qc.setQueryData(['image-lib', 'compositions', 'work'], {});
  vi.mocked(get).mockResolvedValue({ one: latest });
  vi.mocked(put).mockRejectedValue(new ApiError(409, { key: 'server.save.stale', text: 'Stale' }));
  registry = new UnsavedRegistry();
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(
    <QueryClientProvider client={qc}>
      <TabScope registry={registry} tab="library"><ImageLibrary workId="work" /></TabScope>
    </QueryClientProvider>,
  ));
  await act(async () => (host.querySelector('.list-row') as HTMLElement).click());
});

afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it('preserves actual editor input, dirty state and stale revision after a rejected save', async () => {
  await edit('My unsaved input');
  await click(t('common.save'));
  expect(qc.getQueryData(key)).toEqual({ one: latest });
  expect(name().value).toBe('My unsaved input');
  expect(registry.dirty('library')).toBe(true);
  await click(t('common.save'));
  expect(put).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ revision: 'old', item: expect.objectContaining({ name: 'My unsaved input' }) }));
  expect(name().value).toBe('My unsaved input');
});

it('requires explicit discard approval before reopening the latest version', async () => {
  await edit('My unsaved input');
  await click(t('common.save'));
  const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
  vi.stubGlobal('confirm', confirm);
  await click(t('lib.reload_conflict'));
  expect(confirm).toHaveBeenCalledWith(t('lib.discard_confirm'));
  expect(name().value).toBe('My unsaved input');
  expect(registry.dirty('library')).toBe(true);
  await click(t('lib.reload_conflict'));
  expect(name().value).toBe('Remote change');
  expect(registry.dirty('library')).toBe(false);
  await edit('New edit');
  await click(t('common.save'));
  expect(put).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ revision: 'new' }));
});
