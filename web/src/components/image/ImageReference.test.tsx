// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, post, put } from '../../api';
import { t } from '../../i18n';
import type { AnimaReferenceStatus, MossReferenceStatus, ReferenceStatus, SingleRun } from '../../imageTypes';
import { clearReferenceGalleryRequest, sendReferenceHandoff } from '../../lib/referenceHandoff';
import ImageReference from './ImageReference';
import type { Draft } from './referenceDraft';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn(), put: vi.fn() }));

const endpoint = '/api/works/example/image/reference';
const standalone = '/api/image/reference';
const emotionEndpoint = standalone + '/emotions';
const reference = { id: 'asset', name: 'source.png', url: endpoint + '/assets/asset', sha256: '5'.repeat(64) };
const secondReference = { id: 'asset-b', name: 'second.png', url: endpoint + '/assets/asset-b', sha256: '6'.repeat(64) };
const model = 'silvermoonmix.safetensors';
const animaEncoder = 'qwen_3_06b_base.safetensors';
const animaVae = 'qwen_image_vae.safetensors';
const mossModel = 'moss/moss-image-sft-dit-int8-convrot.safetensors';
const mossEncoder = 'moss-image-sft-qwen35-int8-convrot.safetensors';
const mossVae = 'moss-image-sft-vae.safetensors';
const otherMoss = 'moss/unsupported.safetensors';
const catalog = {
  connected: true, models: [model, mossModel, otherMoss], text_encoders: [animaEncoder, mossEncoder, 'unsupported_encoder.safetensors'],
  vaes: [animaVae, mossVae, 'unsupported_vae.safetensors'], loras: [],
  samplers: ['euler'], schedulers: ['simple', 'sgm_uniform'], nodes: { moss: true },
  families: { models: { [model]: 'anima', [mossModel]: 'moss', [otherMoss]: 'moss' } },
  defaults: { family: 'anima', model, text_encoder: animaEncoder, vae: animaVae },
};
const presets = [
  { id: 'anima', name: 'Silvermoon', service: 'comfyui', family: 'anima', settings: { model, steps: 16 } },
  { id: 'moss', name: 'MOSS style', service: 'comfyui', family: 'moss', settings: { model: mossModel } },
  { id: 'moss-slg', name: 'MOSS with SLG', service: 'comfyui', family: 'moss', settings: { moss_slg: true } },
  { id: 'sdxl', name: 'SDXL preset', service: 'comfyui', family: 'sdxl', settings: {} },
];
const openView = vi.fn();
const openSettings = vi.fn();
const adapterReady: ReferenceStatus = { ready: true, node_ready: true, weights_ready: true };
let status: AnimaReferenceStatus;
let mossStatus: MossReferenceStatus;
let history: SingleRun[];
let standaloneDraft: Partial<Draft> | null;
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

const render = async (active = true, workId: string | null = 'example') => act(async () => {
  root.render(<QueryClientProvider client={qc}><ImageReference workId={workId ?? undefined} openView={openView} openSettings={openSettings} active={active} /></QueryClientProvider>);
  await new Promise(resolve => setTimeout(resolve, 0));
});

