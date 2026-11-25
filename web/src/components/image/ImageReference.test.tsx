// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import type { ReferenceStatus, SingleRun } from '../../imageTypes';
import { sendReferenceHandoff } from '../../lib/referenceHandoff';
import ImageReference from './ImageReference';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));

const endpoint = '/api/works/example/image/reference';
const reference = { id: 'asset', name: 'source.png', url: endpoint + '/assets/asset', sha256: '5'.repeat(64) };
const model = 'silvermoonmix.safetensors';
const catalog = {
  connected: true, models: [model], text_encoders: [], vaes: [], loras: [], samplers: ['euler'], schedulers: ['simple'],
  defaults: { family: 'anima', model },
};
const presets = [
  { id: 'anima', name: 'Silvermoon', service: 'comfyui', family: 'anima', settings: { model, steps: 16 } },
  { id: 'sdxl', name: 'SDXL preset', service: 'comfyui', family: 'sdxl', settings: {} },
];
const openView = vi.fn();
const openSettings = vi.fn();
let status: ReferenceStatus;
let history: SingleRun[];
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

const button = (label: string | RegExp) => {
  const found = [...host.querySelectorAll('button')].find(item => {
    const text = item.textContent?.trim() ?? '';
    return typeof label === 'string' ? text === label : label.test(text);
  });
  expect(found, String(label)).toBeTruthy();
  return found!;
};

const render = async () => act(async () => {
  root.render(<QueryClientProvider client={qc}><ImageReference workId="example" openView={openView} openSettings={openSettings} /></QueryClientProvider>);
  await new Promise(resolve => setTimeout(resolve, 0));
});

const changeText = async (element: HTMLTextAreaElement, value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  status = { ready: true, node_ready: true, weights_ready: true };
  history = [];
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['image-catalog'], catalog);
  qc.setQueryData(['image-presets'], presets);
  qc.setQueryData(['image-reference-runs', 'example'], { runs: [] });
  vi.mocked(get).mockImplementation(async url => {
    if (url.endsWith('/reference/status')) return status;
    if (url.endsWith('/runs')) return { runs: history };
    if (url.endsWith('/catalog')) return catalog;
    if (url.endsWith('/presets')) return presets;
    throw new Error('Unexpected GET ' + url);
  });
  vi.mocked(post).mockImplementation(async (url, body) => {
    if (url.endsWith('/assets')) return reference;
    if (url.endsWith('/queue')) {
      const request = body as { positive: string; negative: string; settings: Record<string, unknown> };
      history = [{
        id: 'job-1', status: 'queued', created_at: '2026-11-25', service: 'comfyui', seed: 7,
        request: { ...request, service: 'comfyui', preset_id: '' },
        actual: request, reference: { ...reference, guidance: 4.5 },
      }];
      return { job_id: 'job-1' };
    }
    throw new Error('Unexpected POST ' + url);
  });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
});

it('imports the gallery reference and queues the chosen Anima preset without enabling other services or families', async () => {
  sendReferenceHandoff('example', 'chosen/source.png');
  await render();
  await vi.waitFor(() => expect(host.querySelector<HTMLImageElement>('.reference-card img')?.getAttribute('src')).toBe(reference.url));
  expect(post).toHaveBeenCalledWith(endpoint + '/assets', { gallery_path: 'chosen/source.png' });
  expect(button(/^NovelAI/).disabled).toBe(true);
  expect(button(/^SDXL/).disabled).toBe(true);
  expect(button(/^MOSS/).disabled).toBe(true);

  const select = host.querySelector<HTMLSelectElement>('.single-settings select')!;
  expect([...select.options].map(option => option.value)).toEqual(['', 'anima']);
  await act(async () => {
    select.value = 'anima';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await changeText(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')!, 'standing by the sea');
  await vi.waitFor(() => expect(button(t('single.run')).disabled).toBe(false));
  await act(async () => button(t('single.run')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/queue', expect.objectContaining({
    service: 'comfyui', positive: 'standing by the sea', preset_id: 'anima',
    settings: expect.objectContaining({ family: 'anima', model, steps: 16 }),
    reference: { id: reference.id, guidance: 4.5 },
  }));
  await vi.waitFor(() => expect(host.querySelector('.single-result-head')?.textContent).toContain(t('single.state.queued')));
});

it.each(['file', 'gallery'])('previews a %s reference and returns to the existing draft on Escape', async source => {
  if (source === 'gallery') sendReferenceHandoff('example', 'chosen/source.png');
  await render();
  if (source === 'file') {
    const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { value: [new File(['image'], reference.name, { type: 'image/png' })] });
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith(endpoint + '/assets', {
      filename: reference.name, data_url: 'data:image/png;base64,aW1hZ2U=',
    }));
  }

  await vi.waitFor(() => expect(host.querySelector('.reference-card button[aria-haspopup="dialog"]')).not.toBeNull());
  const thumbnail = host.querySelector<HTMLButtonElement>('.reference-card button[aria-haspopup="dialog"]')!;
  expect(thumbnail.getAttribute('aria-label')).toBe(t('reference.open_preview', { name: reference.name }));
  const scene = host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')!;
  await changeText(scene, 'standing by the sea');
  await act(async () => thumbnail.click());
  const dialog = host.querySelector('[role="dialog"]');
  expect(dialog?.getAttribute('aria-label')).toBe(t('reference.preview_title', { name: reference.name }));
  expect(dialog?.querySelector('img')?.getAttribute('src')).toBe(reference.url);
  expect(document.activeElement).toBe(dialog);

  await act(async () => { dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(thumbnail);
  expect(host.querySelector('textarea[id$="-scene"]')).toBe(scene);
  expect(scene.value).toBe('standing by the sea');
  expect(openView).not.toHaveBeenCalled();
  expect(post).toHaveBeenCalledTimes(1);
});

it('takes an incomplete ComfyUI setup to installation settings', async () => {
  status = { ready: false, node_ready: false, weights_ready: false };
  await render();
  await vi.waitFor(() => expect(host.textContent).toContain(t('reference.weights_missing')));
  expect(host.textContent).toContain(t('reference.node_missing'));
  expect(button(t('single.run')).disabled).toBe(true);
  await act(async () => button(t('reference.open_install')).click());
  expect(openSettings).toHaveBeenCalledWith('install');
});

it('keeps generation disabled when ComfyUI only offers a MOSS model', async () => {
  const moss = 'moss/model.safetensors';
  qc.setQueryData(['image-catalog'], {
    ...catalog, models: [moss], defaults: { ...catalog.defaults, model: moss }, families: { models: { [moss]: 'moss' } },
  });
  sendReferenceHandoff('example', 'chosen/source.png');
  await render();
  await vi.waitFor(() => expect(host.textContent).toContain(t('reference.choose_anima_model')));
  await changeText(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')!, 'standing by the sea');
  expect(button(t('single.run')).disabled).toBe(true);
});
