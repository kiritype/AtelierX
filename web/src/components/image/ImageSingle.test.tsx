// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import type { PromptSource, SingleRun } from '../../imageTypes';
import { takeToolHandoff } from '../../lib/toolHandoff';
import { sendToLab } from './ImageLab';
import ImageSingle from './ImageSingle';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));
vi.mock('./ImageLab', () => ({ sendToLab: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
let rows: SingleRun[];
const openView = vi.fn();
const catalog = { connected: true, models: ['m.safetensors'], text_encoders: ['t.safetensors'], vaes: ['v.safetensors'],
  loras: [], samplers: ['euler'], schedulers: ['normal'], defaults: { family: 'anima', model: 'm.safetensors',
    text_encoder: 't.safetensors', vae: 'v.safetensors', sampler: 'euler', scheduler: 'normal', seed: -1 } };
const services = { max_images_per_run: 50, services: [
  { id: 'novelai', name: 'NovelAI', supported: true, connected: true, key: 'secret:n', interval: 3 },
  { id: 'pixai', name: 'PixAI', supported: true, connected: true, key: 'secret:p', interval: 3 },
] };
const positive = () => host.querySelector('textarea[id$="-positive"]') as HTMLTextAreaElement;
const negative = () => host.querySelector('textarea[id$="-negative"]') as HTMLTextAreaElement;
const button = (label: string) => {
  const found = [...host.querySelectorAll('button')].find(b => b.textContent?.trim() === label);
  expect(found, label).toBeTruthy();
  return found!;
};
const click = async (label: string) => act(async () => { button(label).click(); });
async function edit(element: HTMLTextAreaElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
const publish = async () => act(async () => { await qc.invalidateQueries({ queryKey: ['image-single-runs', 'synthetic'] }); await new Promise(resolve => setTimeout(resolve, 0)); });

beforeEach(async () => {
  vi.clearAllMocks();
  takeToolHandoff();
  localStorage.clear();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  rows = [];
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['image-catalog'], catalog);
  qc.setQueryData(['image-services'], services);
  qc.setQueryData(['image-presets'], [{ id: 'soft', name: 'Soft', service: 'comfyui', family: 'anima',
    settings: {}, artist: { positive: 'soft light', negative: '' } }]);
  qc.setQueryData(['image-single-runs', 'synthetic'], { runs: [] });
  vi.mocked(get).mockImplementation(async url => {
    if (url.endsWith('/single/runs')) return { runs: [...rows] };
    if (url.endsWith('/novelai/info')) return { models: [{ id: 'nai-test', name: 'Test' }], samplers: ['euler'], noise_schedules: ['karras'],
      defaults: { model: 'nai-test', width: 1024, height: 1024, seed: -1, steps: 20, scale: 5, sampler: 'euler', noise_schedule: 'karras' }, free: { pixels: 0, steps: 0 } };
    if (url.endsWith('/pixai/info')) return { models: [{ id: '123456', name: 'Test', type: 'sdxl' }], aspect_ratios: ['1:1'], sizes: ['1k'], modes: ['standard'], samplers: ['Euler'], max_loras: 5, loras: [],
      defaults: { model: '123456', aspect_ratio: '1:1', size: '1k', mode: 'standard', sampler: 'Euler', steps: 20, cfg_scale: 5, seed: -1, loras: [] } };
    return {};
  });
  vi.mocked(post).mockImplementation(async (url, body) => {
    if (url.endsWith('/single')) {
      const request = body as { positive: string; negative: string; service: 'comfyui' | 'novelai' | 'pixai'; settings: Record<string, unknown>; preset_id?: string };
      const id = `job-${rows.length + 1}`;
      rows.unshift({ id, status: 'queued', created_at: '2026-10-13', service: request.service, seed: 17,
        request: { positive: request.positive, negative: request.negative, service: request.service, settings: request.settings, preset_id: request.preset_id ?? '' },
        actual: { positive: request.positive, negative: request.negative, settings: { ...request.settings, seed: 17 } } });
      return { job_id: id };
    }
    if (url.endsWith('/cancel')) { rows[0].status = 'cancelled'; return { ok: true }; }
    if (url.endsWith('/retry')) { rows.unshift({ ...rows[0], id: `job-${rows.length + 1}`, status: 'queued' }); return { job_id: rows[0].id }; }
    if (url.endsWith('/tools/gallery')) return { items: [{ id: 'tool-1' }] };
    return { ok: true };
  });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><ImageSingle workId="synthetic" openView={openView} /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); });

it('keeps both prompts across services and submits a real queued request', async () => {
  await edit(positive(), 'Two people beside a lake'); await edit(negative(), 'blur');
  await click('NovelAI'); await click('PixAI'); await click('ComfyUI');
  expect(positive().value).toBe('Two people beside a lake');
  expect(negative().value).toBe('blur');
  await click(t('single.run'));
  expect(post).toHaveBeenCalledWith('/api/works/synthetic/image/single', expect.objectContaining({
    positive: 'Two people beside a lake', negative: 'blur', service: 'comfyui',
  }));
  expect(host.querySelector('[role="status"]')?.textContent).toBe(t('single.state.queued'));
  expect(button(t('single.multi')).hasAttribute('disabled')).toBe(true);
});

it('cancels, retries, restores and regenerates the saved request', async () => {
  await edit(positive(), 'Original'); await edit(negative(), 'No blur');
  await click(t('single.run'));
  await click(t('common.cancel'));
  expect(rows[0].status).toBe('cancelled');
  await edit(positive(), 'New draft');
  await click(t('single.retry'));
  expect(rows[0].request?.positive).toBe('Original');
  rows[0] = { ...rows[0], status: 'done', image_url: '/api/image/files/_single/synthetic/a.png', path: '_single/synthetic/a.png',
    actual: { positive: 'Preserved tag, Original', negative: 'No blur, preserved negative', settings: { ...rows[0].actual.settings, cfg: 6.5 } } };
  await publish();
  expect(button(t('single.restore')).hasAttribute('disabled')).toBe(false);
  const diff = host.querySelector('.single-result-diff');
  expect(diff?.textContent).toContain('New draft');
  expect(diff?.textContent).toContain('Preserved tag, Original');
  expect(diff?.textContent).toContain('6.5');
  const beforeRestore = vi.mocked(post).mock.calls.length;
  await click(t('single.restore'));
  expect(post).toHaveBeenCalledTimes(beforeRestore);
  expect(host.querySelector('.single-result-diff')).toBeNull();
  expect(positive().value).toBe('Preserved tag, Original'); expect(negative().value).toBe('No blur, preserved negative');
  await edit(positive(), 'Keep this draft');
  await click(t('single.regenerate'));
  expect(rows[0].request?.positive).toBe('Preserved tag, Original');
  expect(rows[0].request?.negative).toBe('No blur, preserved negative');
  expect(rows[0].request?.preset_id).toBe('');
  expect(rows[0].request?.settings.cfg).toBe(6.5);
  expect(rows[0].request?.settings.seed).toBe(17);
  expect(positive().value).toBe('Keep this draft');
  expect(button(t('single.result_new_seed')).disabled).toBe(true);
  rows[0].status = 'done';
  await publish();
  await click(t('single.result_new_seed'));
  expect(rows[0].request?.settings).toMatchObject({ cfg: 6.5, seed: -1 });
  expect(rows[0].request?.positive).toBe('Preserved tag, Original');
  expect(positive().value).toBe('Keep this draft');
});

it('previews preset common tags and compares the saved final prompt', async () => {
  qc.setQueryData(['image-lib', 'common', 'synthetic'], { glow: { prompt: ['warm daylight # note'], target: 'positive' } });
  qc.setQueryData(['image-presets'], [{ id: 'soft', name: 'Soft', service: 'comfyui', family: 'anima',
    common: ['glow'], settings: {}, artist: { positive: 'soft light', negative: '' } }]);
  await edit(positive(), 'forest');
  await act(async () => { (host.querySelector('.single-field select') as HTMLSelectElement).value = 'soft';
    host.querySelector('.single-field select')!.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(host.querySelector('.single-details pre')?.textContent).toContain('warm daylight, forest, soft light');
  rows.unshift({ id: 'saved', status: 'done', created_at: '2026-10-13', service: 'comfyui', seed: 42,
    request: { positive: 'forest', negative: '', service: 'comfyui', settings: {}, preset_id: 'soft' },
    actual: { positive: 'warm daylight, forest, soft light', negative: 'low quality', generation_preset: { name: 'Archived Soft' },
      settings: { family: 'anima', model: 'historical.safetensors', width: 768, height: 1024, steps: 24, cfg: 6.5, seed: 42 } },
    image_url: '/api/image/files/_single/synthetic/a.png', path: '_single/synthetic/a.png' });
  await publish();
  const summary = host.querySelector('.single-result-summary');
  expect(summary?.textContent).toContain('Archived Soft');
  expect(summary?.textContent).toContain('768 × 1024');
  expect(summary?.textContent).toContain('historical.safetensors');
  expect(summary?.textContent).toContain(t('single.result_missing'));
  expect(summary?.textContent).not.toContain('m.safetensors');
  await click(t('single.compare'));
  expect(sendToLab).toHaveBeenCalledWith(expect.objectContaining({ positive: 'warm daylight, forest, soft light', negative: 'low quality', source: '_single/synthetic/a.png' }));
});

it('keeps manual prompts when changing frozen styles and ignores later preset edits or deletion', async () => {
  qc.setQueryData(['image-presets'], [
    { id: 'soft', name: 'Soft', service: 'comfyui', family: 'anima', common: [], settings: {}, artist: { positive: 'soft light', negative: 'soft shadows' } },
    { id: 'crisp', name: 'Crisp', service: 'comfyui', family: 'anima', common: [], settings: {}, artist: { positive: 'crisp detail', negative: 'haze' } },
  ]);
  await edit(positive(), 'forest, (mist:1.2)'); await edit(negative(), 'blur, (noise:0.7)');
  const selectPreset = async (id: string) => act(async () => {
    const select = host.querySelector('.single-field select') as HTMLSelectElement;
    select.value = id; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await selectPreset('soft');
  expect(positive().value).toBe('forest, (mist:1.2)');
  expect(negative().value).toBe('blur, (noise:0.7)');
  expect(host.querySelector('.single-details pre')?.textContent).toContain('forest, (mist:1.2), soft light');
  await selectPreset('crisp');
  expect(positive().value).toBe('forest, (mist:1.2)');
  expect(negative().value).toBe('blur, (noise:0.7)');
  expect(host.querySelector('.single-details pre')?.textContent).toContain('forest, (mist:1.2), crisp detail');

  qc.setQueryData(['image-presets'], [{ id: 'crisp', name: 'Crisp revised', service: 'comfyui', family: 'anima', common: [], settings: {}, artist: { positive: 'changed live text', negative: 'changed live negative' } }]);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(host.querySelector('.single-details pre')?.textContent).toContain('crisp detail');
  expect(host.querySelector('.single-details pre')?.textContent).not.toContain('changed live text');
  qc.setQueryData(['image-presets'], []);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(host.querySelector('.single-details pre')?.textContent).toContain('crisp detail');
  await click(t('single.run'));
  expect(post).toHaveBeenCalledWith('/api/works/synthetic/image/single', expect.objectContaining({
    positive: 'forest, (mist:1.2)', negative: 'blur, (noise:0.7)',
    prompt_sources: expect.arrayContaining([expect.objectContaining({ kind: 'style', id: 'crisp', positive: 'crisp detail' })]),
  }));
});

it('restores frozen source metadata and removes only the selected material', async () => {
  const sources: PromptSource[] = [
    { kind: 'direct', id: '', name: '', positive: 'forest, \\#literal', negative: 'blur' },
    { kind: 'common', id: 'old', name: 'Old common', positive: 'warm # frozen note', negative: '' },
    { kind: 'style', id: 'old-style', name: 'Old style', positive: '(soft light:1.1)', negative: 'haze' },
  ];
  rows.unshift({ id: 'frozen', status: 'done', created_at: '2026-10-13', service: 'comfyui', seed: 42,
    request: { positive: 'forest, \\#literal', negative: 'blur', service: 'comfyui', settings: {}, preset_id: '' },
    actual: { positive: 'warm # frozen note, forest, \\#literal, (soft light:1.1)', negative: 'blur, haze', settings: { seed: 42 }, prompt_sources: sources },
    image_url: '/api/image/files/_single/synthetic/a.png', path: '_single/synthetic/a.png' });
  await publish();
  await click(t('single.restore'));
  expect(positive().value).toBe('forest, \\\\#literal');
  expect(negative().value).toBe('blur');
  const sourceDetails = host.querySelector('.prompt-source-detail') as HTMLDetailsElement;
  sourceDetails.open = true;
  expect(sourceDetails.textContent).toContain('warm # frozen note');
  const remove = [...sourceDetails.querySelectorAll<HTMLButtonElement>('button')].find(item => item.getAttribute('aria-label') === t('materials.remove', { name: 'Old common' }))!;
  await act(async () => { remove.click(); });
  expect(sourceDetails.textContent).not.toContain('warm # frozen note');
  expect(sourceDetails.textContent).toContain('(soft light:1.1)');
  await click(t('single.run'));
  const submitted = vi.mocked(post).mock.calls.find(([url]) => url.endsWith('/single'))?.[1] as { prompt_sources: PromptSource[] };
  expect(submitted.prompt_sources.map(source => source.kind)).toEqual(['direct', 'style']);
  expect(submitted.prompt_sources[0].positive).toBe(sources[0].positive);
  expect(submitted.prompt_sources.find(source => source.kind === 'style')?.positive).toBe('(soft light:1.1)');
});

it('hands a saved image to tools and keeps unsupported comparison disabled', async () => {
  rows.unshift({ id: 'saved', status: 'done', created_at: '2026-10-13', service: 'novelai', seed: 42,
    request: { positive: 'scene', negative: '', service: 'novelai', settings: {}, preset_id: '' },
    actual: { positive: 'scene', negative: '', settings: { seed: 42 } },
    image_url: '/api/image/files/_single/synthetic/a.png', path: '_single/synthetic/a.png' });
  await publish();
  expect(button(t('single.compare')).hasAttribute('disabled')).toBe(true);
  expect(host.querySelector('.single-result-details')?.textContent).toContain(t('single.compare_comfy_only'));
  await click(t('single.send_tools'));
  expect(post).toHaveBeenCalledWith('/api/image/tools/gallery', { paths: ['_single/synthetic/a.png'] });
  expect(takeToolHandoff()).toBe('tool-1');
  expect(openView).toHaveBeenCalledWith('tools');
});

it('pages six recent results, preserves the draft on selection, and opens a detailed image dialog', async () => {
  await edit(positive(), 'Unchanged draft');
  rows = Array.from({ length: 7 }, (_, index): SingleRun => ({
    id: `saved-${index}`, status: 'done', created_at: `2026-10-${String(13 - index).padStart(2, '0')}T10:30:00`,
    service: 'comfyui', seed: index,
    request: { positive: `image ${index}`, negative: '', service: 'comfyui', settings: {}, preset_id: '' },
    actual: { positive: `final image ${index}`, negative: 'blur', settings: { seed: index } },
    image_url: `/api/image/files/_single/synthetic/file_${index}.png`, path: `_single/synthetic/file_${index}.png`,
  }));
  await publish();
  expect(host.querySelectorAll('.single-history-row')).toHaveLength(6);
  expect(host.querySelector('.single-history-thumb')?.getAttribute('src')).toContain('file_0.png');
  expect(host.querySelector('.single-history-name')?.getAttribute('title')).toBe('file_0.png');
  await click(t('single.next_page'));
  expect(host.querySelectorAll('.single-history-row')).toHaveLength(1);
  await act(async () => { (host.querySelector('.single-history-row') as HTMLButtonElement).click(); });
  expect(positive().value).toBe('Unchanged draft');
  expect(host.querySelector('.single-history-row')?.getAttribute('aria-pressed')).toBe('true');
  const preview = host.querySelector('button.single-canvas') as HTMLButtonElement;
  preview.focus();
  await act(async () => { preview.click(); });
  const dialog = host.querySelector('[role="dialog"]') as HTMLDivElement;
  expect(dialog?.getAttribute('aria-modal')).toBe('true');
  expect(dialog.querySelector('.gallery-detail-image img')?.getAttribute('src')).toContain('file_6.png');
  expect(dialog.textContent).toContain('final image 6');
  expect(dialog.textContent).toContain(t('single.regenerate'));
  expect(dialog.textContent).toContain(t('single.send_tools'));
  await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })); });
  expect(dialog.contains(document.activeElement)).toBe(true);
  await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })); });
  expect(document.activeElement).toBe([...dialog.querySelectorAll('summary')].at(-1));
  await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(preview);
  await act(async () => { preview.click(); });
  const modalTools = [...host.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(item => item.textContent === t('single.send_tools'))!;
  await act(async () => { modalTools.click(); });
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(openView).toHaveBeenCalledWith('tools');
});