const changeText = async (element: HTMLTextAreaElement | HTMLInputElement, value: string) => act(async () => {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
});
const changeSelect = async (element: HTMLSelectElement, value: string) => act(async () => {
  element.value = value;
  element.dispatchEvent(new Event('change', { bubbles: true }));
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  status = { ...adapterReady, adapters: { anima_v2: adapterReady, snapref: adapterReady }, stitch_ready: true };
  mossStatus = {
    ready: true, node_ready: true, edit_node_ready: true, weights_ready: true, foundation_ready: true,
    models: [mossModel], text_encoders: [mossEncoder], vaes: [mossVae],
  };
  history = [];
  standaloneDraft = null;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['image-catalog'], catalog);
  qc.setQueryData(['image-presets'], presets);
  qc.setQueryData(['image-reference-runs', 'example'], { runs: [] });
  vi.mocked(get).mockImplementation(async url => {
    if (url.endsWith('/reference/status?family=moss')) return mossStatus;
    if (url.endsWith('/reference/status?family=anima')) return status;
    if (url.endsWith('/runs')) return { runs: history };
    if (url === standalone + '/draft') return { draft: standaloneDraft, revision: 'draft-r1' };
    if (url === '/api/image/library/expressions') return {
      happy: { id: 'happy', name: 'Happy' },
      sad: { id: 'sad', name: 'Sad', targets: ['anima'] },
      startled: { id: 'startled', name: 'Startled', targets: ['moss'] },
    };
    if (url === '/api/image/library/compositions') return {
      park: { id: 'park', name: 'Park', targets: ['anima'] },
      street: { id: 'street', name: 'Street', targets: ['moss'] },
      layout: { id: 'layout', name: 'Layout', moss_layout: { mode: 'layout' } },
    };
    if (url.endsWith('/catalog')) return catalog;
    if (url.endsWith('/presets')) return presets;
    if (url === '/api/image/queue?paused_only=true') return { paused: false };
    throw new Error('Unexpected GET ' + url);
  });
  vi.mocked(put).mockResolvedValue({ revision: 'draft-r2' });
  vi.mocked(post).mockImplementation(async (url, body) => {
    if (url.endsWith('/assets')) return (body as { gallery_path?: string; filename?: string }).gallery_path === 'chosen/second.png'
      || (body as { filename?: string }).filename === secondReference.name ? secondReference : reference;
    if (url.endsWith('/queue')) {
      const { reference: submitted, ...request } = body as {
        positive: string; negative: string; settings: Record<string, unknown>; reference: { engine?: string };
      };
      history = [{
        id: 'job-1', status: 'queued', created_at: '2026-11-25', service: 'comfyui', seed: 7,
        request: { ...request, service: 'comfyui', preset_id: '' },
        actual: request, reference: submitted.engine === 'mossref' ? { ...reference, engine: 'mossref' } : { ...reference, guidance: 4.5 },
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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  clearReferenceGalleryRequest('example');
});

it('imports the gallery reference and queues the chosen Anima preset', async () => {
  sendReferenceHandoff('example', 'chosen/source.png');
  await render();
  await vi.waitFor(() => expect(host.querySelector<HTMLImageElement>('.reference-card img')?.getAttribute('src')).toBe(reference.url));
  expect(post).toHaveBeenCalledWith(endpoint + '/assets', { gallery_path: 'chosen/source.png' });
  expect(button(/^NovelAI/).disabled).toBe(true);
  expect(button('MOSS').disabled).toBe(false);
  expect(host.querySelector('.reference-generation-modes')).toBeNull();

  const select = host.querySelector<HTMLSelectElement>('.single-settings select')!;
  expect([...select.options].map(option => option.value)).toEqual(['', 'anima']);
  await changeSelect(select, 'anima');
  await changeText(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')!, 'standing by the sea');
  await vi.waitFor(() => expect(button(t('single.run')).disabled).toBe(false));
  await act(async () => button(t('single.run')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/queue', expect.objectContaining({
    service: 'comfyui', positive: 'standing by the sea', preset_id: 'anima',
    settings: expect.objectContaining({ family: 'anima', model, steps: 16 }),
    reference: { engine: 'anima_v2', subjects: [{ slot: 'a', id: reference.id, position: 'center' }], guidance: 4.5 },
  }));
  await vi.waitFor(() => expect(host.querySelector('.single-result-head')?.textContent).toContain(t('single.state.queued')));
});

it('previews and queues just the selected emotions with shared settings while keeping the single draft', async () => {
  standaloneDraft = {
    reference, description: 'red hair', second: { reference: secondReference, description: 'blue jacket' },
    positive: 'private single scene', negative: 'private negative', firstOnRight: true, guidance: '6',
    parameters: {
      anima: { settings: { family: 'anima', model, steps: 16 }, preset: 'anima' },
      moss: { settings: {}, preset: '' },
    },
  };
  const noComposition = { family: 'anima', expression_ids: ['happy'], composition: { mode: 'none' } };
  const selection = { ...noComposition, expression_ids: ['happy', 'sad'], composition: { mode: 'library', id: 'park' } };
  const rows = [
    { expression_id: 'happy', expression_name: 'Happy', composition_id: 'park', composition_name: 'Park',
      composition_omitted: false, positive: 'park, smile', negative: 'frown' },
    { expression_id: 'sad', expression_name: 'Sad', composition_id: 'park', composition_name: 'Park',
      composition_omitted: false, positive: 'park, tears', negative: 'smile' },
  ];
  vi.mocked(post).mockImplementation(async (url, body) => {
    if (url === emotionEndpoint + '/preview') {
      return body && (body as { expression_ids: string[] }).expression_ids.length === 2
        ? { rows, revision: 'multi' }
        : { rows: [{ ...rows[0], composition_id: null, composition_name: null }], revision: 'single' };
    }
    if (url === emotionEndpoint + '/queue') return { batch_id: 'new-batch', job_id: 'job-happy', count: 2 };
    throw new Error('Unexpected POST ' + url);
  });
  await render(true, null);
  await vi.waitFor(() => expect(button(t('reference.emotions_mode'))).toBeTruthy());
  await act(async () => button(t('reference.emotions_mode')).click());
  const form = host.querySelector<HTMLFormElement>('form.reference-emotions')!;
  expect(host.querySelector('[data-slot="a"] img')?.getAttribute('src')).toBe(reference.url);
  expect(host.querySelector('[data-slot="b"], .reference-subject-description, textarea')).toBeNull();
  await vi.waitFor(() => expect(form.querySelectorAll('input[type="checkbox"]')).toHaveLength(2));
  const [happy, sad] = [...form.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
  expect(form.textContent).not.toContain('Startled');
  const preview = () => button(t('reference.emotions_preview_action'));
  const queue = () => button(t('reference.emotions_queue'));
  expect(queue().disabled).toBe(true);
  await act(async () => happy.click());
  await act(async () => preview().click());
  expect(post).toHaveBeenCalledWith(emotionEndpoint + '/preview', noComposition);
  await vi.waitFor(() => expect(queue().disabled).toBe(false));
  await act(async () => sad.click());
  expect(queue().disabled).toBe(true);
  await act(async () => form.querySelector<HTMLInputElement>('input[value="library"]')!.click());
  const composition = form.querySelector('select')!;
  await vi.waitFor(() => expect([...composition.options].map(item => item.value)).toEqual(['', 'park']));
  expect(preview().disabled).toBe(true);
  await changeSelect(composition, 'park');
  await act(async () => preview().click());
  expect(post).toHaveBeenCalledWith(emotionEndpoint + '/preview', selection);
  expect(form.querySelectorAll('.reference-emotion-preview-list details')).toHaveLength(2);
  expect(form.textContent).toContain('park, smile');
  expect(form.textContent).toContain(t('reference.emotions_total', { count: 2 }));

  vi.mocked(post).mockRejectedValueOnce(new ApiError(409, { key: 'server.reference.emotions_stale', text: 'Stale preview' }));
  await act(async () => queue().click());
  expect(queue().disabled).toBe(true);
  expect(host.textContent).toContain(t('server.reference.emotions_stale'));
  await act(async () => preview().click());
  expect(host.textContent).not.toContain(t('server.reference.emotions_stale'));
  await act(async () => queue().click());
  expect(post).toHaveBeenLastCalledWith(emotionEndpoint + '/queue', {
    ...selection, preview_revision: 'multi',
    settings: expect.objectContaining({ family: 'anima', model, steps: 16 }),
    reference: { engine: 'anima_v2', guidance: 6, subjects: [{ slot: 'a', position: 'center', id: reference.id }] },
  });

  await act(async () => button(t('reference.single_mode')).click());
  expect(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')?.value).toBe('private single scene');
  expect(host.querySelector<HTMLTextAreaElement>('textarea[id$="-negative"]')?.value).toBe('private negative');
  expect(host.querySelector<HTMLInputElement>('[data-slot="a"] input')?.value).toBe('red hair');
  expect(host.querySelector<HTMLInputElement>('[data-slot="b"] input')?.value).toBe('blue jacket');
  expect(host.querySelector('[data-slot="b"] img')?.getAttribute('src')).toBe(secondReference.url);
});

it('uses MossRef and marks an incompatible linked composition in the preview', async () => {
  standaloneDraft = { reference };
  const selection = { family: 'moss', expression_ids: ['startled'], composition: { mode: 'linked' } };
  vi.mocked(post).mockImplementation(async url => {
    if (url === emotionEndpoint + '/preview') return {
      revision: 'moss-revision',
      rows: [{ expression_id: 'startled', expression_name: 'Startled', composition_id: null, composition_name: null,
        composition_omitted: true, positive: 'The person is startled', negative: '' }],
    };
    if (url === emotionEndpoint + '/queue') return { batch_id: 'moss-batch', job_id: 'job-startled', count: 1 };
    throw new Error('Unexpected POST ' + url);
  });
  await render(true, null);
  await vi.waitFor(() => expect(button(t('reference.emotions_mode'))).toBeTruthy());
  await act(async () => button(t('reference.emotions_mode')).click());
  await act(async () => button('MOSS').click());
  const form = host.querySelector<HTMLFormElement>('form.reference-emotions')!;
  await vi.waitFor(() => expect(form.textContent).toContain('Startled'));
  expect(form.textContent).not.toContain('Sad');
  await act(async () => [...form.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].at(-1)!.click());
  await act(async () => form.querySelector<HTMLInputElement>('input[value="linked"]')!.click());
  await act(async () => button(t('reference.emotions_preview_action')).click());
  expect(post).toHaveBeenCalledWith(emotionEndpoint + '/preview', selection);
  expect(form.textContent).toContain(t('reference.emotions_composition_omitted'));
  await vi.waitFor(() => expect(button(t('reference.emotions_queue')).disabled).toBe(false));
  await act(async () => button(t('reference.emotions_queue')).click());
  expect(post).toHaveBeenLastCalledWith(emotionEndpoint + '/queue', {
    ...selection, preview_revision: 'moss-revision',
    settings: expect.objectContaining({ family: 'moss', model: mossModel, text_encoder: mossEncoder, vae: mossVae }),
    reference: { id: reference.id, engine: 'mossref' },
  });
});

it('keeps an entire batch on one history page and restores a selected emotion as a single run', async () => {
  const actual = { positive: 'park, smile', negative: 'frown', settings: { family: 'anima', model, text_encoder: animaEncoder, vae: animaVae } };
  const saved: SingleRun = {
    id: 'happy-job', status: 'done', created_at: '2026-11-27', service: 'comfyui', seed: 7, actual,
    request: { ...actual, service: 'comfyui', preset_id: '' },
    image_url: '/example.png', path: '_reference/example.png',
    reference: { engine: 'anima_v2', scene: actual.positive, subjects: [{ ...reference, slot: 'a', position: 'center' }] },
  };
  const batch = { id: 'emotion-batch', composition_id: 'park', composition_name: 'Park', count: 2 };
  const happy: SingleRun = { ...saved, reference_batch: { ...batch, index: 0, expression_id: 'happy', expression_name: 'Happy' } };
  const sad: SingleRun = {
    ...saved, id: 'sad-job', status: 'failed', image_url: null,
    reference_batch: { ...batch, index: 1, expression_id: 'sad', expression_name: 'Sad' },
  };
  history = [
    ...Array.from({ length: 11 }, (_, index) => ({ ...saved, id: 'individual-' + index, path: '_reference/' + index + '.png' })),
    sad, { ...saved, id: 'older', path: '_reference/older.png' }, happy,
  ];
  qc.setQueryData(['image-reference-runs', undefined], { runs: history });
  await render(true, null);
  await vi.waitFor(() => expect(host.querySelector('.reference-history-batch')).toBeTruthy());
  const batchRows = [...host.querySelectorAll<HTMLButtonElement>('.reference-history-batch button')];
  expect(batchRows.map(row => row.querySelector('.single-history-name')?.textContent)).toEqual(['Happy', 'Sad']);
  expect(batchRows[1].textContent).toContain(t('single.state.failed'));
  await act(async () => batchRows[1].click());
  expect(button(t('single.retry')).disabled).toBe(false);
  await act(async () => batchRows[0].click());
  expect(host.querySelector('.single-canvas img')?.getAttribute('src')).toBe(saved.image_url);
  await act(async () => button(t('reference.emotions_mode')).click());
  await act(async () => button(t('single.restore')).click());
  expect(button(t('reference.single_mode')).getAttribute('aria-pressed')).toBe('true');
  expect(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')?.value).toBe(actual.positive);
  expect(host.querySelector<HTMLTextAreaElement>('textarea[id$="-negative"]')?.value).toBe(actual.negative);
  await act(async () => button(t('single.next_page')).click());
  expect(host.querySelector('.reference-history-batch')).toBeNull();
  expect(host.querySelector('.single-history-list button')?.textContent).toContain('older.png');
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

it('blocks an Anima draft with stale component selections until the actual selections are replaced', async () => {
  const staleEncoder = 'old-encoder.safetensors';
  const staleVae = 'old-vae.safetensors';
  localStorage.setItem('atelierx-reference-draft-example', JSON.stringify({
    reference, positive: 'a new scene', settings: { family: 'anima', model, text_encoder: staleEncoder, vae: staleVae },
  }));
  await render();
  const actions = host.querySelector('.single-prompts')!;
  await vi.waitFor(() => expect(actions.querySelector('.reference-status')?.textContent).toContain(staleEncoder));
  expect(actions.querySelector('.reference-status')?.textContent).toContain(staleVae);
  expect(button(t('single.run')).disabled).toBe(true);
  await act(async () => button(t('reference.open_models')).click());
  expect(openView).toHaveBeenCalledWith('models');

  const select = (key: string) => host.querySelector<HTMLSelectElement>(`[data-setting="${key}"] select`)!;
  await changeSelect(select('text_encoder'), animaEncoder);
  expect(actions.querySelector('.reference-status')?.textContent).not.toContain(staleEncoder);
  expect(button(t('single.run')).disabled).toBe(true);
  await changeSelect(select('vae'), animaVae);
  expect(button(t('single.run')).disabled).toBe(false);
  await act(async () => button(t('single.run')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/queue', expect.objectContaining({
    settings: expect.objectContaining({ model, text_encoder: animaEncoder, vae: animaVae }),
  }));
});

it('explains a lost ComfyUI connection beside generation and rechecks the connection', async () => {
  localStorage.setItem('atelierx-reference-draft-example', JSON.stringify({ reference, positive: 'new scene' }));
  qc.setQueryData(['image-catalog'], { ...catalog, connected: false });
  await render();
  expect(button(t('single.run')).disabled).toBe(true);
  expect(host.querySelector('.single-prompts .reference-status')?.textContent).toContain(t('gen.not_connected'));
  await act(async () => button(t('gen.open_settings')).click());
  expect(openSettings).toHaveBeenCalledWith('image');
  await vi.waitFor(() => expect(button(t('reference.recheck')).disabled).toBe(false));
  await act(async () => button(t('reference.recheck')).click());
  expect(get).toHaveBeenCalledWith('/api/image/catalog');
  await vi.waitFor(() => expect(button(t('single.run')).disabled).toBe(false));
});

it('keeps the legacy Anima draft and queues one MOSS reference with supported settings', async () => {
  localStorage.setItem('atelierx-reference-draft-example', JSON.stringify({
    positive: 'standing by the sea', negative: 'blur', settings: { family: 'anima', model, steps: 16 },
    preset: 'anima', reference, guidance: '7',
  }));
  await render();
  await act(async () => button('MOSS').click());
  const select = host.querySelector<HTMLSelectElement>('.single-settings select')!;
  const optionValues = (key: string) => [...host.querySelectorAll<HTMLOptionElement>(`[data-setting="${key}"] option`)].map(option => option.value);
  await vi.waitFor(() => expect(optionValues('model')).toEqual(['', mossModel]));
  expect(optionValues('text_encoder')).toEqual(['', mossEncoder]);
  expect(optionValues('vae')).toEqual(['', mossVae]);
  expect(select.value).toBe('');
  expect([...select.options].map(option => option.value)).toEqual(['', 'moss']);
  expect(host.textContent).not.toContain(t('reference.guidance'));
  expect(host.textContent).not.toContain(t('moss.slg'));
  expect(host.textContent).not.toContain(t('moss.components'));
  expect(host.textContent).not.toContain(t('moss.nodes_missing'));
  expect(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')?.value).toBe('standing by the sea');

  await changeSelect(select, 'moss');
  await act(async () => button('Anima').click());
  expect(select.value).toBe('anima');
  expect(host.querySelector<HTMLInputElement>('.reference-guidance input')?.value).toBe('7');
  await act(async () => button('MOSS').click());
  expect(select.value).toBe('moss');
  await vi.waitFor(() => expect(button(t('single.run')).disabled).toBe(false));
  await act(async () => button(t('single.run')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/queue', expect.objectContaining({
    positive: 'standing by the sea', negative: 'blur', preset_id: 'moss',
    settings: expect.objectContaining({
      family: 'moss', model: mossModel, text_encoder: mossEncoder, vae: mossVae, moss_slg: false, loras: [], steps: 35, cfg: 3.5,
    }),
    reference: { id: reference.id, engine: 'mossref' },
  }));
});

it('distinguishes missing local files from unverified remote files', async () => {
  mossStatus = { ...mossStatus, ready: false, edit_node_ready: false, foundation_ready: false };
  sendReferenceHandoff('example', 'chosen/source.png');
  await render();
  await act(async () => button('MOSS').click());
  await vi.waitFor(() => expect(host.textContent).toContain(t('reference.moss_edit_node_missing')));
  expect(host.textContent).toContain(t('reference.moss_foundation_missing'));
  expect(host.querySelector('a')?.getAttribute('href')).toContain('github.com/Neon3579/MossRef');
  await changeText(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')!, 'standing by the sea');
  expect(button(t('single.run')).disabled).toBe(true);

  mossStatus = { ...mossStatus, ready: true, edit_node_ready: true, foundation_ready: null, weights_ready: null };
  await act(async () => button(t('reference.recheck')).click());
  await vi.waitFor(() => expect(host.textContent).toContain(t('reference.moss_files_unverified')));
  expect(host.textContent).not.toContain(t('reference.moss_foundation_missing'));
  expect(button(t('single.run')).disabled).toBe(false);
});

it('retries a saved MOSS run from the Anima draft and keeps the paused queue waiting', async () => {
  status = { ready: false, node_ready: false, weights_ready: false };
  const actual = {
    positive: 'new scene', negative: '',
    settings: { family: 'moss', model: mossModel, text_encoder: mossEncoder, vae: mossVae },
  };
  history = [{
    id: 'moss-job', created_at: '2026-11-26', status: 'failed', service: 'comfyui', seed: 8,
    reference: { ...reference, engine: 'mossref' }, actual, request: { ...actual, service: 'comfyui', preset_id: '' },
  }];
  qc.setQueryData(['image-reference-runs', 'example'], { runs: history });
  qc.setQueryData(['image-queue', 'pause-state'], { paused: true });
  vi.mocked(post).mockImplementation(async url => {
    if (!url.endsWith('/retry')) throw new Error('Unexpected POST ' + url);
    history = [{ ...history[0], id: 'retried', status: 'queued' }, ...history];
    return { job_id: 'retried' };
  });
  await render();
  expect(button('Anima').getAttribute('aria-pressed')).toBe('true');
  await vi.waitFor(() => expect(button(t('single.retry')).disabled).toBe(false));
  await act(async () => button(t('single.retry')).click());
  expect(post).toHaveBeenCalledWith('/api/image/jobs/moss-job/retry');
  expect(post).not.toHaveBeenCalledWith('/api/image/queue/resume');
  await vi.waitFor(() => expect(host.textContent).toContain(t('queue.waiting_while_paused')));
});

it('restores a MossRef result and sends its saved path for regeneration and export', async () => {
  const path = '_single/example/result.png';
  const actual = {
    positive: 'a scene from Picture 1', negative: '',
    settings: { family: 'moss', model: mossModel, text_encoder: mossEncoder, vae: mossVae, seed: 21 },
  };
  history = [{
    id: 'result', created_at: '2026-11-26', status: 'done', service: 'comfyui', seed: 21, path,
    reference: { ...reference, engine: 'mossref' }, actual, request: { ...actual, service: 'comfyui', preset_id: '' },
  }];
  qc.setQueryData(['image-reference-runs', 'example'], { runs: history });
  vi.mocked(post).mockResolvedValue({ job_id: 'regenerated' });
  const copy = vi.fn(async () => new Response('zip'));
  vi.stubGlobal('fetch', copy);
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await render();
  await vi.waitFor(() => expect(button(t('single.restore')).disabled).toBe(false));
  expect(button('Anima').getAttribute('aria-pressed')).toBe('true');

  await vi.waitFor(() => expect(button(t('single.regenerate')).disabled).toBe(false));
  await act(async () => button(t('single.regenerate')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/regenerate', { path, same_seed: true });
  await act(async () => button(t('single.restore')).click());
  expect(button('MOSS').getAttribute('aria-pressed')).toBe('true');
  expect(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')?.value).toBe('a scene from Picture 1');
  await act(async () => button(t('gallery.download_zip')).click());
  expect(copy).toHaveBeenCalledWith(endpoint + '/export?path=' + encodeURIComponent(path) + '&include_reference=false', { credentials: 'same-origin' });
});

it('checks the selected saved adapter and Stitch independently of the ready draft', async () => {
  localStorage.setItem('atelierx-reference-draft-example', JSON.stringify({ reference, positive: 'different scene' }));
  const path = '_single/example/snapref.png';
  const actual = {
    positive: 'two people', negative: '',
    settings: { family: 'anima', model, text_encoder: animaEncoder, vae: animaVae, seed: 17 },
  };
  const savedInputs = {
    id: 'snap-result', created_at: '2026-11-26', service: 'comfyui', seed: 17, path, actual,
    request: { ...actual, service: 'comfyui', preset_id: '' },
    reference: { engine: 'snapref', scene: 'two people', subjects: [
      { ...reference, slot: 'a', position: 'left' }, { ...secondReference, slot: 'b', position: 'right' },
    ] },
  } as const;
  history = [{ ...savedInputs, status: 'done', reference: { ...savedInputs.reference, subjects: [...savedInputs.reference.subjects] } }];
  qc.setQueryData(['image-reference-runs', 'example'], { runs: history });
  status = { ...status, stitch_ready: false, adapters: {
    anima_v2: adapterReady, snapref: { ready: false, node_ready: true, weights_ready: false },
  } };
  vi.mocked(post).mockResolvedValue({ job_id: 'regenerated' });
  await render();
  await vi.waitFor(() => expect(button(t('single.run')).disabled).toBe(false));
  const result = host.querySelector('.single-result')!;
  expect(result.textContent).toContain(t('reference.snapref_weights_missing'));
  expect(result.textContent).toContain(t('reference.stitch_missing'));
  expect(button(t('single.regenerate')).disabled).toBe(true);
  expect(button(t('single.result_new_seed')).disabled).toBe(true);
  expect(button(t('single.restore')).disabled).toBe(false);
  expect(button(t('gallery.download_zip')).disabled).toBe(false);
  await act(async () => button(t('reference.open_install')).click());
  expect(openSettings).toHaveBeenCalledWith('install');

  status = { ...status, adapters: { anima_v2: adapterReady, snapref: adapterReady } };
  await act(async () => button(t('reference.recheck')).click());
  await vi.waitFor(() => expect(result.textContent).not.toContain(t('reference.snapref_weights_missing')));
  expect(button(t('single.regenerate')).disabled).toBe(true);
  status = { ...status, stitch_ready: true };
  await act(async () => button(t('reference.recheck')).click());
  await vi.waitFor(() => expect(button(t('single.result_new_seed')).disabled).toBe(false));
  expect(button(t('single.regenerate')).disabled).toBe(false);
  await act(async () => button(t('single.result_new_seed')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/regenerate', { path, same_seed: false });
});

it('shows missing frozen components beside retry even while the draft is ready', async () => {
  localStorage.setItem('atelierx-reference-draft-example', JSON.stringify({ reference, positive: 'different scene' }));
  const unavailable = 'lost-vae.safetensors';
  const actual = { positive: 'original scene', negative: '', settings: { family: 'moss', model: mossModel, text_encoder: mossEncoder, vae: unavailable } };
  history = [{
    id: 'failed-result', created_at: '2026-11-26', status: 'failed', service: 'comfyui', seed: 7,
    reference: { ...reference, engine: 'mossref' }, actual, request: { ...actual, service: 'comfyui', preset_id: '' },
  }];
  qc.setQueryData(['image-reference-runs', 'example'], { runs: history });
  await render();
  await vi.waitFor(() => expect(button(t('single.run')).disabled).toBe(false));
  expect(host.querySelector('.single-result .reference-status')?.textContent).toContain(unavailable);
  expect(button(t('single.retry')).disabled).toBe(true);
  expect(post).not.toHaveBeenCalled();
});

it('adds a second SnapRef subject from the gallery and swaps only their positions', async () => {
  sendReferenceHandoff('example', 'chosen/source.png');
  await render();
  const adapter = host.querySelector<HTMLSelectElement>('.reference-adapter select')!;
  expect(adapter.value).toBe('anima_v2');
  await changeSelect(adapter, 'snapref');
  const mode = host.querySelectorAll<HTMLSelectElement>('.reference-adapter select')[1];
  expect(mode.value).toBe('cs');
  await changeSelect(mode, 'char');
  expect(host.querySelector('[data-slot="b"]')).toBeNull();
  await act(async () => button(t('reference.add_subject')).click());
  const card = (slot: 'a' | 'b') => host.querySelector<HTMLElement>(`[data-slot="${slot}"]`)!;
  const field = (slot: 'a' | 'b') => card(slot).querySelector<HTMLInputElement>('input')!;
  await changeText(field('a'), 'red hair');
  await changeText(field('b'), 'blue jacket');
  const chooseGallery = [...card('b').querySelectorAll('button')].find(item => item.textContent === t('reference.choose_gallery'))!;
  await act(async () => chooseGallery.click());
  expect(openView).toHaveBeenCalledWith('gallery');
  await render(false);
  sendReferenceHandoff('example', 'chosen/second.png');
  await render();
  await vi.waitFor(() => expect(card('b').querySelector('img')?.getAttribute('src')).toBe(secondReference.url));
  expect(card('a').querySelector('img')?.getAttribute('src')).toBe(reference.url);
  await changeText(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')!, 'talking on a rooftop');
  await act(async () => button(t('reference.swap_positions')).click());
  expect(card('a').textContent).toContain(t('reference.position_right'));
  expect(card('b').textContent).toContain(t('reference.position_left'));
  expect([...host.querySelectorAll('[data-slot]')].map(item => item.getAttribute('data-slot'))).toEqual(['b', 'a']);
  expect(field('a').value).toBe('red hair');
  expect(field('b').value).toBe('blue jacket');
  await act(async () => button(t('single.run')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/queue', expect.objectContaining({
    positive: 'talking on a rooftop',
    reference: { engine: 'snapref', snapref_mode: 'char', subjects: [
      { slot: 'a', id: reference.id, position: 'right', description: 'red hair' },
      { slot: 'b', id: secondReference.id, position: 'left', description: 'blue jacket' },
    ] },
  }));
});

it('keeps a single SnapRef subject usable when Image Stitch is unavailable', async () => {
  status = { ...status, stitch_ready: false };
  sendReferenceHandoff('example', 'chosen/source.png');
  await render();
  await changeSelect(host.querySelector<HTMLSelectElement>('.reference-adapter select')!, 'snapref');
  await changeText(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')!, 'standing by the sea');
  await act(async () => button(t('reference.add_subject')).click());
  await vi.waitFor(() => expect(host.textContent).toContain(t('reference.stitch_missing')));
  expect(button(t('single.run')).disabled).toBe(true);
  await act(async () => button(t('reference.remove_subject')).click());
  await vi.waitFor(() => expect(button(t('single.run')).disabled).toBe(false));
  await act(async () => button(t('single.run')).click());
  expect(post).toHaveBeenCalledWith(endpoint + '/queue', expect.objectContaining({
    reference: { engine: 'snapref', snapref_mode: 'cs', subjects: [{ slot: 'a', id: reference.id, position: 'center' }] },
  }));
});

it.each([false, true])('restores a v8 scene and pair with preset applied: %s', async appliedPreset => {
  const path = '_single/example/pair.png';
  const actual = { positive: 'compiled prompt with subject directions', negative: '', settings: { family: 'anima', model, seed: 21 } };
  const saved = {
    engine: 'anima_v2', guidance: 8, scene: 'talking on a rooftop #after-dark',
    ...(appliedPreset ? { scene_prompt: 'talking on a rooftop #after-dark, ink drawing' } : {}),
    subjects: [
      { ...reference, slot: 'a', position: 'right', description: 'red hair' },
      { ...secondReference, slot: 'b', position: 'left', description: 'blue jacket' },
    ],
  } as const;
  history = [{
    id: 'result', created_at: '2026-11-26', status: 'done', service: 'comfyui', seed: 21, path,
    reference: { ...saved, subjects: [...saved.subjects] }, actual, request: { ...actual, service: 'comfyui', preset_id: '' },
  }];
  qc.setQueryData(['image-reference-runs', 'example'], { runs: history });
  await render();
  await changeSelect(host.querySelector<HTMLSelectElement>('.reference-adapter select')!, 'snapref');
  await act(async () => button(t('single.restore')).click());
  expect(host.querySelector<HTMLSelectElement>('.reference-adapter select')?.value).toBe('anima_v2');
  expect(host.querySelector<HTMLTextAreaElement>('textarea[id$="-scene"]')?.value)
    .toBe('talking on a rooftop \\#after-dark' + (appliedPreset ? ', ink drawing' : ''));
  expect(host.querySelector<HTMLInputElement>('.reference-guidance input')?.value).toBe('8');
  expect(host.querySelector<HTMLInputElement>('[data-slot="a"] input')?.value).toBe('red hair');
  expect(host.querySelector<HTMLInputElement>('[data-slot="b"] input')?.value).toBe('blue jacket');
  expect(host.querySelector('[data-slot="a"]')?.textContent).toContain(t('reference.position_right'));
  expect(host.querySelector('[data-slot="b"]')?.textContent).toContain(t('reference.position_left'));
  expect(host.textContent).toContain(t('reference.include_originals'));
});

it('restores a legacy Anima result as one subject and preserves its guidance', async () => {
  const actual = {
    positive: 'legacy scene', negative: '',
    settings: { family: 'anima', model, text_encoder: animaEncoder, vae: animaVae, seed: 7 },
  };
  history = [{
    id: 'legacy', created_at: '2026-11-26', status: 'done', service: 'comfyui', seed: 7, path: '_single/example/legacy.png',
    reference: { ...reference, guidance: 7 }, actual, request: { ...actual, service: 'comfyui', preset_id: '' },
  }];
  qc.setQueryData(['image-reference-runs', 'example'], { runs: history });
  await render();
  await act(async () => button(t('reference.add_subject')).click());
  await changeSelect(host.querySelector<HTMLSelectElement>('.reference-adapter select')!, 'snapref');
  await vi.waitFor(() => expect(button(t('single.regenerate')).disabled).toBe(false));
  await act(async () => button(t('single.restore')).click());
  expect(host.querySelector<HTMLSelectElement>('.reference-adapter select')?.value).toBe('anima_v2');
  expect(host.querySelector<HTMLInputElement>('.reference-guidance input')?.value).toBe('7');
  expect(host.querySelector('[data-slot="b"]')).toBeNull();
});
