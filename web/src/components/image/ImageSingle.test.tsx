// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import * as api from '../../api';
import { t } from '../../i18n';
import ImageSingle from './ImageSingle';

vi.mock('../../api', async (original) => ({
  ...await original<typeof import('../../api')>(),
  get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(),
}));
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
const openView = vi.fn();
const fetch = vi.fn();
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const status = () => host.querySelector('[role="status"]')?.textContent;
const positive = () => host.querySelector('textarea[id$="-positive"]') as HTMLTextAreaElement;
const negative = () => host.querySelector('textarea[id$="-negative"]') as HTMLTextAreaElement;
const preset = () => host.querySelector('.single-field select') as HTMLSelectElement;
function button(text: string) {
  const result = [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === text);
  expect(result, text).toBeTruthy();
  return result!;
}
const click = (text: string) => act(async () => button(text).click());
async function change(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  await act(async () => {
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype :
      element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  });
}
function seed() {
  const label = [...host.querySelectorAll('label')].find((el) => el.querySelector('span')?.textContent === t('gen.seed'));
  return label!.querySelector('input')!;
}
function resultDraft() {
  return JSON.parse(host.querySelector('.single-result details pre')!.textContent!);
}

beforeEach(async () => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.stubGlobal('fetch', fetch);
  localStorage.clear();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><ImageSingle workId="synthetic" openView={openView} /></QueryClientProvider>));
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  // Preview settings must use their fixtures even after switching service or model.
  for (const request of [api.get, api.post, api.put, api.patch, api.del, fetch]) expect(request).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it('preserves both prompts across service, model and preset changes and restores each service settings', async () => {
  await change(positive(), 'Two people beside a lake\nwith long detailed text');
  await change(negative(), 'blur, extra fingers\nwatermark');
  await change(seed(), '73');
  await click('SDXL·IL');
  await change(preset(), 'soft');
  for (const service of ['NovelAI', 'PixAI', 'ComfyUI']) {
    await click(service);
    expect(positive().value).toBe('Two people beside a lake\nwith long detailed text');
    expect(negative().value).toBe('blur, extra fingers\nwatermark');
    expect(preset().value).toBe('soft');
  }
  expect(seed().value).toBe('73');
  expect(button('SDXL·IL').className).toBe('on');
  await change(preset(), 'ink');
  expect(positive().value).toContain('Two people beside a lake');
  expect(negative().value).toContain('watermark');
  const stored = JSON.parse(localStorage.getItem('atelierx-single-ui-v1-synthetic')!);
  expect(stored.settings.comfyui.seed).toBe(73);
  expect(stored.preset).toBe('ink');
});

it.each([0, 500])('cancels a request after %i ms without a late result or completion', async (elapsed) => {
  await change(positive(), 'A request to cancel');
  await click(t('single.run'));
  expect(status()).toBe(t('single.state.queued'));
  if (elapsed) {
    await advance(elapsed);
    expect(status()).toBe(t('single.state.running'));
  }
  await click(t('common.cancel'));
  await advance(3000);
  expect(status()).toBe(t('single.state.cancelled'));
  expect(host.querySelector('.single-canvas svg')).toBeNull();
  expect(host.querySelector('progress')).toBeNull();
});

it('uses an immutable request snapshot while typing and restores its prompts, service, preset and seed', async () => {
  await change(positive(), 'Original request');
  await change(negative(), 'Original negative');
  await change(seed(), '123');
  await change(preset(), 'soft');
  await click(t('single.run'));
  await change(positive(), 'Typed while running');
  await change(negative(), 'Different negative');
  await click('NovelAI');
  await change(preset(), 'ink');
  await advance(450);
  await advance(1200);
  expect(status()).toBe(t('single.state.done'));
  expect(positive().value).toBe('Typed while running');
  expect(resultDraft()).toMatchObject({ positive: 'Original request', negative: 'Original negative', service: 'comfyui', preset: 'soft', settings: { comfyui: { seed: 123 } } });
  await click(t('single.restore'));
  expect(positive().value).toBe('Original request');
  expect(negative().value).toBe('Original negative');
  expect(preset().value).toBe('soft');
  expect(seed().value).toBe('123');
  expect(button('ComfyUI').getAttribute('aria-pressed')).toBe('true');
  await click(t('single.regenerate'));
  await advance(450);
  await advance(1200);
  expect(resultDraft().settings.comfyui.seed).toBe(123);
});

it('retries the failed request rather than silently substituting newly edited input', async () => {
  await change(positive(), 'Fail this snapshot');
  await act(async () => (host.querySelector('.single-run input[type="checkbox"]') as HTMLInputElement).click());
  await click(t('single.run'));
  await change(positive(), 'New draft after enqueue');
  await advance(450);
  await advance(1200);
  expect(status()).toBe(t('single.state.failed'));
  expect(host.querySelector('.single-canvas svg')).toBeNull();
  await click(t('single.retry'));
  await advance(450);
  await advance(1200);
  expect(status()).toBe(t('single.state.done'));
  expect(positive().value).toBe('New draft after enqueue');
  expect(resultDraft().positive).toBe('Fail this snapshot');
});

it('keeps multi-character disabled and opens another view only after explicit handoff', async () => {
  const multi = button(t('single.multi'));
  expect(multi.disabled).toBe(true);
  await act(async () => multi.click());
  expect(status()).toBe(t('single.state.idle'));
  await change(positive(), 'Preview handoff');
  await click(t('single.run'));
  await advance(450);
  await advance(1200);
  await click(t('single.send_tools'));
  expect(openView).not.toHaveBeenCalled();
  expect(host.querySelector('.single-handoff')?.textContent).toContain(t('single.handoff_note'));
  await click(t('single.open_existing'));
  expect(openView).toHaveBeenCalledWith('tools');
});