it('replays literal hashes in the saved prompt and does not carry over the current style preset', async () => {
  await edit(positive(), 'Unsaved draft');
  await act(async () => {
    const preset = host.querySelector('.single-field select') as HTMLSelectElement;
    preset.value = 'soft';
    preset.dispatchEvent(new Event('change', { bubbles: true }));
  });
  rows.unshift({ id: 'past', status: 'done', created_at: '2026-10-13', service: 'comfyui', seed: 0,
    request: null, actual: { positive: '#compass, pose', negative: 'text, #caption', settings: { seed: 0 } } });
  await publish();
  await click(t('single.regenerate'));
  expect(rows[0].request).toMatchObject({
    positive: '\\#compass, pose', negative: 'text, \\#caption', preset_id: '', settings: { seed: 0 },
  });
  expect(positive().value).toBe('Unsaved draft');
  expect((host.querySelector('.single-field select') as HTMLSelectElement).value).toBe('soft');
});

it('replaces and clears a restored shot without changing direct input', async () => {
  const source = {
    kind: 'composition' as const, id: 'shot:face:side:high', name: 'Saved shot',
    positive: 'portrait, from side, from above', negative: '',
  };
  qc.setQueryData(['image-lib-rules'], { shot_choices: {
    framing: { face: { prompt: 'portrait' }, upper: { prompt: 'upper body' }, cowboy: { prompt: 'cowboy shot' }, full: { prompt: 'full body' } },
    direction: { front: 'straight-on', three_quarter: 'three-quarter view', side: 'from side', back: 'from behind' },
    height: { eye: 'eye level', high: 'from above', low: 'from below' },
  } });
  rows = [{
    id: 'shot-run', status: 'done', created_at: '2026-10-13', service: 'comfyui', seed: 17,
    request: { service: 'comfyui', positive: 'by a window', negative: 'blur', preset_id: '', settings: {}, prompt_sources: [source] },
    actual: { positive: 'by a window, portrait, from side, from above', negative: 'blur', settings: {},
      prompt_sources: [{ kind: 'direct', id: '', name: '', positive: 'by a window', negative: 'blur' }, source] },
  }];
  await publish();
  await click(t('single.restore'));
  expect(positive().value).toBe('by a window');
  const choose = async (key: string) => {
    const input = [...host.querySelectorAll('label')].find(label => label.textContent === t(key))?.querySelector('input');
    expect(input?.type).toBe('radio');
    await act(async () => input!.click());
  };
  expect(host.querySelector('.single-form')?.textContent).toContain(source.positive);
  await choose('shot.framing.full');
  expect(host.querySelector('.single-form')?.textContent).not.toContain(source.positive);
  expect(host.querySelector('.single-form')?.textContent).toContain('full body, from side, from above');
  expect(positive().value).toBe('by a window');
  await choose('shot.mode.auto');
  expect(host.querySelector('.single-form')?.textContent).not.toContain('full body, from side, from above');
  expect(positive().value).toBe('by a window');
  expect(negative().value).toBe('blur');
});
