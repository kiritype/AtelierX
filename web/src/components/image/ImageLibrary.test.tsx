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
const serviceSelect = () => host.querySelector<HTMLSelectElement>('.image-lib-list select')!;
const libraryRows = () => [...host.querySelectorAll<HTMLElement>('.image-lib-list .list-row')];
const rowIds = () => libraryRows().map((row) => row.querySelector<HTMLElement>('span[title]')!.title).sort();
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find((el) => el.textContent?.trim() === label);
  expect(button).toBeTruthy();
  await act(async () => button!.click());
  await advance();
}
async function changeInput(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
const edit = (value: string) => changeInput(name(), value);
const chooseService = (service: string) => act(async () => {
  const select = serviceSelect();
  select.value = service;
  select.dispatchEvent(new Event('change', { bubbles: true }));
});

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

it('shows names first and keeps same-name and unnamed items distinct by ID and scope', async () => {
  await act(async () => qc.setQueryData(key, {
    one: initial,
    two: { ...initial, id: 'two', scope: 'global' },
    three: { ...initial, id: 'three', name: ' ', scope: 'work' },
  }));
  await advance();
  const rows = [...host.querySelectorAll('.image-lib-list .list-row')];
  expect(rows).toHaveLength(3);
  expect(rows[0].textContent).toContain('Original');
  expect(rows[0].textContent).toContain('one');
  expect(rows[1].textContent).toContain('two');
  expect(rows[1].textContent).toContain(t('lib.scope.global'));
  expect(rows[2].textContent).toContain('three');
  await act(async () => (rows[1] as HTMLElement).click());
  expect(host.querySelector('.image-lib-edit strong')?.textContent).toBe('Original');
  expect(host.querySelector('.image-lib-edit .faint.small')?.textContent).toContain('two');
  expect(name().value).toBe('Original');
});

it('combines service and text filters across shared, multi-target, global and work items', async () => {
  const item = (id: string, targets: string[], scope = 'work', group = '') => ({
    ...initial, id, name: id, targets, scope, group,
  });
  await act(async () => qc.setQueryData(key, {
    one: initial,
    shared: item('shared', [], 'global'),
    anima: item('anima', ['anima']),
    sdxl: item('sdxl', ['sdxl'], 'global'),
    moss: item('moss', ['moss'], 'work', 'Portraits'),
    novelai: item('novelai', ['novelai'], 'global', 'Portraits'),
    pixai: item('pixai', ['pixai']),
    both: item('both', ['novelai', 'sdxl']),
    custom: item('custom', ['other']),
  }));
  await advance();
  expect(serviceSelect().value).toBe('');
  expect(rowIds()).toEqual(['anima', 'both', 'custom', 'moss', 'novelai', 'one', 'pixai', 'sdxl', 'shared']);
  await chooseService('novelai');
  expect(rowIds()).toEqual(['both', 'novelai', 'one', 'shared']);
  expect(libraryRows().find((row) => row.textContent?.includes('shared'))?.textContent).toContain(t('lib.all_services'));
  expect(libraryRows().find((row) => row.textContent?.includes('shared'))?.textContent).toContain(t('lib.scope.global'));
  await chooseService('comfyui');
  expect(rowIds()).toEqual(['anima', 'both', 'moss', 'one', 'sdxl', 'shared']);
  await chooseService('pixai');
  expect(rowIds()).toEqual(['one', 'pixai', 'shared']);

  const search = host.querySelector<HTMLInputElement>('.image-lib-list input.grow')!;
  await changeInput(search, 'PORTRAITS');
  expect(rowIds()).toEqual([]);
  await chooseService('comfyui');
  expect(rowIds()).toEqual(['moss']);
  await chooseService('novelai');
  expect(rowIds()).toEqual(['novelai']);
  await chooseService('');
  expect(rowIds()).toEqual(['moss', 'novelai']);
  await changeInput(search, 'custom');
  expect(rowIds()).toEqual(['custom']);
});

it('keeps a hidden editor dirty and uses the existing discard confirmation when changing items or kinds', async () => {
  const scoped = { ...initial, id: 'scoped', name: 'For NovelAI', targets: ['novelai'] };
  const comp = { ...initial, id: 'composition', name: 'Comfy composition', targets: ['sdxl'] };
  await act(async () => {
    qc.setQueryData(key, { one: initial, scoped });
    qc.setQueryData(['image-lib', 'compositions', 'work'], { composition: comp, scoped });
  });
  await advance();
  await act(async () => libraryRows().find((row) => row.textContent?.includes(scoped.name))!.click());
  await edit('Still editing');
  const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
  vi.stubGlobal('confirm', confirm);
  await chooseService('comfyui');
  expect(rowIds()).toEqual(['one']);
  expect(confirm).not.toHaveBeenCalled();
  expect(registry.dirty('library')).toBe(true);
  expect(name().value).toBe('Still editing');
  expect(put).not.toHaveBeenCalled();

  await act(async () => libraryRows()[0].click());
  expect(confirm).toHaveBeenLastCalledWith(t('lib.discard_confirm'));
  expect(name().value).toBe('Still editing');
  const kind = [...host.querySelectorAll<HTMLElement>('.image-lib-kinds .tree-row')]
    .find((row) => row.textContent?.trim() === t('lib.kind.compositions'))!;
  await act(async () => kind.click());
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(serviceSelect().value).toBe('comfyui');
  expect(rowIds()).toEqual(['composition']);
  expect(registry.dirty('library')).toBe(false);
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
