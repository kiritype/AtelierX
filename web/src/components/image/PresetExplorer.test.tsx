// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { get, post, put } from '../../api';
import { t } from '../../i18n';
import PresetExplorer from './PresetExplorer';

vi.mock('../../api', () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), ApiError: class extends Error {} }));
const { toast } = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock('../Toasts', () => ({ useToast: () => toast }));
vi.mock('../Unsaved', () => ({ useUnsaved: vi.fn() }));
let host: HTMLDivElement, root: Root, qc: QueryClient;
let saved = 1234567;
const presets = ['one', 'two'].map(id => ({ id, name: id, service: 'comfyui', family: 'anima',
  tags: [], settings: {}, common: [], artist: { positive: '', negative: '' } }));
const input = () => host.querySelector('input[type="number"]') as HTMLInputElement;
async function edit(value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input(), value);
    input().dispatchEvent(new Event('input', { bubbles: true }));
  });
}
beforeEach(async () => {
  vi.useFakeTimers(); vi.clearAllMocks(); saved = 1234567;
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal('confirm', vi.fn(() => true));
  vi.mocked(get).mockImplementation(async url => url.includes('/settings/') ? { preview_seed: saved } : presets);
  vi.mocked(put).mockImplementation(async (_url, body) => { saved = (body as { preview_seed: number }).preview_seed; return { preview_seed: saved }; });
  vi.mocked(post).mockResolvedValue({ count: 1, seeds: [42] });
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['image-settings', 'presets'], { preview_seed: saved });
  qc.setQueryData(['image-presets'], presets);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><PresetExplorer workId="w" openGenerate={() => {}} /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it.each(['enter', 'blur'])('saves -1 with confirmation on %s', async trigger => {
  await edit('-1');
  await act(async () => input().dispatchEvent(trigger === 'enter'
    ? new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }) : new FocusEvent('focusout', { bubbles: true })));
  expect(confirm).toHaveBeenCalledWith(t('presets.seed_confirm'));
  expect(put).toHaveBeenCalledWith('/api/image/settings/presets', { preview_seed: -1 });
});
it('reports invalid seed instead of silently discarding it', async () => {
  await edit('-2');
  await act(async () => input().dispatchEvent(new FocusEvent('focusout', { bubbles: true })));
  expect(put).not.toHaveBeenCalled();
  expect(toast).toHaveBeenCalledWith({ text: t('presets.seed_invalid'), tone: 'error' });
});
it('shares one concrete random seed across a preview batch', async () => {
  await act(async () => { qc.setQueryData(['image-settings', 'presets'], { preview_seed: -1 }); await vi.advanceTimersByTimeAsync(1); });
  const button = [...host.querySelectorAll('button')].find(b => b.textContent === t('presets.preview_all', { n: 2 }));
  await act(async () => button!.click());
  const calls = vi.mocked(post).mock.calls;
  expect(calls).toHaveLength(2);
  const seed = (calls[0][1] as { seed: number }).seed;
  expect(Number.isInteger(seed)).toBe(true); expect(seed).toBeGreaterThanOrEqual(0); expect(seed).toBeLessThanOrEqual(4294967295);
  expect(calls[1][1]).toEqual({ seed });
});

it('does not open another confirmation when Enter causes blur', async () => {
  await edit('-1');
  vi.mocked(confirm).mockImplementation(() => {
    input().dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    return true;
  });
  await act(async () => input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(put).toHaveBeenCalledTimes(1);
});
it('keeps the saved seed when confirmation is cancelled', async () => {
  await edit('-1'); vi.mocked(confirm).mockReturnValue(false);
  await act(async () => input().dispatchEvent(new FocusEvent('focusout', { bubbles: true })));
  expect(put).not.toHaveBeenCalled(); expect(input().value).toBe('1234567');
});
